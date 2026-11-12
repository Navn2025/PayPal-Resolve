"""Reconciled safe snapshots for resumable app synchronization, independent of webhook delivery."""

from app.schemas.sdk_events import (
    AppResolutionEvent as AppResolutionEvent,
    EventPage as EventPage,
    EventPull as EventPull,
)


from hashlib import sha256
import json
from uuid import uuid4


from app.services.commerce.aftercare import Aftercare
from app.schemas.aftercare import OrderLocator
from app.services.merchant.identity import now
from app.core.exceptions import StoreError


class Events:
    def __init__(self, store):
        self.store = store
        self.aftercare = Aftercare(store)

    def reconcile(self, merchant, source, token=None, limit=100):
        with self.store.transaction(write=True) as db:
            # Check the app grant even when this source has no orders.
            if token and not token.startswith("rweb_"):
                from app.services.merchant.identity import digest

                row = db.execute(
                    "SELECT id,scope FROM merchant_api_keys WHERE token_hash=? AND merchant_id=? AND revoked_at IS NULL",
                    (digest(token), str(merchant)),
                ).fetchone()
                if not row:
                    raise StoreError(401, "Invalid integration key")
                if (
                    row["scope"] != "full"
                    and not db.execute(
                        "SELECT 1 FROM aftercare_apps WHERE merchant_id=? AND key_id=? AND source=?",
                        (str(merchant), row["id"], source),
                    ).fetchone()
                ):
                    raise StoreError(
                        403, "Enable a customer-support key for this app source"
                    )
            rows = db.execute(
                "SELECT o.* FROM commerce_orders o LEFT JOIN assurance_projections p ON p.order_id=o.id WHERE o.merchant_id=? AND o.source=? AND o.resolution_id IS NOT NULL ORDER BY COALESCE(p.updated_at,''),o.id LIMIT ?",
                (str(merchant), source, limit),
            ).fetchall()
            for order in rows:
                locator = OrderLocator(
                    source=source, order_reference=order["order_reference"]
                )
                # Worker bypasses only key authentication; ownership still comes from this owned order.
                status = self.aftercare.status_in(
                    db, merchant, token or "rweb_worker", locator
                )
                version = db.execute(
                    "SELECT COALESCE(max(sequence),0) FROM customer_portal_messages WHERE merchant_id=? AND resolution_id=?",
                    (str(merchant), order["resolution_id"]),
                ).fetchone()[0]
                returns = [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,revision,status FROM platform_returns WHERE merchant_id=? AND case_id=? ORDER BY id",
                        (str(merchant), order["resolution_id"]),
                    )
                ]
                guides = [
                    dict(r)
                    for r in db.execute(
                        "SELECT g.return_id,g.revision FROM assurance_return_guides g JOIN platform_returns r ON r.id=g.return_id WHERE g.merchant_id=? AND r.case_id=? ORDER BY g.return_id",
                        (str(merchant), order["resolution_id"]),
                    )
                ]
                from app.services.assurance.resolution import Assurance

                journey = (
                    Assurance(self.store)
                    .journey_in(db, merchant, token or "rweb_worker", locator)
                    .model_dump(mode="json", exclude={"resolution"})
                )
                label_count = db.execute(
                    "SELECT count(*) FROM assurance_return_labels l JOIN platform_returns r ON r.id=l.return_id WHERE l.merchant_id=? AND r.case_id=?",
                    (str(merchant), order["resolution_id"]),
                ).fetchone()[0]
                policy = db.execute(
                    "SELECT revision FROM assurance_policies WHERE merchant_id=?",
                    (str(merchant),),
                ).fetchone()
                snapshot = {
                    "resolution": status.model_dump(mode="json"),
                    "conversation_version": version,
                    "returns": returns,
                    "return_guides": guides,
                    "saved_label_count": label_count,
                    "return_policy_revision": policy[0] if policy else 0,
                    "refund_journey": journey,
                }
                raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
                fingerprint = sha256(raw.encode()).hexdigest()
                previous = db.execute(
                    "SELECT * FROM assurance_projections WHERE order_id=?",
                    (order["id"],),
                ).fetchone()
                stamp = now()
                if not previous or previous["fingerprint"] != fingerprint:
                    revision = previous["revision"] + 1 if previous else 1
                    db.execute(
                        "INSERT INTO assurance_projections VALUES (?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET revision=excluded.revision,fingerprint=excluded.fingerprint,snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at",
                        (order["id"], str(merchant), revision, fingerprint, raw, stamp),
                    )
                    db.execute(
                        "INSERT INTO assurance_events (id,merchant_id,source,order_id,order_reference,revision,snapshot_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            str(uuid4()),
                            str(merchant),
                            source,
                            order["id"],
                            order["order_reference"],
                            revision,
                            raw,
                            stamp,
                        ),
                    )
                else:
                    db.execute(
                        "UPDATE assurance_projections SET updated_at=? WHERE order_id=?",
                        (stamp, order["id"]),
                    )
            return len(rows)

    def pull(self, merchant, token, payload):
        checked = self.reconcile(merchant, payload.source, token)
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM assurance_events WHERE merchant_id=? AND source=? AND sequence>? ORDER BY sequence LIMIT ?",
                (
                    str(merchant),
                    payload.source,
                    payload.after_sequence,
                    payload.limit + 1,
                ),
            ).fetchall()
            more, rows = len(rows) > payload.limit, rows[: payload.limit]
            items = [
                AppResolutionEvent(
                    id=r["id"],
                    sequence=r["sequence"],
                    source=r["source"],
                    order_reference=r["order_reference"],
                    revision=r["revision"],
                    snapshot=json.loads(r["snapshot_json"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]
            return EventPage(
                merchant_id=merchant,
                source=payload.source,
                items=items,
                next_after_sequence=items[-1].sequence
                if items
                else payload.after_sequence,
                has_more=more,
                reconciled_orders=checked,
            )
