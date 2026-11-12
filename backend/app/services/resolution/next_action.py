"""What is missing before a refund, and a short explanation of the next action.

`missing_before_refund`, the facts and the template summary are deterministic code. The
optional AI explanation rewrites the same structured facts (never chat messages or free-text
promise wording) and is accepted only if every amount, date and number in it appears in those
facts; otherwise the code template is returned. Nothing here approves or submits a refund.
"""

from app.schemas.next_action import (
    CaseFacts as CaseFacts,
    Explanation as Explanation,
    MissingCode as MissingCode,
    MissingItem as MissingItem,
    NextAction as NextAction,
    Prerequisite as Prerequisite,
    RefundFacts as RefundFacts,
)


import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from app.services.ai.extraction import (
    AMOUNT,
    GROQ_DATA_POLICY,
    MAX_COMPLETION_TOKENS,
    _failure_reason,
    _log_failure,
)
from app.services.resolution.workspace import ResolutionWorkspace

logger = logging.getLogger(__name__)
ZERO = Decimal("0.00")
AI_LABEL = "AI explanation – verify before acting"

KIND_NAMES = {
    "return": "return",
    "replacement": "replacement",
    "order_cancellation": "order cancellation",
    "subscription": "subscription change",
    "store_credit_or_exchange": "store credit or exchange",
    "billing_correction": "billing correction",
    "dispute_handoff": "dispute handoff",
    "refund": "refund",
}
ACTIONS = {
    "refund_required": "review a refund of {recommended}",
    "awaiting_prerequisite": "confirm the {prerequisite} before any refund",
    "awaiting_condition": "verify the agreed condition before any refund",
    "awaiting_acceptance": "record the accepted agreement before any refund",
    "refund_pending": "wait for PayPal to confirm the pending refund",
    "execution_pending": "wait for the submitted refund to finish",
    "execution_failed": "review the failed refund attempt before trying again",
    "promise_review": "review the promise evidence before any refund",
    "provider_review": "review the PayPal evidence before any refund",
    "fulfilled": "no further refund is needed",
    "closed": "no action; the payment case is closed",
    "no_commitment": "record the agreed refund amount on the payment case",
}


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def collect(case_id, merchant_id, store, now: datetime | None = None) -> NextAction:
    now = now or datetime.now(UTC)
    workspace = ResolutionWorkspace(store)
    with store.transaction() as connection:
        case = workspace._case(connection, case_id, merchant_id)
        view = workspace._view(connection, case)
        legacy = workspace._legacy(connection, case)
        basis = store._reconcile(connection, legacy) if legacy is not None else None
    facts = CaseFacts(payment_linked=legacy is not None)
    missing: list[MissingItem] = []
    if legacy is None:
        missing.append(
            MissingItem(
                code="no_linked_payment", text="No payment is linked to this case."
            )
        )
    else:
        commitment = legacy.commitment
        facts.captured_amount = legacy.payment.captured_amount
        facts.agreed_amount = commitment.amount if commitment else None
        facts.agreement_status = commitment.status if commitment else None
        facts.reconciliation_status = basis.status
        facts.recommended_refund_amount = basis.recommended_refund_amount
        if commitment is None:
            missing.append(
                MissingItem(
                    code="no_amount",
                    text="The payment case has no agreed refund amount.",
                )
            )
        elif commitment.status != "accepted":
            missing.append(
                MissingItem(
                    code="agreement_not_accepted",
                    text="The refund agreement is not accepted on the payment case yet.",
                )
            )
        if basis.status == "awaiting_condition":
            missing.append(
                MissingItem(
                    code="unmet_condition",
                    text="The agreed refund condition is not verified yet.",
                )
            )
    by_id = {promise.id: promise for promise in view.promises}
    refunds = [
        promise for promise in view.promises if promise.terms.target.kind == "refund"
    ]
    if not refunds:
        missing.append(
            MissingItem(
                code="no_refund_promise",
                text="No refund promise is recorded on this case.",
            )
        )
    for promise in refunds:
        progress = promise.refund_progress
        prerequisites = [
            Prerequisite(
                name=KIND_NAMES.get(by_id[ref].terms.target.kind, "prerequisite"),
                done=by_id[ref].outcome == "fulfilled",
            )
            for ref in promise.terms.requires
            if ref in by_id
        ]
        if promise.terms.due_at is None:
            missing.append(
                MissingItem(
                    code="no_deadline",
                    promise_id=promise.id,
                    text="The refund promise has no due date.",
                )
            )
        for item in prerequisites:
            if not item.done:
                missing.append(
                    MissingItem(
                        code="unmet_condition",
                        promise_id=promise.id,
                        text=f"The {item.name} is not confirmed yet.",
                    )
                )
        if progress is None:
            continue
        pending = max(
            progress.provider_pending_amount,
            basis.pending_refund_amount if basis else ZERO,
        )
        if pending > ZERO:
            missing.append(
                MissingItem(
                    code="pending_refund_unconfirmed",
                    promise_id=promise.id,
                    text=f"{money(pending)} is pending and not yet confirmed by PayPal.",
                )
            )
        elif (
            basis is not None
            and basis.completed_refund_amount > progress.provider_completed_amount
        ):
            missing.append(
                MissingItem(
                    code="pending_refund_unconfirmed",
                    promise_id=promise.id,
                    text="A recorded refund is not yet confirmed by PayPal.",
                )
            )
        facts.refunds.append(
            RefundFacts(
                promise_id=promise.id,
                promised_amount=progress.promised_amount,
                refunded_amount=progress.provider_completed_amount,
                pending_amount=pending,
                remaining_amount=progress.outstanding_amount,
                due_date=promise.terms.due_at.date() if promise.terms.due_at else None,
                days_since_promise=max((now - promise.created_at).days, 0),
                prerequisites=prerequisites,
            )
        )
    return NextAction(
        case_id=case_id, facts=facts, missing=missing, summary=template(facts)
    )


