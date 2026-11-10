"""Reason-specific document requirements; a present document is not a winning dispute."""

from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from pydantic import Field

from .platform_identity import Input, audit
from .errors import StoreError


class DisputeDocument(Input):
    request_id: UUID
    requirement: Literal[
        "original_delivery",
        "product_description",
        "return_policy",
        "buyer_authorization",
        "service_fulfilled",
        "credit_agreement",
        "cancellation",
        "duplicate_charge",
        "other",
    ]
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=10)
    note: str = Field(min_length=1, max_length=2000)


def documents(db, merchant, case_id):
    return [
        json.loads(r[0])
        for r in db.execute(
            "SELECT data_json FROM resolution_events WHERE merchant_id=? AND resolution_id=? AND event_type='merchant_evidence' AND json_extract(data_json,'$.evidence_type')='dispute_document' ORDER BY sequence",
            (str(merchant), str(case_id)),
        )
    ]


def checklist(db, merchant, case, view, reason, imported=False):
    docs = documents(db, merchant, case["id"])
    groups = {d["requirement"] for d in docs if d.get("evidence_ids") or d.get("note")}
    types = {
        "item_not_received": [
            (
                "Original shipment/delivery or service fulfillment",
                bool(groups & {"original_delivery", "service_fulfilled"}),
                "PROOF_OF_FULFILLMENT",
            )
        ],
        "not_as_described": [
            (
                "Product description and condition evidence",
                "product_description" in groups,
                "OTHER",
            ),
            ("Return policy and instructions", "return_policy" in groups, "OTHER"),
        ],
        "unauthorized": [
            (
                "Buyer authorization or fulfillment evidence",
                bool(
                    groups
                    & {"buyer_authorization", "original_delivery", "service_fulfilled"}
                ),
                "OTHER / PROOF_OF_FULFILLMENT",
            )
        ],
        "credit_not_processed": [
            ("Credit/refund agreement", "credit_agreement" in groups, "OTHER")
        ],
        "duplicate_charge": [
            (
                "Both transaction references and duplicate-charge explanation",
                "duplicate_charge" in groups,
                "OTHER",
            )
        ],
        "canceled_recurring": [
            (
                "Cancellation request and effective-date evidence",
                "cancellation" in groups,
                "OTHER",
            )
        ],
        "other": [("Reason-specific supporting documents", bool(groups), "OTHER")],
    }
    result = [
        {
            "item": "Payment linked",
            "present": bool(case["refund_case_id"]),
            "evidence_type": "TRANSACTION_REFERENCE",
            "source": "linked_record",
        },
        {
            "item": "Conversation available",
            "present": imported
            or bool(
                db.execute(
                    "SELECT 1 FROM customer_portal_messages WHERE resolution_id=?",
                    (case["id"],),
                ).fetchone()
            ),
            "evidence_type": "OTHER",
            "source": "recorded_conversation",
        },
    ]
    for item, present, kind in types[reason]:
        result.append(
            {
                "item": item,
                "present": present,
                "evidence_type": kind,
                "source": "merchant_recorded_document",
            }
        )
    proof = False
    if case["refund_case_id"]:
        row = db.execute(
            "SELECT capture_id FROM cases WHERE id=? AND merchant_id=?",
            (case["refund_case_id"], str(merchant)),
        ).fetchone()
        proof = bool(
            db.execute(
                "SELECT 1 FROM paypal_refund_verifications WHERE merchant_id=? AND capture_id=? AND provider_status='COMPLETED'",
                (str(merchant), row[0]),
            ).fetchone()
        )
    result.append(
        {
            "item": "Completed provider refund reference (where applicable)",
            "present": proof,
            "evidence_type": "PROOF_OF_REFUND",
            "source": "provider_observation",
        }
    )
    return result


def record_document(store, merchant, actor, case_id, payload):
    from .evidence_workspace import EvidenceWorkspace

    evidence = EvidenceWorkspace(store)
    with store.transaction(write=True) as db:
        case = evidence.workspace._case(db, case_id, merchant)
        for identifier in payload.evidence_ids:
            if not db.execute(
                "SELECT 1 FROM customer_evidence WHERE id=? AND merchant_id=? AND resolution_id=?",
                (str(identifier), str(merchant), str(case_id)),
            ).fetchone():
                raise StoreError(404, "Select an evidence file owned by this case")
        raw = payload.model_dump_json()
        data = {
            "evidence_type": "dispute_document",
            **payload.model_dump(mode="json"),
            "source_label": "merchant_recorded",
        }
        identifier, _ = evidence._event(
            db,
            case,
            "merchant",
            "dispute_document",
            str(payload.request_id),
            sha256(raw.encode()).hexdigest(),
            data,
        )
        audit(db, merchant, actor, "dispute_document_recorded", identifier)
        return {
            "id": identifier,
            "source": "merchant_recorded",
            "authorizes_payment": False,
        }
