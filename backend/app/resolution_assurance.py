"""Customer-safe refund journeys, shared context and recoverable issue receipts."""

from datetime import datetime
import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, Field

from .aftercare import Aftercare, OrderLocator, OrderResolution
from .customer_portal import PortalMessage
from .errors import StoreError
from .platform_identity import Input, audit, now


class TraceInput(Input):
    request_id: UUID
    refund_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    reference_type: Literal["ARN", "STAN", "RRN", "bank_reference"]
    reference: str = Field(pattern=r"^[A-Za-z0-9 -]{4,100}$")
    stage: Literal[
        "initiated", "processor_pending", "sent_to_bank", "bank_processing", "failed"
    ]
    expected_by: AwareDatetime | None = None
    note: str = Field(min_length=1, max_length=1000)


class TraceView(BaseModel):
    refund_id: str
    reference_type: str
    reference: str
    stage: str
    expected_by: datetime | None
    source: Literal["merchant_recorded"]
    recorded_at: datetime


class RefundJourney(BaseModel):
    stage: Literal[
        "not_promised",
        "needs_verification",
        "promised",
        "processor_pending",
        "sent_to_original_method",
        "buyer_reports_received",
        "needs_review",
    ]
    explanation: str
    last_checked_at: datetime | None
    buyer_reported_received_at: datetime | None
    bank_receipt_verified: Literal[False] = False
    resolution: OrderResolution
    traces: list[TraceView]
    authorizes_payment: Literal[False] = False


class ContextView(BaseModel):
    resolution: OrderResolution
    issues: list[dict]
    messages: list[PortalMessage]
    next_before_sequence: int | None
    has_more_messages: bool
    identity_source: Literal["merchant_app_or_private_buyer_link"] = (
        "merchant_app_or_private_buyer_link"
    )


class LookupIssue(OrderLocator):
    request_id: UUID