def _action(facts: CaseFacts, default: str, open_items: list[str]) -> str:
    """The action for the reconciliation status, with every placeholder filled from the facts."""
    return ACTIONS.get(facts.reconciliation_status or "", default).format(
        recommended=money(facts.recommended_refund_amount or ZERO),
        prerequisite=" and ".join(open_items) or "prerequisite",
    )


def template(facts: CaseFacts) -> str:
    """Plain-English next step built only from the facts."""
    if not facts.payment_linked:
        return "No payment is linked → link the payment before any refund."
    if not facts.refunds:
        action = _action(facts, "record the agreed refund promise first", [])
        return f"No refund promise is recorded → {action}."
    first = facts.refunds[0]
    parts = [
        f"Promised {money(first.promised_amount)}"
        + (
            " after " + " and ".join(item.name for item in first.prerequisites)
            if first.prerequisites
            else ""
        )
    ]
    parts.append(f"{money(first.refunded_amount)} refunded")
    if first.pending_amount > ZERO:
        parts.append(f"{money(first.pending_amount)} pending")
    parts.append(f"{money(first.remaining_amount)} remaining")
    parts += [
        f"{item.name} {'confirmed' if item.done else 'not confirmed'}"
        for item in first.prerequisites
    ]
    open_items = [item.name for item in first.prerequisites if not item.done]
    action = _action(facts, "review the case evidence", open_items)
    more = (
        f" ({len(facts.refunds) - 1} more refund promise{'s' if len(facts.refunds) > 2 else ''} on this case.)"
        if len(facts.refunds) > 1
        else ""
    )
    return "; ".join(parts) + f" → {action}." + more


# Fact guard

MONTHS = "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
MONTH_NUMBER = {
    name: index
    for index, name in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        start=1,
    )
}
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
NAMED_DATE = re.compile(
    rf"\b({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
    re.IGNORECASE,
)
DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS})\.?(?:,?\s+(\d{{4}}))?\b",
    re.IGNORECASE,
)
NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")
CLAIMS = re.compile(
    r"\b(approved|authori[sz]ed?|authori[sz]ation|has been (?:sent|issued|paid))\b",
    re.IGNORECASE,
)


def _walk(value):
    if isinstance(value, BaseModel):
        for item in value.__dict__.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def guard(text: str, facts: CaseFacts) -> list[str]:
    """Every amount, date and number in `text` must come from `facts`. Returns the violations."""
    values = list(_walk(facts))
    amounts = {
        value.quantize(Decimal("0.01"))
        for value in values
        if isinstance(value, Decimal)
    }
    dates = {value for value in values if isinstance(value, date)}
    integers = {
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool)
    }
    violations, spans = [], []

    for match in AMOUNT.finditer(text):
        whole, cents = (
            (match.group(1), match.group(2))
            if match.group(1)
            else (match.group(3), match.group(4))
        )
        amount = Decimal(whole.replace(",", "") + "." + (cents or "0").ljust(2, "0"))
        if amount not in amounts:
            violations.append(f"amount {match.group(0).strip()} is not in the facts")
        spans.append(match.span())

    def check_date(match, year, month, day):
        try:
            found = [
                item
                for item in dates
                if item.month == month
                and item.day == day
                and (year is None or item.year == year)
            ]
        except TypeError:
            found = []
        if not found:
            violations.append(f"date {match.group(0)} is not in the facts")
        spans.append(match.span())

    for match in ISO_DATE.finditer(text):
        check_date(match, int(match.group(1)), int(match.group(2)), int(match.group(3)))
    for match in NAMED_DATE.finditer(text):
        check_date(
            match,
            int(match.group(3)) if match.group(3) else None,
            MONTH_NUMBER[match.group(1)[:3].lower()],
            int(match.group(2)),
        )
    for match in DAY_MONTH.finditer(text):
        check_date(
            match,
            int(match.group(3)) if match.group(3) else None,
            MONTH_NUMBER[match.group(2)[:3].lower()],
            int(match.group(1)),
        )

    def covered(position):
        return any(start <= position < end for start, end in spans)

    for match in NUMBER_TOKEN.finditer(text):
        if covered(match.start()):
            continue
        token = match.group(0).rstrip(".,")
        try:
            number = Decimal(token.replace(",", ""))
        except InvalidOperation:
            violations.append(f"number {token} is not in the facts")
            continue
        if (
            not (number == number.to_integral_value() and int(number) in integers)
            and number.quantize(Decimal("0.01")) not in amounts
        ):
            violations.append(f"number {token} is not in the facts")
    if CLAIMS.search(text):
        violations.append("claims an approval or payment")
    if len(text) > 400 or "\n" in text.strip():
        violations.append("not a single short summary")
    return violations


