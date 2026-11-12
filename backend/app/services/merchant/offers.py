"""Offers workflow, preserving existing transaction boundaries."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import uuid4
from app.services.payments.approvals import invalidate_approvals
from app.services.payments.cases import provider_hold
from app.services.customer.portal import CustomerPortal
from app.core.exceptions import StoreError
from app.services.merchant.identity import audit, digest, now
from app.services.merchant.operation_values import _json


class MerchantOffers:
    def __init__(self, store, workspace):
        self.store = store
        self.workspace = workspace

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
            raise StoreError(
                409, "A dispute or provider hold blocks refund offers for this payment"
            )
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