class Assurance:
    def __init__(self, store):
        self.store = store
        self.aftercare = Aftercare(store)

    def record_trace(self, merchant, actor, case_id, payload):
        with self.store.transaction(write=True) as db:
            case = self.aftercare.workspace._case(db, case_id, merchant)
            if not case["refund_case_id"]:
                raise StoreError(
                    409, "Link the payment before recording a refund trace"
                )
            legacy = self.store._require_case(db, case["refund_case_id"], merchant)
            if not db.execute(
                "SELECT 1 FROM refunds WHERE merchant_id=? AND capture_id=? AND refund_id=?",
                (str(merchant), legacy.payment.capture_id, payload.refund_id),
            ).fetchone():
                raise StoreError(
                    404, "Refund reference is not recorded against this case's capture"
                )
            data = payload.model_dump_json()
            prior = db.execute(
                "SELECT * FROM assurance_refund_traces WHERE merchant_id=? AND request_id=?",
                (str(merchant), str(payload.request_id)),
            ).fetchone()
            if prior:
                if (
                    prior["data_json"] != data
                    or prior["capture_id"] != legacy.payment.capture_id
                ):
                    raise StoreError(
                        409, "Trace request ID already has different details"
                    )
                return {"id": prior["id"], "source": "merchant_recorded"}
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO assurance_refund_traces VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    str(merchant),
                    legacy.payment.capture_id,
                    payload.refund_id,
                    str(payload.request_id),
                    data,
                    actor,
                    now(),
                ),
            )
            audit(db, merchant, actor, "refund_trace_recorded", identifier)
            self.aftercare.workspace._event(
                db,
                case,
                "merchant_evidence",
                "merchant_recorded",
                {"evidence_type": "refund_trace", "trace_id": identifier},
            )
            return {"id": identifier, "source": "merchant_recorded"}

    def journey_in(self, db, merchant, token, locator):
        row = self.aftercare._order(db, merchant, token, locator)
        resolution = self.aftercare.status_in(db, merchant, token, locator)
        traces = []
        receipt = None
        if row["resolution_id"]:
            case = self.aftercare.workspace._case(db, row["resolution_id"], merchant)
            if case["refund_case_id"]:
                legacy = self.store._require_case(db, case["refund_case_id"], merchant)
                for record in db.execute(
                    "SELECT * FROM assurance_refund_traces WHERE merchant_id=? AND capture_id=? ORDER BY created_at DESC LIMIT 25",
                    (str(merchant), legacy.payment.capture_id),
                ):
                    data = json.loads(record["data_json"])
                    traces.append(
                        TraceView(
                            **{
                                k: data[k]
                                for k in (
                                    "refund_id",
                                    "reference_type",
                                    "reference",
                                    "stage",
                                    "expected_by",
                                )
                            },
                            source="merchant_recorded",
                            recorded_at=record["created_at"],
                        )
                    )
            receipt = db.execute(
                "SELECT received_at FROM assurance_receipts WHERE resolution_id=? AND merchant_id=?",
                (row["resolution_id"], str(merchant)),
            ).fetchone()
        refund = resolution.refund
        stage, explanation = (
            "not_promised",
            "The merchant has not recorded a refund agreement for this order.",
        )
        if refund:
            if refund.verification != "current":
                stage, explanation = (
                    "needs_verification",
                    "The current provider result needs checking; unavailable amounts are not a zero refund.",
                )
            elif refund.pending_amount and refund.pending_amount > 0:
                stage, explanation = (
                    "processor_pending",
                    "A refund is pending with the payment provider. This does not confirm receipt in your bank account.",
                )
            elif refund.completed_amount and refund.completed_amount > 0:
                stage, explanation = (
                    "sent_to_original_method",
                    "The provider reports a completed refund. Posting to your original payment method can take additional time; use an available trace reference to ask your bank.",
                )
            elif refund.promised_amount is not None:
                stage, explanation = (
                    "promised",
                    "The refund agreement is recorded; completed provider reimbursement is not yet confirmed.",
                )
            else:
                stage, explanation = (
                    "not_promised",
                    "Provider history was checked; the merchant has not recorded a refund agreement for this order.",
                )
        if traces and not refund:
            stage, explanation = (
                "needs_verification",
                "A merchant-recorded refund tracing reference is available. Check the current provider result; this reference does not prove bank receipt.",
            )
        if resolution.stage == "needs_review":
            stage, explanation = (
                "needs_review",
                "The merchant needs to review the resolution and payment evidence before another action.",
            )
        if receipt:
            stage, explanation = (
                "buyer_reports_received",
                "You reported receiving the refund. This is your acknowledgement, not an independent bank observation.",
            )
        return RefundJourney(
            stage=stage,
            explanation=explanation,
            last_checked_at=refund.last_checked_at if refund else None,
            buyer_reported_received_at=receipt[0] if receipt else None,
            resolution=resolution,
            traces=traces,
        )

    def journey(self, merchant, token, locator):
        with self.store.transaction() as db:
            return self.journey_in(db, merchant, token, locator)

    def context(self, merchant, token, locator, before=None):
        with self.store.transaction() as db:
            order = self.aftercare._order(db, merchant, token, locator)
            resolution = self.aftercare.status_in(db, merchant, token, locator)
            issues, messages, next_before, more = [], [], None, False
            if order["resolution_id"]:
                case_id = order["resolution_id"]
                for row in db.execute(
                    "SELECT request_json,created_at FROM aftercare_issues WHERE merchant_id=? AND case_id=? ORDER BY created_at DESC LIMIT 100",
                    (str(merchant), case_id),
                ):
                    data = json.loads(row["request_json"])
                    issues.append(
                        {
                            "reason": data["reason"],
                            "message": data["message"],
                            "requested_resolution": data["requested_resolution"],
                            "created_at": row["created_at"],
                        }
                    )
                rows = db.execute(
                    "SELECT sequence,id,sender,body,created_at FROM customer_portal_messages WHERE resolution_id=? AND merchant_id=? AND sequence<? ORDER BY sequence DESC LIMIT 51",
                    (case_id, str(merchant), before or 9223372036854775807),
                ).fetchall()
                more, rows = len(rows) > 50, rows[:50]
                messages = [
                    PortalMessage.model_validate(
                        {k: r[k] for k in ("id", "sender", "body", "created_at")}
                    )
                    for r in reversed(rows)
                ]
                next_before = rows[-1]["sequence"] if more else None
            return ContextView(
                resolution=resolution,
                issues=issues,
                messages=messages,
                next_before_sequence=next_before,
                has_more_messages=more,
            )

    def acknowledge(self, merchant, actor, token, locator):
        with self.store.transaction(write=True) as db:
            order = self.aftercare._order(db, merchant, token, locator)
            if not order["resolution_id"]:
                raise StoreError(409, "There is no refund case to acknowledge")
            case = self.aftercare.workspace._case(db, order["resolution_id"], merchant)
            if not case["refund_case_id"]:
                raise StoreError(409, "The refund payment is not linked")
            db.execute(
                "INSERT INTO assurance_receipts VALUES (?,?,?,'buyer_reported_via_app') ON CONFLICT(resolution_id) DO NOTHING",
                (order["resolution_id"], str(merchant), now()),
            )
            audit(db, merchant, actor, "buyer_reports_refund_received", case["id"])
        return self.journey(merchant, token, locator)

    def lookup(self, merchant, token, payload):
        with self.store.transaction() as db:
            order = self.aftercare._order(db, merchant, token, payload)
            row = db.execute(
                "SELECT * FROM aftercare_issues WHERE merchant_id=? AND order_id=? AND request_id=?",
                (str(merchant), order["id"], str(payload.request_id)),
            ).fetchone()
            if not row:
                raise StoreError(
                    404, "No committed issue exists for this order and request ID"
                )
            return self.aftercare._receipt(row, payload.order_reference)
