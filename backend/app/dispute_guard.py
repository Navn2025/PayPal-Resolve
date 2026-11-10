"""Versioned capture-wide dispute holds. Recorded provider names are not provider verification."""

import json
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from pydantic import Field

from .platform_identity import Input, audit, now
from .errors import StoreError


class DisputeEvent(Input):
    provider: Literal["paypal", "stripe", "bank", "merchant"]
    reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    event_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    version: int = Field(strict=True, ge=1)
    state: Literal["open", "under_review", "resolved_no_refund", "resolved_refunded"]
    note: str = Field(min_length=1, max_length=2000)


def held(db, merchant, capture):
    if db.execute(
        "SELECT 1 FROM assurance_disputes WHERE merchant_id=? AND capture_id=? AND state!='resolved_no_refund' LIMIT 1",
        (str(merchant), capture),
    ).fetchone():
        return True
    known = db.execute(
        "SELECT p.promise_json,p.id,p.revision FROM resolution_promises p JOIN resolution_cases r ON r.id=p.resolution_id JOIN cases c ON c.id=r.refund_case_id WHERE p.merchant_id=? AND c.capture_id=? AND p.kind='dispute_handoff'",
        (str(merchant), capture),
    ).fetchall()
    for row in known:
        reference = json.loads(row[0])["target"]["paypal_dispute_id"]
        proof = db.execute(
            "SELECT data_json FROM resolution_events WHERE promise_id=? AND revision=? AND event_type='provider_observation' AND source='provider_confirmed' ORDER BY sequence DESC LIMIT 1",
            (row["id"], row["revision"]),
        ).fetchone()
        if proof:
            observations = json.loads(proof[0]).get("proofs", [])
            if not observations or any(
                not isinstance(item, dict) or item.get("status") != "RESOLVED"
                for item in observations
            ):
                return True

        if not db.execute(
            "SELECT 1 FROM assurance_disputes WHERE merchant_id=? AND capture_id=? AND provider='paypal' AND reference=? AND state='resolved_no_refund'",
            (str(merchant), capture, reference),
        ).fetchone():
            return True
    return False


class Disputes:
    def __init__(self, store):
        self.store = store

    def list(self, merchant, case_id):
        with self.store.transaction() as db:
            case = self.store._require_case(db, case_id, merchant)
            return {
                "capture_held": held(db, merchant, case.payment.capture_id),
                "items": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,provider,reference,version,state,data_json,updated_at FROM assurance_disputes WHERE merchant_id=? AND capture_id=? ORDER BY updated_at DESC",
                        (str(merchant), case.payment.capture_id),
                    )
                ],
            }

    def record(self, merchant, actor, case_id, payload):
        encoded = payload.model_dump_json()
        fingerprint = sha256(encoded.encode()).hexdigest()
        with self.store.transaction(write=True) as db:
            case = self.store._require_case(db, case_id, merchant)
            prior = db.execute(
                "SELECT * FROM assurance_dispute_events WHERE merchant_id=? AND provider=? AND event_id=?",
                (str(merchant), payload.provider, payload.event_id),
            ).fetchone()
            if prior:
                if prior["body_hash"] != fingerprint:
                    raise StoreError(
                        409, "Dispute event ID already has different content"
                    )
                return {
                    "accepted": True,
                    "outcome": prior["outcome"],
                    "duplicate": True,
                }
            row = db.execute(
                "SELECT * FROM assurance_disputes WHERE merchant_id=? AND provider=? AND reference=?",
                (str(merchant), payload.provider, payload.reference),
            ).fetchone()
            if row and row["capture_id"] != case.payment.capture_id:
                raise StoreError(409, "This dispute is bound to another capture")
            outcome = "applied"
            if row and payload.version < row["version"]:
                outcome = "stale_ignored"
            elif row and payload.version == row["version"]:
                if {
                    k: v
                    for k, v in json.loads(row["data_json"]).items()
                    if k != "event_id"
                } != {
                    k: v
                    for k, v in {
                        **payload.model_dump(mode="json"),
                        "source": "merchant_recorded",
                    }.items()
                    if k != "event_id"
                }:
                    raise StoreError(409, "Dispute version already has different terms")
                outcome = "duplicate_version"
            elif (
                row
                and row["state"] == "resolved_refunded"
                and payload.state != "resolved_refunded"
            ):
                raise StoreError(
                    409,
                    "Reimbursed dispute remains blocked until payment reconciliation; do not erase reimbursement history",
                )
            if outcome == "applied":
                identifier = row["id"] if row else str(uuid4())
                db.execute(
                    "INSERT INTO assurance_disputes VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,state=excluded.state,data_json=excluded.data_json,updated_at=excluded.updated_at",
                    (
                        identifier,
                        str(merchant),
                        case.payment.capture_id,
                        payload.provider,
                        payload.reference,
                        payload.version,
                        payload.state,
                        json.dumps(
                            {
                                **payload.model_dump(mode="json"),
                                "source": "merchant_recorded",
                            }
                        ),
                        now(),
                    ),
                )
                from .approvals import invalidate_approvals

                invalidate_approvals(
                    db,
                    merchant,
                    case.payment.capture_id,
                    "Dispute state changed; reconcile before another refund",
                )
            db.execute(
                "INSERT INTO assurance_dispute_events VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    str(merchant),
                    payload.provider,
                    payload.event_id,
                    fingerprint,
                    payload.reference,
                    payload.version,
                    outcome,
                    now(),
                ),
            )
            audit(
                db,
                merchant,
                actor,
                "dispute_event_recorded",
                case_id,
                outcome=outcome,
                state=payload.state,
                version=payload.version,
            )
            return {"accepted": True, "outcome": outcome, "duplicate": False}
