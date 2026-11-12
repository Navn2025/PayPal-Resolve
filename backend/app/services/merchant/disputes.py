"""Disputes workflow, preserving existing transaction boundaries."""

from hashlib import sha256
import json
from uuid import uuid4
from app.services.customer.portal import CustomerPortal
from app.core.exceptions import StoreError
from app.services.merchant.identity import audit, now
from app.services.merchant.operation_values import _json


class DisputePackages:
    def __init__(self, store, workspace):
        self.store = store
        self.workspace = workspace

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
            "assurance": DisputePackages._assurance_sources(db, merchant, case_id),
        }

    def build_package(self, merchant, actor, case_id, payload):
        from app.services.resolution.evidence import EvidenceWorkspace

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
            from app.services.assurance.dispute_evidence import (
                checklist as required_evidence,
                documents,
            )

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
