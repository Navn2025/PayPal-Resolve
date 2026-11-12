"""Order-bound customer support for explicitly enabled server integrations."""

from app.schemas.aftercare import (
    IssueInput as IssueInput,
    IssueReceipt as IssueReceipt,
    OrderLocator as OrderLocator,
    OrderResolution as OrderResolution,
    SupportKeyInput as SupportKeyInput,
    SupportKeyReceipt as SupportKeyReceipt,
    SupportRefund as SupportRefund,
    SupportRequestPage as SupportRequestPage,
    SupportRequestView as SupportRequestView,
)


from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4


from app.schemas.commerce import CommerceSnapshot
from app.services.commerce.orders import CommerceWorkspace
from app.services.customer.portal import CustomerPortal
from app.schemas.customer_portal import LinkCreate, MessageCreate, PublicPromise
from app.schemas.customer_progress import CustomerNextStep
from app.services.customer.progress import customer_progress
from app.core.exceptions import StoreError
from app.services.resolution.evidence import evidence_summary
from app.services.merchant.identity import audit, digest, now
from app.services.payments.history import HISTORY_MAX_AGE


class Aftercare:
    def __init__(self, store):
        self.store = store
        self.commerce = CommerceWorkspace(store)
        self.workspace = self.commerce.cases

    def _order(self, db, merchant, token, locator):
        if not token.startswith("rweb_"):
            key = db.execute(
                "SELECT id,scope FROM merchant_api_keys WHERE token_hash=? AND merchant_id=? AND revoked_at IS NULL",
                (digest(token), str(merchant)),
            ).fetchone()
            if not key:
                raise StoreError(401, "Invalid integration key")
            if key["scope"] != "full":
                grant = db.execute(
                    "SELECT source FROM aftercare_apps WHERE key_id=? AND merchant_id=?",
                    (key["id"], str(merchant)),
                ).fetchone()
                if not grant or grant["source"] != locator.source:
                    raise StoreError(
                        403, "Enable a customer-support key for this app source"
                    )
        row = db.execute(
            "SELECT * FROM commerce_orders WHERE merchant_id=? AND source=? AND order_reference=?",
            (str(merchant), locator.source, locator.order_reference),
        ).fetchone()
        if not row:
            raise StoreError(
                404, "Sync this order from your app before opening support"
            )
        return row

    def requests(self, merchant, case_id):
        with self.store.transaction() as db:
            self.workspace._case(db, case_id, merchant)
            rows = db.execute(
                "SELECT * FROM aftercare_issues WHERE merchant_id=? AND case_id=? ORDER BY created_at DESC LIMIT 100",
                (str(merchant), str(case_id)),
            ).fetchall()
            return SupportRequestPage(
                items=[
                    SupportRequestView(
                        issue_id=r["id"],
                        created_at=r["created_at"],
                        **{
                            key: json.loads(r["request_json"])[key]
                            for key in (
                                "source",
                                "reason",
                                "requested_resolution",
                                "message",
                            )
                        },
                    )
                    for r in rows
                ]
            )

    @staticmethod
    def _receipt(row, reference):
        return IssueReceipt(
            issue_id=row["id"],
            case_id=row["case_id"],
            order_reference=reference,
            created_at=row["created_at"],
        )

    def open_issue(self, merchant, actor, token, payload):
        with self.store.transaction(write=True) as db:
            order = self._order(db, merchant, token, payload)
            encoded = payload.model_dump_json()
            previous = db.execute(
                "SELECT * FROM aftercare_issues WHERE merchant_id=? AND request_id=?",
                (str(merchant), str(payload.request_id)),
            ).fetchone()
            if previous:
                if (
                    previous["request_json"] != encoded
                    or previous["order_id"] != order["id"]
                ):
                    raise StoreError(
                        409, "Issue request ID already has different content"
                    )
                return self._receipt(previous, payload.order_reference)
            snapshot = CommerceSnapshot.model_validate_json(order["snapshot_json"])
            case = self.commerce._case_for_order(db, merchant, snapshot, order, None)
            if not order["resolution_id"]:
                self.commerce._record_evidence(db, case, snapshot)
                db.execute(
                    "UPDATE commerce_orders SET resolution_id=? WHERE id=?",
                    (case["id"], order["id"]),
                )
            if (
                db.execute(
                    "SELECT count(*) FROM aftercare_issues WHERE case_id=?",
                    (case["id"],),
                ).fetchone()[0]
                >= 100
            ):
                raise StoreError(
                    409, "This order has reached its support request limit"
                )
            message = CustomerPortal._record(
                db,
                case,
                "customer",
                MessageCreate(request_id=payload.request_id, body=payload.message),
            )
            identifier, stamp = str(uuid4()), now()
            db.execute(
                "INSERT INTO aftercare_issues VALUES (?,?,?,?,?,?,?)",
                (
                    identifier,
                    str(merchant),
                    order["id"],
                    case["id"],
                    str(payload.request_id),
                    encoded,
                    stamp,
                ),
            )
            db.execute(
                "UPDATE resolution_operations SET waiting_on_customer=0,revision=revision+1 WHERE resolution_id=? AND merchant_id=? AND waiting_on_customer=1",
                (case["id"], str(merchant)),
            )
            self.workspace._event(
                db,
                case,
                "merchant_evidence",
                "merchant_recorded",
                {
                    "evidence_type": "app_support_request",
                    "issue_id": identifier,
                    "reason": payload.reason,
                    "requested_resolution": payload.requested_resolution,
                    "message_id": str(message.id),
                    "identity_source": "merchant_app",
                },
            )
            audit(
                db,
                merchant,
                actor,
                "app_support_requested",
                identifier,
                source=payload.source,
                case_id=case["id"],
            )
            return IssueReceipt(
                issue_id=identifier,
                case_id=case["id"],
                order_reference=payload.order_reference,
                created_at=stamp,
            )

    def status(self, merchant, token, locator):
        with self.store.transaction() as db:
            return self.status_in(db, merchant, token, locator)

    def status_in(self, db, merchant, token, locator):
        order = self._order(db, merchant, token, locator)
        if not order["resolution_id"]:
            return OrderResolution(
                order_reference=locator.order_reference,
                case_id=None,
                stage="no_issue",
                next_action="report_issue",
                next_step=CustomerNextStep(
                    actor="customer",
                    action="Report an issue with this order.",
                    due_at=None,
                    overdue=False,
                ),
                promises=[],
                refund=None,
                issue_count=0,
            )
        case = self.workspace._case(db, order["resolution_id"], merchant)
        view = self.workspace._view(db, case)
        _, step = customer_progress(db, self.store, case, view)
        stage = (
            "resolved"
            if view.outcome == "fulfilled"
            else "pending"
            if view.outcome == "pending"
            else "needs_review"
            if view.outcome == "needs_review"
            else "under_review"
        )
        action = (
            "none"
            if stage == "resolved"
            else "open_portal"
            if step.actor == "customer"
            else "wait"
        )
        offer = db.execute(
            "SELECT * FROM platform_offers WHERE case_id=? ORDER BY revision DESC LIMIT 1",
            (case["id"],),
        ).fetchone()
        if offer and offer["status"] == "published" and offer["expires_at"] > now():
            current = {str(p.id): p.revision for p in view.promises}
            if all(
                current.get(c["promise_id"]) == c["promise_revision"]
                for c in json.loads(offer["choices_json"])
            ):
                stage, action = "action_required", "review_offer"
                step = CustomerNextStep(
                    actor="customer",
                    action="Review the merchant's resolution offer.",
                    due_at=offer["expires_at"],
                    overdue=False,
                )
        if step.actor == "customer" and stage != "resolved":
            stage = "action_required"
        refund_promise = next(
            (p for p in view.promises if p.terms.target.kind == "refund"), None
        )
        evidence = evidence_summary(db, case)
        connection = db.execute(
            "SELECT enabled,updated_at FROM platform_connections WHERE merchant_id=? AND provider='paypal'",
            (str(merchant),),
        ).fetchone()

        def fresh(checked_at):
            if not checked_at:
                return False
            age = datetime.now(timezone.utc) - checked_at
            return (
                age.total_seconds() >= 0
                and age <= HISTORY_MAX_AGE
                and (
                    not connection
                    or (
                        connection["enabled"]
                        and connection["updated_at"] <= checked_at.isoformat()
                    )
                )
            )

        refund = None
        if refund_promise:
            progress = refund_promise.refund_progress
            current = bool(
                progress
                and progress.history_current
                and fresh(refund_promise.checked_at)
            )
            completed = progress.provider_completed_amount if current else None
            pending = progress.provider_pending_amount if current else None
            amount = refund_promise.terms.target.amount
            refund = SupportRefund(
                promised_amount=amount,
                completed_amount=completed,
                pending_amount=pending,
                remaining_amount=max(Decimal(0), amount - completed - pending)
                if current
                else None,
                verification="current" if current else "unverified",
                last_checked_at=refund_promise.checked_at or evidence.last_checked_at,
            )
        elif evidence.last_checked_at:
            current = evidence.order_history_verified and fresh(
                evidence.last_checked_at
            )
            refund = SupportRefund(
                promised_amount=None,
                completed_amount=evidence.provider_completed_amount
                if current
                else None,
                pending_amount=evidence.provider_pending_amount if current else None,
                remaining_amount=None,
                verification="current" if current else "unverified",
                last_checked_at=evidence.last_checked_at,
            )
        count = db.execute(
            "SELECT count(*) FROM aftercare_issues WHERE case_id=? AND merchant_id=?",
            (case["id"], str(merchant)),
        ).fetchone()[0]
        return OrderResolution(
            order_reference=locator.order_reference,
            case_id=view.id,
            stage=stage,
            next_action=action,
            next_step=step,
            promises=[
                PublicPromise(
                    kind=p.terms.target.kind,
                    promise=p.terms.promise,
                    outcome=p.outcome,
                    due_at=p.terms.due_at,
                    provider_confirmed=p.evidence_source == "provider_confirmed"
                    and p.outcome == "fulfilled",
                )
                for p in view.promises
            ],
            refund=refund,
            issue_count=count,
        )

    def portal(self, merchant, actor, token, locator, settings):
        from app.integrations.paypal.identity import web_origin

        with self.store.transaction(write=True) as db:
            order = self._order(db, merchant, token, locator)
            if not order["resolution_id"]:
                raise StoreError(409, "Open an issue before creating a support link")
            case = self.workspace._case(db, order["resolution_id"], merchant)
            issued = CustomerPortal._issue(
                db,
                case,
                LinkCreate(title="Your order support", show_order_reference=True),
            )
            audit(
                db,
                merchant,
                actor,
                "app_support_link_issued",
                case["id"],
                source=locator.source,
            )
        origin = web_origin(
            settings.customer_public_origin or settings.merchant_web_origin
        )
        return (
            issued.model_copy(
                update={"public_url": origin + "/customer#" + issued.token}
            )
            if origin
            else issued
        )