# AI explanation

EXPLAIN_PROMPT = """You explain a refund case to a merchant in one short plain-English sentence.
You receive only structured facts as JSON. Summarise what was promised, what PayPal confirmed as
refunded, what remains, whether prerequisites are confirmed, and the next action implied by
reconciliation_status. Rules:
- Use only amounts, dates and numbers that appear in the facts. Write amounts as $X.XX.
- Do not say anything is approved, authorized, sent or paid unless it is a refunded_amount.
- Never instruct an automatic refund; the merchant decides.
- At most 40 words, no line breaks.
Return JSON: {"summary": "..."}"""
EXPLAIN_PROMPT_VERSION = hashlib.sha256(EXPLAIN_PROMPT.encode()).hexdigest()[:16]


def explanation_key(model, facts: CaseFacts) -> str:
    material = {
        "kind": "next_action_explanation",
        "model": model,
        "prompt_version": EXPLAIN_PROMPT_VERSION,
        "facts": facts.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def _facts_payload(facts: CaseFacts):
    # Promise IDs are internal; the model gets positions instead.
    data = facts.model_dump(mode="json")
    for refund in data["refunds"]:
        refund.pop("promise_id", None)
    return data


def explain(
    action: NextAction, client, settings, *, data_policy, usage=None, merchant_id=None
) -> Explanation:
    result = Explanation(
        case_id=action.case_id,
        text=action.summary,
        source="template",
        label=None,
        fallback_reason=None,
        guard_violations=[],
        model=None,
        facts=action.facts,
        missing=action.missing,
    )
    called = False
    skipped = None

    def fallback(reason, *, skip=False):
        nonlocal skipped
        result.fallback_reason = reason
        if skip:
            skipped = reason
        return result

    def finish():
        if usage is not None:
            usage.record(
                merchant_id,
                case_id=action.case_id,
                tokens=result.tokens,
                cache_hit=result.cache_hit,
                skipped_reason=skipped,
                status="ok" if result.source == "ai" else "needs_review",
                model_called=called,
            )
        return result

    if not settings.enabled:
        fallback("extraction_disabled", skip=True)
        return finish()
    if client is None:
        fallback("not_configured", skip=True)
        return finish()
    if data_policy != GROQ_DATA_POLICY:
        logger.warning(
            "AI next-action explanation blocked for case %s by data policy",
            action.case_id,
        )
        fallback("data_policy_blocked", skip=True)
        return finish()
    key = explanation_key(settings.model, action.facts)
    # The cache holds only the model's raw output; a hit is parsed and fact-guarded again below.
    content = usage.cached(merchant_id, key) if usage is not None else None
    if isinstance(content, str):
        result.cache_hit = True
    else:
        if (
            usage is not None
            and usage.tokens_today(merchant_id) >= settings.daily_token_limit
        ):
            fallback("budget_exceeded", skip=True)
            return finish()
        try:
            called = True
            response = client.chat.completions.create(
                model=settings.model,
                temperature=0,
                max_tokens=MAX_COMPLETION_TOKENS,
                response_format={"type": "json_object"},
                timeout=settings.timeout_seconds,
                messages=[
                    {"role": "system", "content": EXPLAIN_PROMPT},
                    {
                        "role": "user",
                        "content": "Case facts as JSON data:\n"
                        + json.dumps(_facts_payload(action.facts)),
                    },
                ],
            )
            tokens = getattr(getattr(response, "usage", None), "total_tokens", 0)
            result.tokens = tokens if isinstance(tokens, int) else 0
            content = response.choices[0].message.content
        except Exception as error:  # noqa: BLE001 - always return the template instead
            reason = _failure_reason(error)
            _log_failure(action.case_id, error, reason, settings)
            fallback(reason)
            return finish()
    try:
        text = json.loads(content or "")["summary"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError
    except (TypeError, ValueError, KeyError):
        fallback("invalid_json")
        return finish()
    text = " ".join(text.split())
    violations = guard(text, action.facts)
    if violations:
        result.guard_violations = violations
        fallback("fact_guard")
        return finish()
    result.text, result.source, result.label, result.model = (
        text,
        "ai",
        AI_LABEL,
        settings.model,
    )
    if usage is not None and called:
        usage.store(merchant_id, key, content)
    return finish()
