"""Returns workflow, preserving existing transaction boundaries."""

from collections import Counter
import json
from uuid import uuid4
from app.services.commerce.orders import CommerceWorkspace
from app.services.customer.portal import CustomerPortal
from app.core.exceptions import StoreError
from app.services.merchant.identity import audit, now
from app.services.merchant.operation_values import _json


class MerchantReturns:
    def __init__(self, store, workspace):
        self.store = store
        self.workspace = workspace

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
            from app.services.assurance.returns import Returns

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
            from app.services.assurance.returns import Returns

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
