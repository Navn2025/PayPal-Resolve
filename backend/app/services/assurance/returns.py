"""Explainable return checks, inspection findings and authenticated reusable labels."""

from app.schemas.return_assurance import (
    EligibilityView as EligibilityView,
    GuideInput as GuideInput,
    InspectionInput as InspectionInput,
    LabelMetadata as LabelMetadata,
    PolicyUpdate as PolicyUpdate,
    PolicyView as PolicyView,
    PublicReturnPolicy as PublicReturnPolicy,
    ReturnGuideView as ReturnGuideView,
    ReturnLabelFile as ReturnLabelFile,
    ReturnPolicy as ReturnPolicy,
)


from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4


from app.services.customer.evidence import _validated_file
from app.core.exceptions import StoreError
from app.services.merchant.identity import audit, now


class Returns:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def policy_in(db, merchant):
        row = db.execute(
            "SELECT * FROM assurance_policies WHERE merchant_id=?", (str(merchant),)
        ).fetchone()
        return (
            PolicyView(
                revision=row["revision"],
                policy=ReturnPolicy.model_validate_json(row["data_json"]),
            )
            if row
            else PolicyView(revision=0, policy=ReturnPolicy(window_days=30))
        )

    def policy(self, merchant):
        with self.store.transaction() as db:
            return self.policy_in(db, merchant)

    def public_policy(self, merchant):
        view = self.policy(merchant)
        policy = view.policy
        return PublicReturnPolicy(
            policy_enabled=policy.enabled,
            revision=view.revision,
            window_days=policy.window_days if policy.enabled else None,
            shipping_paid_by=policy.shipping_paid_by if policy.enabled else None,
            restocking_fee=policy.restocking_fee if policy.enabled else None,
            inspection_required=policy.enabled and policy.inspection_required,
            evidence_required=policy.enabled and policy.photos_required,
            instructions=policy.instructions,
        )

    def save_policy(self, merchant, actor, payload):
        with self.store.transaction(write=True) as db:
            old = self.policy_in(db, merchant)
            if old.revision != payload.expected_revision:
                raise StoreError(409, "Return policy changed; reload it")
            policy = ReturnPolicy.model_validate(
                payload.model_dump(exclude={"expected_revision"})
            )
            db.execute(
                "INSERT INTO assurance_policies VALUES (?,?,?,?) ON CONFLICT(merchant_id) DO UPDATE SET revision=excluded.revision,data_json=excluded.data_json,updated_at=excluded.updated_at",
                (str(merchant), old.revision + 1, policy.model_dump_json(), now()),
            )
            audit(
                db, merchant, actor, "return_policy_updated", revision=old.revision + 1
            )
            return PolicyView(revision=old.revision + 1, policy=policy)

    @staticmethod
    def eligible_in(db, merchant, order, items, delivered_at=None):
        view = Returns.policy_in(db, merchant)
        policy, flags = view.policy, []
        from collections import Counter

        quantities = Counter()
        for item in json.loads(order["snapshot_json"])["items"]:
            quantities[item["product_id"]] += item["quantity"]
        for row in db.execute(
            "SELECT items_json FROM platform_returns WHERE order_id=? AND status!='rejected'",
            (order["id"],),
        ):
            for item in json.loads(row[0]):
                quantities[item["product_id"]] -= item["quantity"]
        requested = Counter()
        for item in items:
            requested[item.product_id] += item.quantity
        if any(
            quantity > quantities[product] for product, quantity in requested.items()
        ):
            flags.append("Selected quantities exceed unreserved order items")
        if policy.enabled:
            if not delivered_at:
                flags.append("Delivery date needs confirmation")
            elif delivered_at > datetime.now(timezone.utc):
                flags.append("Delivery date is in the future")
            elif datetime.now(timezone.utc) - delivered_at > timedelta(
                days=policy.window_days
            ):
                flags.append(
                    "Outside the configured return window; merchant review required"
                )
            if any(item.product_id in policy.excluded_products for item in items):
                flags.append("A selected product needs a policy exception")
            if (
                policy.photos_required
                and not db.execute(
                    "SELECT 1 FROM customer_evidence WHERE resolution_id=? AND merchant_id=?",
                    (order["resolution_id"], str(merchant)),
                ).fetchone()
            ):
                flags.append("Requested item evidence is missing")
            count = db.execute(
                "SELECT count(*) FROM platform_returns WHERE order_id=? AND status!='rejected'",
                (order["id"],),
            ).fetchone()[0]
            if count >= 3:
                flags.append(
                    "Repeated requests require a quantity and condition review"
                )
        return EligibilityView(
            decision="needs_review" if flags else "eligible",
            policy_enabled=policy.enabled,
            policy_revision=view.revision,
            delivered_at=delivered_at,
            flags=flags,
            shipping_paid_by=policy.shipping_paid_by,
            restocking_fee=policy.restocking_fee if policy.enabled else None,
            instructions=policy.instructions,
        )

    @staticmethod
    def record_eligibility(db, merchant, identifier, eligibility):
        db.execute(
            "INSERT INTO assurance_return_reviews VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                str(merchant),
                str(identifier),
                str(uuid4()),
                "eligibility",
                eligibility.model_dump_json(),
                "policy-engine",
                now(),
            ),
        )

    @staticmethod
    def gate(db, merchant, row, action):
        policy = Returns.policy_in(db, merchant)
        if not policy.policy.enabled or action not in ("approve", "pass_inspection"):
            return
        review = db.execute(
            "SELECT * FROM assurance_return_reviews WHERE return_id=? AND merchant_id=? AND kind='inspection' ORDER BY created_at DESC,id DESC LIMIT 1",
            (row["id"], str(merchant)),
        ).fetchone()
        finding = json.loads(review["data_json"]) if review else None
        valid = bool(
            finding
            and finding["expected_revision"] == row["revision"]
            and finding["policy_revision"] == policy.revision
            and finding["finding"] == "clear"
            and finding["quantities_match"]
        )
        if (
            action == "pass_inspection"
            and policy.policy.inspection_required
            and not valid
        ):
            raise StoreError(
                409,
                "Record a current clear item/quantity inspection before completing this milestone",
            )
        if action == "approve":
            assessment = db.execute(
                "SELECT data_json FROM assurance_return_reviews WHERE return_id=? AND merchant_id=? AND kind='eligibility' ORDER BY created_at DESC LIMIT 1",
                (row["id"], str(merchant)),
            ).fetchone()
            data = json.loads(assessment[0]) if assessment else None
            needs = (
                not data
                or data["policy_revision"] != policy.revision
                or data["decision"] != "eligible"
            )
            if needs and not (valid and finding["override_policy"]):
                raise StoreError(
                    409,
                    "A manager must review policy flags and record an explicit current exception",
                )

    @staticmethod
    def _return(db, merchant, case_id, return_id):
        row = db.execute(
            "SELECT * FROM platform_returns WHERE merchant_id=? AND case_id=? AND id=?",
            (str(merchant), str(case_id), str(return_id)),
        ).fetchone()
        if not row:
            raise StoreError(404, "Return not found")
        return row

    def inspect(self, merchant, actor, role, case_id, return_id, payload):
        if payload.override_policy and role not in ("owner", "manager"):
            raise StoreError(
                403, "Only an owner or manager can approve a policy exception"
            )
        with self.store.transaction(write=True) as db:
            row = self._return(db, merchant, case_id, return_id)
            policy = self.policy_in(db, merchant)
            data = {
                **payload.model_dump(mode="json"),
                "policy_revision": policy.revision,
                "source": "merchant_recorded",
            }
            prior = db.execute(
                "SELECT * FROM assurance_return_reviews WHERE merchant_id=? AND request_id=?",
                (str(merchant), str(payload.request_id)),
            ).fetchone()
            if prior:
                if (
                    prior["return_id"] != str(return_id)
                    or json.loads(prior["data_json"]) != data
                ):
                    raise StoreError(
                        409, "Inspection request ID already has different findings"
                    )
                return {
                    "recorded": True,
                    "id": prior["id"],
                    "source": "merchant_recorded",
                }
            if row["revision"] != payload.expected_revision:
                raise StoreError(409, "Return changed; inspect the current revision")
            if (
                policy.policy.photos_required
                and payload.finding == "clear"
                and not payload.override_policy
                and not payload.evidence_ids
            ):
                raise StoreError(409, "Select evidence files for this inspection")
            for identifier in payload.evidence_ids:
                if not db.execute(
                    "SELECT 1 FROM customer_evidence WHERE id=? AND merchant_id=? AND resolution_id=?",
                    (str(identifier), str(merchant), str(case_id)),
                ).fetchone():
                    raise StoreError(404, "Evidence file does not belong to this case")
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO assurance_return_reviews VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    str(merchant),
                    str(return_id),
                    str(payload.request_id),
                    "inspection",
                    json.dumps(data),
                    actor,
                    now(),
                ),
            )
            audit(
                db,
                merchant,
                actor,
                "return_inspected",
                return_id,
                finding=payload.finding,
                override=payload.override_policy,
            )
            return {"recorded": True, "id": identifier, "source": "merchant_recorded"}

    def guide(self, merchant, case_id, return_id):
        with self.store.transaction() as db:
            self._return(db, merchant, case_id, return_id)
            row = db.execute(
                "SELECT * FROM assurance_return_guides WHERE return_id=? AND merchant_id=?",
                (str(return_id), str(merchant)),
            ).fetchone()
            policy = self.policy_in(db, merchant)
            data = (
                json.loads(row["data_json"])
                if row
                else {
                    "instructions": policy.policy.instructions,
                    "return_address": "",
                    "shipping_paid_by": policy.policy.shipping_paid_by,
                }
            )
            labels = [
                dict(r)
                for r in db.execute(
                    "SELECT id,filename,sha256,created_at FROM assurance_return_labels WHERE merchant_id=? AND return_id=? ORDER BY created_at DESC LIMIT 10",
                    (str(merchant), str(return_id)),
                )
            ]
            assessment = db.execute(
                "SELECT data_json FROM assurance_return_reviews WHERE return_id=? AND kind='eligibility' ORDER BY created_at DESC LIMIT 1",
                (str(return_id),),
            ).fetchone()
            inspection = db.execute(
                "SELECT data_json FROM assurance_return_reviews WHERE return_id=? AND kind='inspection' ORDER BY created_at DESC LIMIT 1",
                (str(return_id),),
            ).fetchone()
            return {
                "eligibility": json.loads(assessment[0]) if assessment else None,
                "inspection_status": json.loads(inspection[0])["finding"]
                if inspection
                else "unknown",
                "policy_revision": policy.revision,
                "revision": row["revision"] if row else 0,
                **data,
                "policy_enabled": policy.policy.enabled,
                "restocking_fee": str(policy.policy.restocking_fee)
                if policy.policy.enabled
                else None,
                "currency": "USD",
                "labels": labels,
                "save_label_for_later": True,
            }

    def save_guide(self, merchant, actor, case_id, return_id, payload):
        with self.store.transaction(write=True) as db:
            self._return(db, merchant, case_id, return_id)
            old = db.execute(
                "SELECT revision FROM assurance_return_guides WHERE return_id=?",
                (str(return_id),),
            ).fetchone()
            if (old[0] if old else 0) != payload.expected_revision:
                raise StoreError(409, "Return instructions changed")
            db.execute(
                "INSERT INTO assurance_return_guides VALUES (?,?,?,?,?) ON CONFLICT(return_id) DO UPDATE SET revision=excluded.revision,data_json=excluded.data_json,updated_at=excluded.updated_at",
                (
                    str(return_id),
                    str(merchant),
                    payload.expected_revision + 1,
                    payload.model_dump_json(exclude={"expected_revision"}),
                    now(),
                ),
            )
            audit(db, merchant, actor, "return_guide_saved", return_id)
        return self.guide(merchant, case_id, return_id)

    def upload_label(self, merchant, actor, case_id, return_id, filename, content):
        _validated_file(filename, "application/pdf", content)
        with self.store.transaction(write=True) as db:
            self._return(db, merchant, case_id, return_id)
            fingerprint = sha256(content).hexdigest()
            old = db.execute(
                "SELECT id,filename FROM assurance_return_labels WHERE return_id=? AND sha256=?",
                (str(return_id), fingerprint),
            ).fetchone()
            if old:
                return {
                    "id": old["id"],
                    "filename": old["filename"],
                    "sha256": fingerprint,
                }
            if (
                db.execute(
                    "SELECT count(*) FROM assurance_return_labels WHERE return_id=?",
                    (str(return_id),),
                ).fetchone()[0]
                >= 10
            ):
                raise StoreError(409, "This return already has ten saved labels")
            identifier = old[0] if old else str(uuid4())
            if not old:
                db.execute(
                    "INSERT INTO assurance_return_labels VALUES (?,?,?,?,?,?,?)",
                    (
                        identifier,
                        str(merchant),
                        str(return_id),
                        filename,
                        content,
                        fingerprint,
                        now(),
                    ),
                )
                audit(db, merchant, actor, "return_label_saved", identifier)
            return {"id": identifier, "filename": filename, "sha256": fingerprint}

    def label(self, merchant, case_id, return_id, identifier):
        with self.store.transaction() as db:
            self._return(db, merchant, case_id, return_id)
            row = db.execute(
                "SELECT * FROM assurance_return_labels WHERE merchant_id=? AND return_id=? AND id=?",
                (str(merchant), str(return_id), str(identifier)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Return label not found")
            return row["filename"], bytes(row["content"])
