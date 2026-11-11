"""Private, revision-bound advisory investigations using the existing worker/store pattern."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import uuid4

from .case_workspace import now_text
from .errors import StoreError
from .evidence_models import PayPalEvidenceFact
from .evidence_workspace import _hash, evidence_summary
from .inference import (
    Budget,
    GroqProvider,
    InferenceUnavailable,
    InvestigationSettings,
    OpenRouterProvider,
)
from .investigation_models import (
    Finding,
    InvestigationPage,
    InvestigationResult,
    InvestigationView,
    Recommendation,
    ReviewReceipt,
    Triage,
)
from .resolution_workspace import ResolutionWorkspace
from .paypal_history import HISTORY_MAX_AGE


def now():
    return datetime.now(timezone.utc)


def audit(db, case, kind, data):
    db.execute(
        "INSERT INTO investigation_audit VALUES (?,?,?,?,?,?)",
        (
            str(uuid4()),
            case["id"],
            case["merchant_id"],
            now_text(),
            kind,
            json.dumps(data),
        ),
    )


def snapshot(db, case):
    """Hash all relevant private state; model input is built separately below."""
    params = (case["id"], case["merchant_id"])
    events = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM resolution_events WHERE resolution_id=? AND merchant_id=? ORDER BY sequence",
            params,
        )
    ]
    links = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM resolution_evidence_links WHERE resolution_id=? AND merchant_id=? ORDER BY id",
            params,
        )
    ]
    state = db.execute(
        "SELECT data_json FROM resolution_evidence_state WHERE resolution_id=? AND merchant_id=?",
        params,
    ).fetchone()
    extra = {}
    for table in ("customer_portal_messages", "customer_evidence", "commerce_orders"):
        # Hashes/metadata only for files; never load attachment bodies.
        columns = (
            "id,sha256,created_at"
            if table == "customer_evidence"
            else "id,body,created_at"
            if table == "customer_portal_messages"
            else "snapshot_json,revision"
        )
        extra[table] = [
            dict(r)
            for r in db.execute(
                f"SELECT {columns} FROM {table} WHERE resolution_id=? AND merchant_id=?",
                params,
            )
        ]
    if case["refund_case_id"]:
        # Capture-scoped events include concurrent changes in sibling cases.
        extra["payment_events"] = [
            dict(r)
            for r in db.execute(
                """SELECT e.id,e.payload_json,e.recorded_at FROM case_events e JOIN cases c
            ON c.capture_id=e.capture_id AND c.merchant_id=e.merchant_id WHERE c.id=? AND c.merchant_id=? ORDER BY e.sequence""",
                (case["refund_case_id"], case["merchant_id"]),
            )
        ]
        for table in ("paypal_capture_verifications", "paypal_refund_verifications"):
            extra[table] = [
                dict(r)
                for r in db.execute(
                    f"SELECT v.* FROM {table} v JOIN cases c ON c.capture_id=v.capture_id AND c.merchant_id=v.merchant_id WHERE c.id=? AND c.merchant_id=? ORDER BY v.checked_at,v.id",
                    (case["refund_case_id"], case["merchant_id"]),
                )
            ]
        for table in (
            "paypal_refund_history",
            "refund_approvals",
            "refund_executions",
            "review_exceptions",
        ):
            extra[table] = [
                dict(r)
                for r in db.execute(
                    f"SELECT v.* FROM {table} v JOIN cases c ON c.capture_id=v.capture_id AND c.merchant_id=v.merchant_id WHERE c.id=? AND c.merchant_id=?",
                    (case["refund_case_id"], case["merchant_id"]),
                )
            ]
    value = {
        "case": dict(case),
        "events": events,
        "links": links,
        "state": state["data_json"] if state else None,
        "extra": extra,
    }
    return _hash(value), events, links


def analyze(db, case, revision, cfg, store):
    digest, events, links = snapshot(db, case)
    summary = evidence_summary(db, case)
    findings, contradictions, missing = [], [], []
    instant = now()
    provider_events = [e for e in events if e["source"] == "provider_confirmed"]
    facts = list(summary.verified)
    legacy_ids = {}
    legacy = ResolutionWorkspace(store)._legacy(db, case)
    basis = store._reconcile(db, legacy) if legacy else None
    if basis:
        # Merge independently verified capture-scoped records; never promote the manual ledger.
        cap = basis.capture_verification
        if cap:
            fact = PayPalEvidenceFact(
                kind="paypal_capture",
                reference=cap.capture_id,
                capture_id=cap.capture_id,
                status=cap.capture_status,
                amount=cap.captured_amount,
                currency=cap.currency,
                checked_at=cap.checked_at,
            )
            facts = [
                f
                for f in facts
                if not (
                    f.kind == fact.kind
                    and f.reference == fact.reference
                    and f.checked_at < fact.checked_at
                )
            ]
            if not any(
                f.kind == fact.kind and f.reference == fact.reference for f in facts
            ):
                facts.append(fact)
                legacy_ids[(fact.kind, fact.reference)] = str(cap.id)
        for refund in basis.refund_verifications:
            fact = PayPalEvidenceFact(
                kind="paypal_refund",
                reference=refund.refund_id,
                capture_id=refund.capture_id,
                status=refund.provider_status,
                amount=refund.amount,
                currency=refund.currency,
                checked_at=refund.checked_at,
            )
            facts = [
                f
                for f in facts
                if not (
                    f.kind == fact.kind
                    and f.reference == fact.reference
                    and f.checked_at < fact.checked_at
                )
            ]
            if not any(
                f.kind == fact.kind and f.reference == fact.reference for f in facts
            ):
                facts.append(fact)
                legacy_ids[(fact.kind, fact.reference)] = str(refund.id)
        if not summary.verified:
            summary.order_history_verified = basis.paypal_history_current
            if basis.paypal_history_current and summary.last_checked_at is None:
                # Existing verified payment history is usable without an SDK refresh.
                summary.issues = [
                    i for i in summary.issues if i.kind != "provider_refresh"
                ]
    seen = set()
    for fact in facts:
        stable = fact.model_dump(mode="json", exclude={"checked_at"})
        event = next(
            (
                e
                for e in reversed(provider_events)
                if {
                    k: v
                    for k, v in json.loads(e["data_json"]).items()
                    if k != "checked_at"
                }
                == stable
            ),
            None,
        )
        legacy_id = legacy_ids.get((fact.kind, fact.reference))
        if not event and not legacy_id:
            contradictions.append("provider_fact_without_source_event")
            continue
        key = (fact.kind, fact.reference)
        if key in seen:
            contradictions.append("duplicate_provider_identity")
            continue
        seen.add(key)
        findings.append(
            Finding(
                evidence_id=event["id"] if event else legacy_id,
                source="provider_fact",
                kind=fact.kind,
                status=fact.status,
                amount=str(fact.amount) if fact.amount is not None else None,
                currency=fact.currency,
                verified_at=fact.checked_at,
            )
        )
        if fact.checked_at > instant + timedelta(seconds=5):
            contradictions.append("future_provider_timestamp")
        allowed = {
            "paypal_capture": {
                "COMPLETED",
                "DECLINED",
                "PARTIALLY_REFUNDED",
                "PENDING",
                "REFUNDED",
                "FAILED",
            },
            "paypal_refund": {"COMPLETED", "PENDING", "FAILED", "CANCELLED"},
            "paypal_order": {
                "CREATED",
                "SAVED",
                "APPROVED",
                "VOIDED",
                "COMPLETED",
                "PAYER_ACTION_REQUIRED",
            },
        }
        if fact.status not in allowed[fact.kind]:
            contradictions.append("unsupported_provider_status")
        if fact.kind != "paypal_order" and (
            fact.amount is None
            or fact.currency != "USD"
            or fact.amount != fact.amount.quantize(Decimal(".01"))
        ):
            contradictions.append("invalid_provider_money")
    approval = summary.last_merchant_approval
    if approval:
        findings.append(
            Finding(
                evidence_id=approval.id,
                source="merchant_claim",
                kind="refund_approved",
                status="merchant_reported",
                amount=str(approval.amount),
                currency=approval.currency,
            )
        )
        if approval.occurred_at > instant + timedelta(seconds=5):
            contradictions.append("future_merchant_claim")
    capture = next((f for f in facts if f.kind == "paypal_capture"), None)
    refunds = [f for f in facts if f.kind == "paypal_refund"]
    if len([f for f in facts if f.kind == "paypal_capture"]) > 1:
        contradictions.append("multiple_capture_identities")
    if (
        any(f.capture_id != capture.reference for f in refunds)
        if capture
        else bool(refunds)
    ):
        contradictions.append("refund_capture_mismatch")
    completed = sum(
        (f.amount or Decimal(0) for f in refunds if f.status == "COMPLETED"), Decimal(0)
    )
    pending = sum(
        (f.amount or Decimal(0) for f in refunds if f.status == "PENDING"), Decimal(0)
    )
    if capture and capture.amount and completed + pending > capture.amount:
        contradictions.append("refunds_exceed_capture")
    if (
        capture
        and capture.amount is not None
        and approval
        and approval.amount > capture.amount
    ):
        contradictions.append("merchant_claim_exceeds_capture")
    if capture and capture.status == "REFUNDED" and completed != capture.amount:
        missing.append("refund_history_does_not_explain_capture")
    if (
        capture
        and completed
        and capture.status not in ("PARTIALLY_REFUNDED", "REFUNDED")
    ):
        contradictions.append("capture_refund_status_conflict")
    if not capture:
        missing.append("verified_capture")
    if not summary.order_history_verified:
        missing.append("complete_provider_refund_history")
    if summary.issues:
        missing.extend(
            sorted(
                {
                    "provider_" + i.status
                    for i in summary.issues
                    if i.kind != "refund_confirmation"
                }
            )
        )
    if basis:
        if basis.status in ("provider_review", "promise_review", "execution_failed"):
            contradictions.append("linked_payment_requires_review")
        if basis.status in (
            "awaiting_acceptance",
            "awaiting_condition",
            "awaiting_prerequisite",
        ):
            missing.append("linked_payment_" + basis.status)
        if basis.active_refund_execution_id:
            missing.append("linked_payment_execution_unconfirmed")
        if (
            basis.completed_refund_amount > completed
            or basis.pending_refund_amount > pending
        ):
            missing.append("manual_refund_ledger_not_provider_confirmed")
    if len(events) > 256:
        missing.append("evidence_budget_exceeded")
    verified_times = [f.checked_at for f in facts]
    fresh_until = (
        min(verified_times) + timedelta(seconds=cfg.freshness_seconds)
        if verified_times
        else None
    )
    if basis and basis.paypal_refund_history and fresh_until:
        fresh_until = min(
            fresh_until, basis.paypal_refund_history.checked_at + HISTORY_MAX_AGE
        )
    stale = bool(fresh_until and fresh_until <= instant)
    status = (
        "contradictory"
        if contradictions
        else "stale"
        if stale
        else "missing"
        if not capture or missing
        else "pending_refund"
        if pending
        else "confirmed_full_refund"
        if capture.amount and completed == capture.amount
        else "partial_refund"
        if completed
        else "approval_unconfirmed"
        if approval
        else "missing"
    )
    step = (
        "abstain"
        if status in ("contradictory", "stale", "missing")
        else "wait_provider"
        if status == "pending_refund"
        else "no_action"
        if status == "confirmed_full_refund"
        else "review"
    )
    return (
        InvestigationResult(
            issue_type="refund"
            if capture
            or approval
            or any(l["kind"].startswith("paypal_") for l in links)
            else "unknown",
            status=status,
            findings=findings,
            contradictions=sorted(set(contradictions)),
            missing_evidence=sorted(set(missing)),
            next_step=step,
            reason={
                "abstain": "Evidence is incomplete, stale or contradictory; a merchant must review it.",
                "wait_provider": "A pending refund is not a completed refund. Wait for provider confirmation.",
                "no_action": "Fresh provider evidence confirms the full captured amount was refunded.",
                "review": "Review the recorded refund evidence; merchant claims do not confirm a provider refund.",
            }[step],
            last_verified_at=max(verified_times) if verified_times else None,
            evidence_fresh_until=fresh_until,
            evidence_snapshot=digest,
            case_revision=revision,
        ),
        links,
        summary,
    )


class Investigations:
    def __init__(self, store, settings=None):
        self.store = store
        self.workspace = ResolutionWorkspace(store)
        self.settings = settings or InvestigationSettings()

    def list(self, case_id, merchant_id):
        with self.store.transaction() as db:
            case = self.workspace._case(db, case_id, merchant_id)
            job = db.execute(
                "SELECT * FROM investigation_jobs WHERE resolution_id=? AND merchant_id=?",
                (str(case_id), str(merchant_id)),
            ).fetchone()
            digest, _, _ = snapshot(db, case)
            rows = db.execute(
                "SELECT * FROM investigations WHERE resolution_id=? AND merchant_id=? ORDER BY revision DESC LIMIT 20",
                (str(case_id), str(merchant_id)),
            ).fetchall()
            items = []
            for row in rows:
                result = InvestigationResult.model_validate_json(row["result_json"])
                review = db.execute(
                    "SELECT receipt_json FROM investigation_reviews WHERE investigation_id=? AND merchant_id=?",
                    (row["id"], str(merchant_id)),
                ).fetchone()
                stale = (
                    row["revision"] != job["revision"]
                    or result.evidence_snapshot != digest
                    or bool(
                        result.evidence_fresh_until
                        and result.evidence_fresh_until <= now()
                    )
                )
                items.append(
                    InvestigationView(
                        id=row["id"],
                        case_id=case_id,
                        case_revision=row["revision"],
                        state=row["state"],
                        stale=stale,
                        created_at=row["created_at"],
                        completed_at=row["completed_at"],
                        result=result,
                        review=ReviewReceipt.model_validate_json(review["receipt_json"])
                        if review
                        else None,
                    )
                )
            if job and (not rows or rows[0]["revision"] != job["revision"]):
                items.insert(
                    0,
                    InvestigationView(
                        id=case_id,
                        case_id=case_id,
                        case_revision=job["revision"],
                        state=job["state"],
                        stale=False,
                        created_at=job["created_at"],
                    ),
                )
            return InvestigationPage(items=items)

    def review(
        self, case_id, investigation_id, merchant_id, payload, reviewer_identity
    ):
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant_id)
            row = db.execute(
                "SELECT * FROM investigations WHERE id=? AND resolution_id=? AND merchant_id=?",
                (str(investigation_id), str(case_id), str(merchant_id)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Investigation not found")
            result = InvestigationResult.model_validate_json(row["result_json"])
            job = db.execute(
                "SELECT revision FROM investigation_jobs WHERE resolution_id=?",
                (str(case_id),),
            ).fetchone()
            digest, _, _ = snapshot(db, case)
            if (
                payload.expected_revision != row["revision"]
                or row["revision"] != job["revision"]
                or payload.evidence_snapshot != result.evidence_snapshot
                or digest != result.evidence_snapshot
                or (
                    payload.decision == "approve"
                    and result.evidence_fresh_until
                    and result.evidence_fresh_until <= now()
                )
            ):
                raise StoreError(
                    409, "Investigation evidence is stale; review the current revision"
                )
            previous = db.execute(
                "SELECT receipt_json FROM investigation_reviews WHERE investigation_id=?",
                (str(investigation_id),),
            ).fetchone()
            if previous:
                receipt = ReviewReceipt.model_validate_json(previous["receipt_json"])
                if (
                    receipt.decision != payload.decision
                    or receipt.reviewer_identity != reviewer_identity
                ):
                    raise StoreError(
                        409, "Investigation already has a different review decision"
                    )
                return receipt
            receipt = ReviewReceipt(
                **payload.model_dump(),
                reviewer_merchant_id=merchant_id,
                reviewer_identity=reviewer_identity,
                reviewed_at=now(),
            )
            db.execute(
                "INSERT INTO investigation_reviews VALUES (?,?,?)",
                (str(investigation_id), str(merchant_id), receipt.model_dump_json()),
            )
            audit(
                db,
                case,
                "investigation_reviewed",
                {
                    "investigation_id": str(investigation_id),
                    **receipt.model_dump(mode="json"),
                },
            )
            return receipt

    def run_one(self, groq=None, openrouter=None, refresh=None):
        token = str(uuid4())
        with self.store.transaction(write=True) as db:
            job = db.execute(
                "SELECT * FROM investigation_jobs WHERE state='queued' OR (state='running' AND lease_until<?) ORDER BY created_at,resolution_id LIMIT 1",
                (now_text(),),
            ).fetchone()
            if not job:
                return False
            db.execute(
                "UPDATE investigation_jobs SET state='running',attempts=attempts+1,lease_token=?,lease_until=? WHERE resolution_id=?",
                (
                    token,
                    (now() + timedelta(minutes=3)).isoformat(),
                    job["resolution_id"],
                ),
            )
            case = self.workspace._case(db, job["resolution_id"], job["merchant_id"])
            try:
                result, links, summary = analyze(
                    db, case, job["revision"], self.settings, self.store
                )
            except (ValueError, TypeError, KeyError, ArithmeticError):
                # Persisted evidence from a bad/older source must not strand a lease.
                result = InvestigationResult(
                    issue_type="unknown",
                    status="contradictory",
                    findings=[],
                    contradictions=["invalid_source_evidence"],
                    missing_evidence=["validated_source_snapshot"],
                    next_step="abstain",
                    reason="Source evidence could not be validated; merchant review is required.",
                    validation_failures=["source_validation_failed"],
                    evidence_snapshot=snapshot(db, case)[0],
                    case_revision=job["revision"],
                )
                links, summary = [], None
            audit(
                db,
                case,
                "investigation_started",
                {
                    "revision": job["revision"],
                    "snapshot": result.evidence_snapshot,
                    "lease_attempt": job["attempts"] + 1,
                },
            )
        state = "finished"
        cached_reads = []
        try:
            if result.validation_failures:
                raise InferenceUnavailable("source_validation_failed")
            if job["attempts"] >= 2:
                raise InferenceUnavailable("worker_attempt_budget_exceeded")
            if not self.settings.enabled:
                raise InferenceUnavailable("inference_disabled")
            budget = Budget()

            def complete(adapter, schema, data):
                before = budget.remaining
                try:
                    value, metadata = adapter.complete(schema, data, budget)
                    metadata["assessment"] = value.model_dump(mode="json")
                    result.model_calls.append(metadata)
                    return value
                except InferenceUnavailable:
                    provider = getattr(adapter, "provider", "simulation")
                    result.model_calls.append(
                        {
                            "provider": provider,
                            "model": getattr(
                                self.settings, provider + "_model", "unknown"
                            ),
                            "route": ",".join(self.settings.openrouter_routes)
                            if provider == "openrouter"
                            else provider,
                            "attempts": before - budget.remaining,
                            "failed": True,
                        }
                    )
                    raise

            # No notes, messages, names, payment identifiers, contacts or provider bodies.
            evidence = {
                "candidate": result.model_dump(
                    mode="json", exclude={"model_calls", "evidence_snapshot", "reason"}
                ),
                "linked_reads": [
                    {"evidence_id": l["id"], "kind": l["kind"]}
                    for l in links
                    if l["kind"] in ("paypal_capture", "paypal_refund")
                ],
            }
            triage = complete(groq or GroqProvider(self.settings), Triage, evidence)
            if result.issue_type != triage.issue_type:
                raise InferenceUnavailable("unsupported_issue_classification")
            if triage.reads:
                selected = triage.reads[0]
                linked = next(
                    (l for l in links if l["id"] == str(selected.evidence_id)), None
                )
                expected = (
                    "paypal_capture"
                    if selected.operation == "refresh_linked_capture"
                    else "paypal_refund"
                )
                if not linked or linked["kind"] != expected:
                    raise InferenceUnavailable("unauthorized_evidence_read")
                recent = (
                    summary.last_checked_at
                    and summary.last_checked_at > now() - timedelta(minutes=5)
                )
                # The model already received these validated facts. A read of
                # the same linked resource can use that current snapshot rather
                # than falsely blocking or calling the provider again. A recent
                # failed check alone is insufficient: the matching fact itself
                # must be verified within both the cache and configured windows.
                cutoff = now() - timedelta(seconds=min(300, self.settings.freshness_seconds))
                cached = next((fact for fact in summary.verified
                               if fact.kind == expected
                               and fact.reference == linked["reference"]
                               and cutoff < fact.checked_at <= now()), None)
                if cached:
                    cached_reads.append({**selected.model_dump(mode="json"),
                                         "verified_at": cached.checked_at.isoformat()})
                else:
                    if not self.settings.allow_sandbox_refresh or refresh is None or recent:
                        raise InferenceUnavailable("evidence_refresh_unavailable_or_recent")
                    # The callback validates ownership again and has no write operation.
                    refresh(case["id"], case["merchant_id"], selected)
                    raise InferenceUnavailable("evidence_refresh_completed_reinvestigate")
            if triage.escalate or result.status in (
                "contradictory",
                "stale",
                "missing",
                "approval_unconfirmed",
                "partial_refund",
            ):
                recommendation = complete(
                    openrouter or OpenRouterProvider(self.settings),
                    Recommendation,
                    evidence,
                )
                valid = {str(f.evidence_id) for f in result.findings}
                cited = [str(i) for i in recommendation.evidence_ids]
                if (
                    len(cited) != len(set(cited))
                    or not set(cited) <= valid
                    or (valid and not cited)
                ):
                    raise InferenceUnavailable("invalid_evidence_citation")
                if (
                    recommendation.status != result.status
                    or recommendation.next_step not in (result.next_step, "abstain")
                ):
                    raise InferenceUnavailable("recommendation_contradicts_evidence")
                result.next_step = recommendation.next_step
                if result.next_step == "abstain":
                    result.reason = "The investigator abstained; a merchant must review the available evidence."
        except InferenceUnavailable as error:
            state, result.next_step = "blocked", "abstain"
            if str(error) not in result.validation_failures:
                result.validation_failures.append(str(error))
            result.reason = (
                "Investigation requires human review: "
                + str(error).replace("_", " ")
                + "."
            )
        except Exception:
            state, result.next_step, result.reason = (
                "blocked",
                "abstain",
                "Investigation requires human review: internal validation failed.",
            )
            result.validation_failures.append("internal_validation_failed")
        with self.store.transaction(write=True) as db:
            current = db.execute(
                "SELECT * FROM investigation_jobs WHERE resolution_id=?", (case["id"],)
            ).fetchone()
            # A late worker cannot publish over a newer revision or replacement lease.
            if (
                current["lease_token"] != token
                or current["revision"] != job["revision"]
            ):
                audit(
                    db, case, "investigation_superseded", {"revision": job["revision"]}
                )
                return True
            if (
                snapshot(db, self.workspace._case(db, case["id"], case["merchant_id"]))[
                    0
                ]
                != result.evidence_snapshot
            ):
                db.execute(
                    "UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL WHERE resolution_id=?",
                    (case["id"],),
                )
                audit(
                    db, case, "investigation_superseded", {"revision": job["revision"]}
                )
                return True
            for read in cached_reads:
                audit(db, case, "investigation_read_cache_hit",
                      {"revision": job["revision"], "source": "verified_snapshot", **read})
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    case["id"],
                    case["merchant_id"],
                    job["revision"],
                    state,
                    job["created_at"],
                    now_text(),
                    result.model_dump_json(),
                ),
            )
            db.execute(
                "UPDATE investigation_jobs SET state=?,lease_token=NULL,lease_until=NULL WHERE resolution_id=? AND lease_token=?",
                (state, case["id"], token),
            )
            audit(
                db,
                case,
                "investigation_" + state,
                {
                    "investigation_id": identifier,
                    "revision": job["revision"],
                    "snapshot": result.evidence_snapshot,
                    "evidence_ids": [str(f.evidence_id) for f in result.findings],
                    "models": result.model_calls,
                    "validation_failures": result.validation_failures,
                },
            )
        return True
