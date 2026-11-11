"""Version-bound buyer decisions, guided returns, portfolio alerts and evidence packages."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, SecretStr, model_validator

from .approvals import invalidate_approvals
from .case_workspace import provider_hold
from .commerce_workspace import CommerceWorkspace
from .customer_portal import CustomerPortal
from .errors import StoreError
from .platform_identity import Input, audit, digest, now
from .resolution_workspace import ResolutionWorkspace


class OfferChoice(Input):
    promise_id: UUID
    expected_revision: int = Field(ge=1)


class OfferCreate(Input):
    choices: list[OfferChoice] = Field(min_length=1, max_length=4)
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def distinct_choices(self):
        if len({c.promise_id for c in self.choices}) != len(self.choices):
            raise ValueError("Offer choices must refer to distinct promises")
        return self


class OfferDecision(Input):
    token: SecretStr
    offer_id: UUID
    expected_revision: int = Field(ge=1)
    choice_id: UUID | None = None
    decision: str = Field(pattern=r"^(accept|decline)$")


class ReturnItem(Input):
    product_id: str = Field(min_length=1, max_length=160)
    quantity: int = Field(strict=True, ge=1, le=10000)


class ReturnCreate(Input):
    request_id: UUID
    order_id: UUID
    items: list[ReturnItem] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=2000)
    delivered_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def distinct_items(self):
        if len({i.product_id for i in self.items}) != len(self.items):
            raise ValueError("List each product once")
        return self


class BuyerReturn(ReturnCreate):
    token: SecretStr


class Shipment(Input):
    carrier: str = Field(min_length=1, max_length=60)
    tracking_code: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=160)


class ReturnUpdate(Input):
    expected_revision: int = Field(ge=1)
    action: str = Field(
        pattern=r"^(approve|reject|ship_return|receive|pass_inspection|ship_replacement|complete)$"
    )
    note: str = Field(min_length=1, max_length=2000)
    shipment: Shipment | None = None
    promise_id: UUID | None = None
    promise_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def complete_promise_reference(self):
        if bool(self.promise_id) != bool(self.promise_revision):
            raise ValueError("Select an exact promise revision")
        return self


class PackageCreate(Input):
    dispute_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    reason: str = Field(
        pattern=r"^(item_not_received|not_as_described|unauthorized|credit_not_processed|duplicate_charge|canceled_recurring|other)$"
    )


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


class Operations:
    def __init__(self, store):
        self.store = store
        self.workspace = ResolutionWorkspace(store)

    def _invalidate(self, db, case, reason):
        legacy = self.workspace._legacy(db, case)
        if legacy:
            active = db.execute(
                "SELECT 1 FROM refund_executions WHERE merchant_id=? AND capture_id=? AND status IN ('reserved','submitting','unknown','pending') LIMIT 1",
                (str(legacy.merchant_id), legacy.payment.capture_id),
            ).fetchone()
            if active or provider_hold(
                db, legacy.merchant_id, legacy.payment.capture_id
            ):
                raise StoreError(
                    409,
                    "Resolve the existing payment execution before changing its agreement",
                )
            invalidate_approvals(
                db, legacy.merchant_id, legacy.payment.capture_id, reason
            )

    @staticmethod
    def _offer(row):
        value = dict(row)
        value["choices"] = json.loads(value.pop("choices_json"))
        value.pop("merchant_id", None)
        return value

    def offers(self, merchant, case_id):
        with self.store.transaction() as db:
            self.workspace._case(db, case_id, merchant)
            rows = db.execute(
                "SELECT * FROM platform_offers WHERE merchant_id=? AND case_id=? ORDER BY revision DESC",
                (str(merchant), str(case_id)),
            ).fetchall()
            return {"items": [self._offer(r) for r in rows]}

    def publish(self, merchant, actor, case_id, payload):
        moment = datetime.now(timezone.utc)
        if not moment < payload.expires_at <= moment + timedelta(days=30):
            raise StoreError(422, "Offer expiry must be in the next thirty days")
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant)
            self._invalidate(
                db, case, "A new buyer offer requires a current acceptance"
            )
            choices = []
            for option in payload.choices:
                row = self.workspace._promise(db, case, option.promise_id)
                if row["revision"] != option.expected_revision:
                    raise StoreError(409, "A promise changed; reload before publishing")
                terms = json.loads(row["promise_json"])
                choices.append(
                    {
                        "id": str(uuid4()),
                        "promise_id": row["id"],
                        "promise_revision": row["revision"],
                        "promise": terms["promise"],
                        "target": terms["target"],
                        "requires": terms["requires"],
                        "due_at": terms["due_at"],
                    }
                )
            self._check_refund_balance(db, merchant, case, choices)
            revision = (
                db.execute(
                    "SELECT COALESCE(max(revision),0) FROM platform_offers WHERE case_id=?",
                    (case["id"],),
                ).fetchone()[0]
                + 1
            )
            db.execute(
                "UPDATE platform_offers SET status='superseded' WHERE case_id=? AND status IN ('published','accepted','declined')",
                (case["id"],),
            )
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO platform_offers VALUES (?,?,?,?,?,?,'published',NULL,NULL,NULL,?)",
                (
                    identifier,
                    str(merchant),
                    case["id"],
                    revision,
                    _json(choices),
                    payload.expires_at.astimezone(timezone.utc).isoformat(
                        timespec="microseconds"
                    ),
                    now(),
                ),
            )
            audit(db, merchant, actor, "offer_published", identifier, revision=revision)
            self.workspace._event(
                db,
                case,
                "merchant_evidence",
                "merchant_recorded",
                {
                    "evidence_type": "buyer_offer",
                    "offer_id": identifier,
                    "revision": revision,
                },
            )
        return self.offers(merchant, case_id)["items"][0]

    def _check_refund_balance(self, db, merchant, case, choices):
        """Each refund choice is an alternative, so each must fit the current refundable balance
        (captured minus completed and pending refunds) of the linked payment, and no hold may apply."""
        refunds = [c for c in choices if c["target"]["kind"] == "refund"]
        legacy = self.workspace._legacy(db, case) if refunds else None
        if legacy is None:
            return
        if provider_hold(db, merchant, legacy.payment.capture_id):
            raise StoreError(409, "A dispute or provider hold blocks refund offers for this payment")
        basis = self.store._reconcile(db, legacy)
        refundable = (
            basis.captured_amount
            - basis.completed_refund_amount
            - basis.pending_refund_amount
        )
        for choice in refunds:
            if Decimal(str(choice["target"]["amount"])) > refundable:
                raise StoreError(
                    409,
                    "A refund choice exceeds the current refundable balance; reload before publishing",
                )

    @staticmethod
    def _safe_choice(choice):
        target = choice["target"]
        # Private provider references, source notes and prerequisite IDs never leave the merchant API.
        return {
            "id": choice["id"],
            "promise": choice["promise"],
            "kind": target["kind"],
            "amount": target.get("amount"),
            "currency": target.get("currency"),
            "due_at": choice.get("due_at"),
            "conditions_required": bool(choice["requires"]),
        }

    def buyer_offers(self, token):
        with self.store.transaction() as db:
            link = CustomerPortal._authorized_link(db, token)
            rows = db.execute(
                "SELECT * FROM platform_offers WHERE case_id=? AND status!='superseded' ORDER BY revision DESC LIMIT 1",
                (link["resolution_id"],),
            ).fetchall()
            items = []
            for row in rows:
                choices = json.loads(row["choices_json"])
                stale = row["status"] == "published" and row["expires_at"] <= now()
                for choice in choices:
                    current = db.execute(
                        "SELECT revision FROM resolution_promises WHERE id=? AND resolution_id=?",
                        (choice["promise_id"], row["case_id"]),
                    ).fetchone()
                    stale = (
                        stale
                        or not current
                        or current["revision"] != choice["promise_revision"]
                    )
                items.append(
                    {
                        "id": row["id"],
                        "revision": row["revision"],
                        "status": row["status"],
                        "stale": bool(stale),
                        "expires_at": row["expires_at"],
                        "selected_choice": row["selected_choice"],
                        "decision_at": row["decision_at"],
                        "choices": [self._safe_choice(c) for c in choices],
                    }
                )
            return {"items": items}

    def decide(self, payload):
        with self.store.transaction(write=True) as db:
            link = CustomerPortal._authorized_link(db, payload.token)
            row = db.execute(
                "SELECT * FROM platform_offers WHERE id=? AND case_id=? AND merchant_id=?",
                (str(payload.offer_id), link["resolution_id"], link["merchant_id"]),
            ).fetchone()
            if not row:
                raise StoreError(404, "Offer not found")
            if (
                row["revision"] != payload.expected_revision
                or row["status"] == "superseded"
                or row["expires_at"] <= now()
            ):
                raise StoreError(
                    409, "This offer changed or expired; request a current offer"
                )
            choices = json.loads(row["choices_json"])
            for choice in choices:
                current = db.execute(
                    "SELECT revision FROM resolution_promises WHERE id=? AND resolution_id=?",
                    (choice["promise_id"], row["case_id"]),
                ).fetchone()
                if not current or current["revision"] != choice["promise_revision"]:
                    raise StoreError(
                        409, "The proposed terms changed; request a new offer"
                    )
            selected = str(payload.choice_id) if payload.choice_id else None
            if payload.decision == "accept" and selected not in {
                c["id"] for c in choices
            }:
                raise StoreError(422, "Select one of this offer's choices")
            if payload.decision == "decline" and selected:
                raise StoreError(422, "A declined offer cannot select a choice")
            status = "accepted" if payload.decision == "accept" else "declined"
            if row["status"] != "published":
                if row["status"] == status and row["selected_choice"] == selected:
                    return {
                        "status": status,
                        "decision_at": row["decision_at"],
                        "authorizes_payment": False,
                    }
                raise StoreError(409, "A decision has already been recorded")
            case = self.workspace._case(db, row["case_id"], row["merchant_id"])
            self._invalidate(db, case, "The buyer recorded a resolution offer decision")
            stamp, actor = (
                now(),
                "buyer-link:" + digest(payload.token.get_secret_value())[:20],
            )
            db.execute(
                "UPDATE platform_offers SET status=?,selected_choice=?,decision_at=?,decision_actor=? WHERE id=?",
                (status, selected, stamp, actor, row["id"]),
            )
            audit(
                db,
                row["merchant_id"],
                actor,
                "offer_" + status,
                row["id"],
                revision=row["revision"],
                choice_id=selected,
            )
            self.workspace._event(
                db,
                case,
                "merchant_evidence",
                "system",
                {
                    "evidence_type": "buyer_offer_decision",
                    "offer_id": row["id"],
                    "decision": status,
                },
            )
            return {"status": status, "decision_at": stamp, "authorizes_payment": False}

    @staticmethod
    def _return(row):
        result = dict(row)
        for key in ("items", "tracking", "replacement"):
            raw = result.pop(key + "_json")
            result[key] = json.loads(raw) if raw else None
        result.pop("merchant_id", None)
        return result

    def return_catalog(self, merchant, case_id):
        with self.store.transaction() as db:
            case = self.workspace._case(db, case_id, merchant)
            rows = db.execute(
                "SELECT * FROM commerce_orders WHERE merchant_id=? AND resolution_id=?",
                (str(merchant), case["id"]),
            ).fetchall()
            orders = []
            for row in rows:
                snapshot = json.loads(row["snapshot_json"])
                items = []
                for item in snapshot["items"]:
                    reserved = 0
                    for old in db.execute(
                        "SELECT items_json FROM platform_returns WHERE order_id=? AND status!='rejected'",
                        (row["id"],),
                    ):
                        reserved += sum(
                            i["quantity"]
                            for i in json.loads(old["items_json"])
                            if i["product_id"] == item["product_id"]
                        )
                    items.append(
                        {
                            **item,
                            "available_quantity": max(0, item["quantity"] - reserved),
                        }
                    )
                orders.append(
                    {
                        "id": row["id"],
                        "order_reference": row["order_reference"],
                        "items": items,
                    }
                )
            return {
                "orders": orders,
                "items": [
                    self._return(r)
                    for r in db.execute(
                        "SELECT * FROM platform_returns WHERE merchant_id=? AND case_id=? ORDER BY created_at DESC",
                        (str(merchant), str(case_id)),
                    )
                ],
            }

    def request_return(self, merchant, actor, case_id, payload):
        with self.store.transaction(write=True) as db:
            if getattr(payload, "token", None):
                link = CustomerPortal._authorized_link(db, payload.token)
                if link["resolution_id"] != str(case_id) or link["merchant_id"] != str(
                    merchant
                ):
                    raise StoreError(404, "Return case not found")
            case = self.workspace._case(db, case_id, merchant)
            order = CommerceWorkspace._order(db, payload.order_id, merchant)
            if order["resolution_id"] != case["id"]:
                raise StoreError(409, "Select an order connected to this case")
            prior = db.execute(
                "SELECT * FROM platform_returns WHERE merchant_id=? AND request_id=?",
                (str(merchant), str(payload.request_id)),
            ).fetchone()
            items = [i.model_dump() for i in payload.items]
            if prior:
                if (
                    prior["case_id"] != case["id"]
                    or prior["order_id"] != str(payload.order_id)
                    or json.loads(prior["items_json"]) != items
                    or prior["reason"] != payload.reason
                ):
                    raise StoreError(
                        409, "This request ID has different return details"
                    )
                assessment = db.execute(
                    "SELECT data_json FROM assurance_return_reviews WHERE return_id=? AND kind='eligibility' ORDER BY created_at DESC LIMIT 1",
                    (prior["id"],),
                ).fetchone()
                original_delivery = (
                    json.loads(assessment[0]).get("delivered_at")
                    if assessment
                    else None
                )
                if original_delivery != (
                    payload.delivered_at.isoformat() if payload.delivered_at else None
                ):
                    raise StoreError(
                        409, "This request ID has a different delivery date"
                    )
                return self._return(prior)
            quantities = Counter()
            for item in json.loads(order["snapshot_json"])["items"]:
                quantities[item["product_id"]] += item["quantity"]
            for row in db.execute(
                "SELECT items_json FROM platform_returns WHERE order_id=? AND status!='rejected'",
                (order["id"],),
            ):
                for item in json.loads(row["items_json"]):
                    quantities[item["product_id"]] -= item["quantity"]
            if any(i.quantity > quantities[i.product_id] for i in payload.items):
                raise StoreError(
                    409, "A return quantity exceeds the unreserved order quantity"
                )
            from .return_assurance import Returns

            eligibility = Returns.eligible_in(
                db, merchant, order, payload.items, payload.delivered_at
            )
            identifier, stamp = str(uuid4()), now()
            db.execute(
                "INSERT INTO platform_returns VALUES (?,?,?,?,?,1,'requested',?,?,NULL,NULL,?,?)",
                (
                    identifier,
                    str(merchant),
                    case["id"],
                    order["id"],
                    str(payload.request_id),
                    _json(items),
                    payload.reason,
                    stamp,
                    stamp,
                ),
            )
            Returns.record_eligibility(db, merchant, identifier, eligibility)
            audit(
                db, merchant, actor, "return_requested", identifier, case_id=case["id"]
            )
            return self._return(
                db.execute(
                    "SELECT * FROM platform_returns WHERE id=?", (identifier,)
                ).fetchone()
            )

    def update_return(self, merchant, actor, case_id, identifier, payload):
        transitions = {
            "approve": ("requested", "approved"),
            "reject": ("requested", "rejected"),
            "ship_return": ("approved", "in_transit"),
            "receive": ("in_transit", "received"),
            "pass_inspection": ("received", "inspection_passed"),
            "ship_replacement": ("inspection_passed", "replacement_shipped"),
            "complete": (("inspection_passed", "replacement_shipped"), "completed"),
        }
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant)
            row = db.execute(
                "SELECT * FROM platform_returns WHERE id=? AND case_id=? AND merchant_id=?",
                (str(identifier), case["id"], str(merchant)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Return not found")
            before, after = transitions[payload.action]
            if row["revision"] != payload.expected_revision or (
                row["status"] not in before
                if isinstance(before, tuple)
                else row["status"] != before
            ):
                raise StoreError(
                    409, "Return state changed or this step is out of order"
                )
            if (
                payload.action in ("ship_return", "ship_replacement")
                and not payload.shipment
            ):
                raise StoreError(
                    422, "Shipment reference, carrier and tracking code are required"
                )
            from .return_assurance import Returns

            Returns.gate(db, merchant, row, payload.action)
            tracking, replacement = row["tracking_json"], row["replacement_json"]
            if payload.action == "ship_return":
                tracking = payload.shipment.model_dump_json()
            if payload.action == "ship_replacement":
                replacement = payload.shipment.model_dump_json()
            db.execute(
                "UPDATE platform_returns SET revision=revision+1,status=?,tracking_json=?,replacement_json=?,updated_at=? WHERE id=?",
                (after, tracking, replacement, now(), row["id"]),
            )
            audit(
                db,
                merchant,
                actor,
                "return_" + after,
                row["id"],
                note=payload.note,
                revision=row["revision"] + 1,
            )
            self.workspace._event(
                db,
                case,
                "merchant_evidence",
                "merchant_recorded",
                {
                    "evidence_type": "guided_return",
                    "return_id": row["id"],
                    "status": after,
                    "note": payload.note,
                },
            )
            if payload.promise_id:
                promise = self.workspace._promise(db, case, payload.promise_id)
                terms = json.loads(promise["promise_json"])
                milestone = {
                    "receive": "warehouse_received",
                    "pass_inspection": "inspection_passed",
                }.get(payload.action)
                if (
                    promise["revision"] != payload.promise_revision
                    or terms["target"].get("kind") != "return"
                    or not milestone
                    or terms["target"].get("milestone") != milestone
                ):
                    raise StoreError(
                        409, "Select the current matching internal return milestone"
                    )
                before_gate = self.workspace._gate(db, case)
                self.workspace._event(
                    db,
                    case,
                    "merchant_evidence",
                    "merchant_recorded",
                    {
                        "finding": "confirmed",
                        "note": payload.note,
                        "reference": row["id"],
                    },
                    promise,
                )
                self.workspace._invalidate_if_changed(db, case, before_gate)
            return self._return(
                db.execute(
                    "SELECT * FROM platform_returns WHERE id=?", (row["id"],)
                ).fetchone()
            )

    def scan(self, merchant, actor="worker", *, moment=None):
        moment = moment or datetime.now(timezone.utc)
        with self.store.transaction(write=True) as db:
            rows = db.execute(
                "SELECT * FROM resolution_cases WHERE merchant_id=? ORDER BY created_at,id",
                (str(merchant),),
            ).fetchall()
            active = set()
            created = 0
            for case in rows:
                view = self.workspace._view(db, case)
                assignment = db.execute(
                    "SELECT assignee FROM resolution_operations WHERE resolution_id=?",
                    (case["id"],),
                ).fetchone()
                for promise in view.promises:
                    if (
                        not promise.terms.due_at
                        or promise.terms.due_at >= moment
                        or promise.outcome == "fulfilled"
                    ):
                        continue
                    active.add((str(promise.id), promise.revision))
                    if not assignment or not assignment["assignee"]:
                        owner = db.execute(
                            "SELECT name FROM platform_staff WHERE merchant_id=? AND role='owner' AND active=1 ORDER BY created_at,id LIMIT 1",
                            (str(merchant),),
                        ).fetchone()
                        label = owner["name"][:80] if owner else "Workspace owner"
                        db.execute(
                            "INSERT INTO resolution_operations (resolution_id,merchant_id,assignee) VALUES (?,?,?) ON CONFLICT(resolution_id) DO UPDATE SET assignee=excluded.assignee,revision=resolution_operations.revision+1",
                            (case["id"], str(merchant), label),
                        )
                        assignment = {"assignee": label}
                        audit(
                            db,
                            merchant,
                            actor,
                            "overdue_case_escalated",
                            case["id"],
                            assignee=label,
                        )
                    progress = promise.refund_progress
                    pending = bool(
                        progress
                        and progress.history_current
                        and progress.provider_pending_amount > 0
                    )
                    reason = (
                        "Refund pending with provider" if pending else promise.reason
                    )
                    draft = (
                        "We are reviewing your overdue "
                        + promise.terms.target.kind.replace("_", " ")
                        + " commitment. "
                    )
                    draft += (
                        "The provider still reports a pending refund."
                        if pending
                        else "We will update you after checking the remaining evidence."
                    )
                    db.execute(
                        "UPDATE platform_alerts SET state='superseded',resolved_at=? WHERE merchant_id=? AND promise_id=? AND state='open' AND day<>?",
                        (
                            now(),
                            str(merchant),
                            str(promise.id),
                            moment.date().isoformat(),
                        ),
                    )
                    result = db.execute(
                        "INSERT INTO platform_alerts VALUES (?,?,?,?,?,?, 'open',?,?,?, ?,NULL) ON CONFLICT(merchant_id,promise_id,promise_revision,day) DO UPDATE SET reason=excluded.reason,customer_draft=excluded.customer_draft,assignee=excluded.assignee",
                        (
                            str(uuid4()),
                            str(merchant),
                            case["id"],
                            str(promise.id),
                            promise.revision,
                            moment.date().isoformat(),
                            assignment["assignee"]
                            if assignment and assignment["assignee"]
                            else "Workspace owner",
                            reason,
                            draft,
                            now(),
                        ),
                    )
                    created += result.rowcount
            for alert in db.execute(
                "SELECT id,promise_id,promise_revision FROM platform_alerts WHERE merchant_id=? AND state='open'",
                (str(merchant),),
            ).fetchall():
                if (alert["promise_id"], alert["promise_revision"]) not in active:
                    db.execute(
                        "UPDATE platform_alerts SET state='resolved',resolved_at=? WHERE id=?",
                        (now(), alert["id"]),
                    )
            audit(db, merchant, actor, "watchdog_scanned", created=created)
        return self.alerts(merchant)

    def alerts(self, merchant):
        with self.store.transaction() as db:
            return {
                "items": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM platform_alerts WHERE merchant_id=? AND state='open' ORDER BY created_at DESC LIMIT 500",
                        (str(merchant),),
                    )
                ]
            }

    def dashboard(self, merchant):
        with self.store.transaction() as db:
            cases = db.execute(
                "SELECT * FROM resolution_cases WHERE merchant_id=?", (str(merchant),)
            ).fetchall()
            outcomes, remedies, reasons = Counter(), Counter(), Counter()
            overdue = awaiting = 0
            for case in cases:
                view = self.workspace._view(db, case)
                outcomes[view.outcome] += 1
                for p in view.promises:
                    remedies[p.terms.target.kind] += 1
                    overdue += int(p.overdue and p.outcome != "fulfilled")
                    awaiting += int(
                        p.evidence_source != "provider_confirmed"
                        and p.outcome != "fulfilled"
                    )
                row = db.execute(
                    "SELECT issue_type FROM customer_intake_invites WHERE resolution_id=?",
                    (case["id"],),
                ).fetchone()
                if row and row["issue_type"]:
                    reasons[row["issue_type"]] += 1
            # Shared captures are one balance. Use maximum cumulative commitment per
            # capture rather than summing overlapping promises on multiple cases.
            balances = {}
            closure = []
            for row in db.execute(
                "SELECT c.id,c.closed_at,(SELECT min(e.recorded_at) FROM case_events e WHERE e.case_id=c.id AND e.event_type='case.created') AS created_at FROM cases c WHERE c.merchant_id=?",
                (str(merchant),),
            ):
                case = self.store._require_case(db, row["id"], merchant)
                if case.commitment:
                    key = case.payment.capture_id
                    entry = balances.setdefault(
                        key,
                        {
                            "promised": Decimal(0),
                            "completed": Decimal(0),
                            "pending": Decimal(0),
                        },
                    )
                    entry["promised"] = max(
                        entry["promised"],
                        case.commitment.amount
                        if case.commitment.status == "accepted"
                        else Decimal(0),
                    )
                    # Do not confuse manual ledger observations with independent provider proof.
                    completed = db.execute(
                        "SELECT COALESCE(sum(amount_cents),0) FROM refunds WHERE merchant_id=? AND capture_id=? AND status='completed'",
                        (str(merchant), key),
                    ).fetchone()[0]
                    pending = db.execute(
                        "SELECT COALESCE(sum(amount_cents),0) FROM refunds WHERE merchant_id=? AND capture_id=? AND status='pending'",
                        (str(merchant), key),
                    ).fetchone()[0]
                    entry["completed"], entry["pending"] = (
                        Decimal(completed) / 100,
                        Decimal(pending) / 100,
                    )
                if row["closed_at"] and row["created_at"]:
                    closure.append(
                        (
                            datetime.fromisoformat(row["closed_at"])
                            - datetime.fromisoformat(row["created_at"])
                        ).total_seconds()
                    )

            def total(key):
                return _money(sum((v[key] for v in balances.values()), Decimal(0)))

            remaining = sum(
                (
                    max(Decimal(0), v["promised"] - v["completed"] - v["pending"])
                    for v in balances.values()
                ),
                Decimal(0),
            )
            return {
                "case_count": len(cases),
                "outcomes": dict(outcomes),
                "remedies": dict(remedies),
                "complaint_reasons": dict(reasons),
                "overdue_promises": overdue,
                "awaiting_evidence": awaiting,
                "financial": {
                    "currency": "USD",
                    "source": "recorded_ledger_not_independent_provider_verification",
                    "shared_capture_count": len(balances),
                    "promised": total("promised"),
                    "completed": total("completed"),
                    "pending": total("pending"),
                    "outstanding_excluding_pending": _money(remaining),
                },
                "resolution_time": {
                    "sample_count": len(closure),
                    "average_hours": round(sum(closure) / len(closure) / 3600, 2)
                    if closure
                    else None,
                },
            }

    def packages(self, merchant, case_id):
        with self.store.transaction() as db:
            self.workspace._case(db, case_id, merchant)
            return {
                "items": [
                    {
                        k: r[k]
                        for k in (
                            "id",
                            "dispute_id",
                            "reason",
                            "snapshot_hash",
                            "created_at",
                            "reviewed_at",
                            "reviewer_id",
                        )
                    }
                    for r in db.execute(
                        "SELECT * FROM platform_packages WHERE case_id=? AND merchant_id=? ORDER BY created_at DESC",
                        (str(case_id), str(merchant)),
                    )
                ]
            }

    @staticmethod
    def _assurance_sources(db, merchant, case_id):
        case = db.execute(
            "SELECT refund_case_id FROM resolution_cases WHERE id=? AND merchant_id=?",
            (str(case_id), str(merchant)),
        ).fetchone()
        capture = (
            db.execute(
                "SELECT capture_id FROM cases WHERE id=? AND merchant_id=?",
                (case[0], str(merchant)),
            ).fetchone()
            if case and case[0]
            else None
        )
        return {
            "return_guides": [
                dict(r)
                for r in db.execute(
                    "SELECT g.return_id,g.revision,g.data_json FROM assurance_return_guides g JOIN platform_returns r ON r.id=g.return_id WHERE g.merchant_id=? AND r.case_id=? ORDER BY g.return_id",
                    (str(merchant), str(case_id)),
                )
            ],
            "return_labels": [
                dict(r)
                for r in db.execute(
                    "SELECT l.id,l.filename,l.sha256 FROM assurance_return_labels l JOIN platform_returns r ON r.id=l.return_id WHERE l.merchant_id=? AND r.case_id=? ORDER BY l.id",
                    (str(merchant), str(case_id)),
                )
            ],
            "return_reviews": [
                dict(r)
                for r in db.execute(
                    "SELECT v.id,v.data_json,v.actor_id FROM assurance_return_reviews v JOIN platform_returns r ON r.id=v.return_id WHERE v.merchant_id=? AND r.case_id=? ORDER BY v.id",
                    (str(merchant), str(case_id)),
                )
            ],
            "disputes": [
                dict(r)
                for r in db.execute(
                    "SELECT provider,reference,version,state,data_json FROM assurance_disputes WHERE merchant_id=? AND capture_id=? ORDER BY id",
                    (str(merchant), capture[0]),
                )
            ]
            if capture
            else [],
        }

    @staticmethod
    def _source_revision(db, case_id, merchant):
        job = db.execute(
            "SELECT revision FROM investigation_jobs WHERE resolution_id=? AND merchant_id=?",
            (str(case_id), str(merchant)),
        ).fetchone()
        imports = db.execute(
            "SELECT count(*) FROM platform_ticket_messages m JOIN platform_imports i ON i.id=m.import_id WHERE i.case_id=? AND i.merchant_id=?",
            (str(case_id), str(merchant)),
        ).fetchone()[0]
        configs = [
            [r["provider"], r["revision"]]
            for r in db.execute(
                "SELECT provider,revision FROM platform_connections WHERE merchant_id=? ORDER BY provider",
                (str(merchant),),
            )
        ]
        return {
            "evidence_revision": job[0] if job else 0,
            "imported_messages": imports,
            "connections": configs,
            "assurance": Operations._assurance_sources(db, merchant, case_id),
        }

    def build_package(self, merchant, actor, case_id, payload):
        from .evidence_workspace import EvidenceWorkspace

        with self.store.transaction() as db:
            self.workspace._case(db, case_id, merchant)
            source_revision = self._source_revision(db, case_id, merchant)
        # Fetch every page, including histories longer than the default UI page.
        bundle = (
            EvidenceWorkspace(self.store)
            .bundle(case_id, merchant, 100, 0)
            .model_dump(mode="json")
        )
        timeline, offset = [], 0
        while True:
            page = self.workspace.timeline(case_id, merchant, 100, offset)
            timeline.extend(i.model_dump(mode="json") for i in page.items)
            offset += len(page.items)
            if not page.items or offset >= page.total:
                break
        messages = [
            m.model_dump(mode="json")
            for m in CustomerPortal(self.store).merchant_messages(case_id, merchant)
        ]
        payment_timeline = []
        refund_case = bundle["case"].get("refund_case_id")
        if refund_case:
            offset = 0
            while True:
                page = self.store.timeline(
                    refund_case, merchant, limit=100, offset=offset
                )
                payment_timeline.extend(i.model_dump(mode="json") for i in page.items)
                offset += len(page.items)
                if not page.items or offset >= page.total:
                    break
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant)
            if self._source_revision(db, case_id, merchant) != source_revision:
                raise StoreError(
                    409,
                    "Evidence changed while preparing the package; retry with the current case",
                )
            imported = [
                dict(r)
                for r in db.execute(
                    "SELECT m.source_id,m.sender,m.body,m.public,m.sent_at FROM platform_ticket_messages m JOIN platform_imports i ON i.id=m.import_id WHERE i.case_id=? AND i.merchant_id=? ORDER BY m.sent_at,m.source_id",
                    (case["id"], str(merchant)),
                )
            ]
            view = self.workspace._view(db, case)
            from .dispute_evidence import checklist as required_evidence, documents

            checklist = required_evidence(
                db, merchant, case, view, payload.reason, imported=bool(imported)
            )
            files = [
                dict(r)
                for r in db.execute(
                    "SELECT id,filename,content_type,size_bytes,sha256,created_at FROM customer_evidence WHERE resolution_id=? AND merchant_id=?",
                    (case["id"], str(merchant)),
                )
            ]
            snapshot = {
                "dispute_id": payload.dispute_id,
                "reason": payload.reason,
                "case": bundle,
                "timeline": timeline,
                "conversation": messages,
                "support_sources": imported,
                "checklist": checklist,
                "customer_files": files,
                "payment_timeline": payment_timeline,
                "dispute_documents": documents(db, merchant, case_id),
                "assurance": self._assurance_sources(db, merchant, case_id),
                "source_revision": source_revision,
                "classification": "merchant_review_package_not_paypal_submission",
                "authorizes_payment": False,
            }
            raw = _json(snapshot)
            if len(raw.encode()) > 20_000_000:
                raise StoreError(
                    422,
                    "This evidence package exceeds the export bound; arrange a manual evidence review",
                )
            fingerprint = sha256(raw.encode()).hexdigest()
            prior = db.execute(
                "SELECT id FROM platform_packages WHERE merchant_id=? AND case_id=? AND snapshot_hash=?",
                (str(merchant), str(case_id), fingerprint),
            ).fetchone()
            identifier = prior["id"] if prior else str(uuid4())
            if not prior:
                db.execute(
                    "INSERT INTO platform_packages VALUES (?,?,?,?,?,?,?, ?,NULL,NULL)",
                    (
                        identifier,
                        str(merchant),
                        str(case_id),
                        payload.dispute_id,
                        payload.reason,
                        raw,
                        fingerprint,
                        now(),
                    ),
                )
                audit(
                    db,
                    merchant,
                    actor,
                    "dispute_package_created",
                    identifier,
                    snapshot_hash=fingerprint,
                )
            return {
                "id": identifier,
                "snapshot_hash": fingerprint,
                "checklist": checklist,
                "submitted_to_paypal": False,
            }

    def package(self, merchant, case_id, identifier, *, review=False, actor=None):
        with self.store.transaction(write=review) as db:
            self.workspace._case(db, case_id, merchant)
            row = db.execute(
                "SELECT * FROM platform_packages WHERE id=? AND merchant_id=? AND case_id=?",
                (str(identifier), str(merchant), str(case_id)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Evidence package not found")
            snapshot = json.loads(row["snapshot_json"])
            stale = snapshot.get("source_revision") != self._source_revision(
                db, case_id, merchant
            )
            if review and stale:
                raise StoreError(
                    409, "Case evidence changed; prepare and review a new package"
                )
            if review and not row["reviewed_at"]:
                db.execute(
                    "UPDATE platform_packages SET reviewed_at=?,reviewer_id=? WHERE id=?",
                    (now(), actor, row["id"]),
                )
                audit(
                    db,
                    merchant,
                    actor,
                    "dispute_package_reviewed",
                    row["id"],
                    snapshot_hash=row["snapshot_hash"],
                )
            return {
                "id": row["id"],
                "snapshot_hash": row["snapshot_hash"],
                "reviewed": bool(review or row["reviewed_at"]),
                "stale": stale,
                "snapshot": snapshot,
                "submitted_to_paypal": False,
            }
