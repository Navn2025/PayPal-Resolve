"""Merchant order catalog and its optional link to a resolution case."""

from uuid import uuid4

from app.services.payments.cases import now_text
from app.services.commerce.comparison import commerce_report
from app.schemas.commerce import (
    CommerceContact,
    CommerceOrderDetail,
    CommerceOrderReceipt,
    CommerceOrderSummary,
    CommerceOrdersPage,
    CommerceSnapshot,
    CommerceSyncResult,
)
from app.core.exceptions import StoreError
from app.schemas.evidence import EvidenceRecordInput
from app.services.resolution.evidence import EvidenceWorkspace, evidence_summary
from app.schemas.resolution import ResolutionCreate


class CommerceWorkspace:
    def __init__(self, store):
        self.store = store
        self.evidence = EvidenceWorkspace(store)
        self.cases = self.evidence.workspace

    def sync(self, merchant_id, payload):
        receipt = self._save(merchant_id, payload, open_case=True)
        return CommerceSyncResult(**receipt.model_dump(exclude={"id"}))

    def register(self, merchant_id, payload):
        return self._save(merchant_id, payload, open_case=False)

    @staticmethod
    def _receipt(row):
        return CommerceOrderReceipt(
            id=row["id"],
            case_id=row["resolution_id"],
            source=row["source"],
            order_reference=row["order_reference"],
            revision=row["revision"],
            synced_at=row["synced_at"],
        )

    @staticmethod
    def _order(db, order_id, merchant_id):
        row = db.execute(
            """SELECT * FROM commerce_orders WHERE id=? AND merchant_id=?""",
            (str(order_id), str(merchant_id)),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Connected order not found")
        return row

    def _case_for_order(self, db, merchant_id, snapshot, row, requested_id):
        if row and row["resolution_id"]:
            case = self.cases._case(db, row["resolution_id"], merchant_id)
            if requested_id and str(requested_id) != case["id"]:
                # Check tenant ownership before returning a conflict.
                self.cases._case(db, requested_id, merchant_id)
                raise StoreError(
                    409, "The order already belongs to a different Resolve case"
                )
            return case
        if requested_id:
            case = self.cases._case(db, requested_id, merchant_id)
            if case["order_reference"] not in (None, snapshot.order_reference):
                raise StoreError(
                    409, "The Resolve case has a different order reference"
                )
            if db.execute(
                "SELECT 1 FROM commerce_orders WHERE resolution_id=? AND merchant_id=?",
                (case["id"], str(merchant_id)),
            ).fetchone():
                raise StoreError(409, "The Resolve case already has a connected order")
            return case
        return self.cases._create(
            db,
            merchant_id,
            ResolutionCreate(
                title="Connected order", order_reference=snapshot.order_reference
            ),
        )

    def _record_evidence(self, db, case, snapshot):
        if snapshot.payment:
            for kind, identifier in (
                ("paypal_order", snapshot.payment.paypal_order_id),
                ("paypal_capture", snapshot.payment.paypal_capture_id),
            ):
                if identifier:
                    self.evidence._link(
                        db,
                        case,
                        EvidenceRecordInput(
                            kind=kind, reference=identifier, source=snapshot.source
                        ),
                        reuse_association=True,
                    )
        self.cases._event(
            db,
            case,
            "merchant_evidence",
            "merchant_recorded",
            {
                "evidence_type": "commerce_snapshot",
                "source": snapshot.source,
                "revision": snapshot.revision,
            },
        )

    def _save(self, merchant_id, payload, *, open_case):
        snapshot = CommerceSnapshot.model_validate(
            payload.model_dump(exclude={"contact", "case_id"})
        )
        snapshot_json = snapshot.model_dump_json()
        contact_json = payload.contact.model_dump_json() if payload.contact else None
        key = (str(merchant_id), snapshot.source, snapshot.order_reference)
        with self.store.transaction(write=True) as db:
            row = db.execute(
                """SELECT * FROM commerce_orders
                   WHERE merchant_id=? AND source=? AND order_reference=?""",
                key,
            ).fetchone()
            same = bool(row and snapshot.revision == row["revision"])
            if row:
                if snapshot.revision < row["revision"]:
                    raise StoreError(
                        409, "The order snapshot is older than the stored revision"
                    )
                if same and (
                    row["snapshot_json"] != snapshot_json
                    or row["contact_json"] != contact_json
                ):
                    raise StoreError(
                        409, "The order revision already has different data"
                    )
                previous = CommerceSnapshot.model_validate_json(row["snapshot_json"])
                for name in ("paypal_order_id", "paypal_capture_id"):
                    identifier = getattr(previous.payment, name, None)
                    if identifier and identifier != getattr(
                        snapshot.payment, name, None
                    ):
                        raise StoreError(
                            409,
                            "An existing PayPal reference cannot be replaced or removed",
                        )

            case = (
                self._case_for_order(
                    db, merchant_id, snapshot, row, getattr(payload, "case_id", None)
                )
                if open_case or (row and row["resolution_id"])
                else None
            )
            case_id = case["id"] if case else None
            attaching = bool(case and (not row or not row["resolution_id"]))
            if same and not attaching:
                return self._receipt(row)

            order_id = row["id"] if row else str(uuid4())
            now = row["synced_at"] if same else now_text()
            if case:
                self._record_evidence(db, case, snapshot)
            db.execute(
                """INSERT INTO commerce_orders
                   (merchant_id,source,order_reference,id,resolution_id,revision,snapshot_json,contact_json,synced_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET resolution_id=excluded.resolution_id,
                   revision=excluded.revision,snapshot_json=excluded.snapshot_json,
                   contact_json=excluded.contact_json,synced_at=excluded.synced_at""",
                (
                    *key,
                    order_id,
                    case_id,
                    snapshot.revision,
                    snapshot_json,
                    contact_json,
                    now,
                ),
            )
            return self._receipt(self._order(db, order_id, merchant_id))

    def list_orders(self, merchant_id, *, source, q, limit, offset):
        filters = ["merchant_id=?"]
        params = [str(merchant_id)]
        if source:
            filters.append("source=?")
            params.append(source)
        if q and q.strip():
            term = (
                q.strip()
                .lower()
                .replace("!", "!!")
                .replace("%", "!%")
                .replace("_", "!_")
            )
            pattern = "%" + term + "%"
            filters.append(
                """(lower(order_reference) LIKE ? ESCAPE '!'
                    OR lower(json_extract(snapshot_json,'$.payment.paypal_order_id')) LIKE ? ESCAPE '!'
                    OR lower(json_extract(snapshot_json,'$.payment.paypal_capture_id')) LIKE ? ESCAPE '!')"""
            )
            params.extend([pattern] * 3)
        where = " AND ".join(filters)
        with self.store.transaction() as db:
            count = db.execute(
                f"SELECT count(*) FROM commerce_orders WHERE {where}", tuple(params)
            ).fetchone()[0]
            rows = db.execute(
                f"""SELECT id,resolution_id,source,order_reference,revision,snapshot_json,synced_at
                    FROM commerce_orders WHERE {where} ORDER BY synced_at DESC,id DESC LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
            items = []
            for row in rows:
                snapshot = CommerceSnapshot.model_validate_json(row["snapshot_json"])
                items.append(
                    CommerceOrderSummary(
                        **self._receipt(row).model_dump(),
                        payment=snapshot.payment,
                        order_status=snapshot.order_status,
                        line_count=len(snapshot.items),
                    )
                )
            return CommerceOrdersPage(
                items=items, total=count, limit=limit, offset=offset
            )

    def detail(self, order_id, merchant_id):
        with self.store.transaction() as db:
            row = self._order(db, order_id, merchant_id)
            return CommerceOrderDetail(
                **self._receipt(row).model_dump(),
                app=CommerceSnapshot.model_validate_json(row["snapshot_json"]),
            )

    def open_case(self, order_id, merchant_id):
        with self.store.transaction(write=True) as db:
            row = self._order(db, order_id, merchant_id)
            if not row["resolution_id"]:
                snapshot = CommerceSnapshot.model_validate_json(row["snapshot_json"])
                case = self._case_for_order(db, merchant_id, snapshot, row, None)
                self._record_evidence(db, case, snapshot)
                db.execute(
                    "UPDATE commerce_orders SET resolution_id=? WHERE id=? AND merchant_id=?",
                    (case["id"], str(order_id), str(merchant_id)),
                )
                row = self._order(db, order_id, merchant_id)
            return self._receipt(row)

    def report(self, case_id, merchant_id):
        with self.store.transaction() as db:
            case = self.cases._case(db, case_id, merchant_id)
            result = commerce_report(db, case, evidence_summary(db, case))
        if result is None:
            raise StoreError(404, "No connected order on this case")
        return result

    def contact(self, case_id, merchant_id):
        with self.store.transaction() as db:
            case = self.cases._case(db, case_id, merchant_id)
            row = db.execute(
                """SELECT contact_json FROM commerce_orders
                   WHERE resolution_id=? AND merchant_id=?""",
                (case["id"], case["merchant_id"]),
            ).fetchone()
        if not row or not row["contact_json"]:
            raise StoreError(404, "No shared contact on this case")
        return CommerceContact.model_validate_json(row["contact_json"])

    def refresh(self, case_id, merchant_id, client):
        self.report(case_id, merchant_id)
        self.evidence.refresh(case_id, merchant_id, client)
        return self.report(case_id, merchant_id)
