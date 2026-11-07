"""Deterministic calculations over local development records; no payment calls."""

from decimal import Decimal
import hashlib
import json
from uuid import UUID

from .models import (
    CaseResponse,
    ConditionCheck,
    PaymentReference,
    ReconciliationResponse,
    RefundRecord,
    PayPalCaptureVerification,
    PayPalRefundVerification,
)


ZERO = Decimal("0.00")


def validate_refund_record(
    payment: PaymentReference,
    refund: RefundRecord,
    other_refunds: list[RefundRecord],
) -> None:
    """Validate a new or updated record against the remaining recorded balance."""
    if refund.capture_id != payment.capture_id:
        raise ValueError("Refund must reference the case's payment capture")
    if refund.currency != payment.currency:
        raise ValueError("Refund and payment currencies must match")
    if refund.amount > payment.captured_amount:
        raise ValueError("Refund amount cannot exceed the captured amount")

    reserved = sum(
        (
            record.amount
            for record in other_refunds
            if record.capture_id == payment.capture_id
            and record.status in ("completed", "pending")
        ),
        ZERO,
    )
    if refund.status in ("completed", "pending"):
        reserved += refund.amount
    if reserved > payment.captured_amount:
        raise ValueError("Completed and pending refunds cannot exceed the capture")


def reconcile_case(
    case: CaseResponse,
    refund_records: list[RefundRecord],
    condition_check: ConditionCheck | None = None,
    capture_verification: PayPalCaptureVerification | None = None,
    active_refund_execution_id: UUID | None = None,
    refund_verifications: list[PayPalRefundVerification] | None = None,
    failed_refund_execution_id: UUID | None = None,
) -> ReconciliationResponse:
    records = [
        refund
        for refund in refund_records
        if refund.capture_id == case.payment.capture_id
    ]
    totals = {
        status: sum(
            (record.amount for record in records if record.status == status), ZERO
        )
        for status in ("completed", "pending", "failed")
    }
    completed, pending = totals["completed"], totals["pending"]
    remaining = case.payment.captured_amount - completed - pending
    commitment = case.commitment
    outstanding = max(commitment.amount - completed, ZERO) if commitment else None
    uncovered = max(outstanding - pending, ZERO) if outstanding is not None else None
    recommendation = ZERO

    if active_refund_execution_id is not None:
        status, action = "execution_pending", "monitor_refund_execution"
    elif commitment is None:
        status, action = "no_commitment", "review_complaint"
    elif commitment.status != "accepted":
        status, action = "awaiting_acceptance", "confirm_agreement"
    elif pending > ZERO:
        status, action = "refund_pending", "monitor_pending_refund"
    elif outstanding == ZERO:
        status, action = "fulfilled", "none"
    elif failed_refund_execution_id is not None:
        status, action = "execution_failed", "review_failed_execution"
    elif commitment.condition is not None and (
        condition_check is None or condition_check.status != "met"
    ):
        status, action = "awaiting_condition", "verify_condition"
    else:
        status, action = "refund_required", "request_merchant_approval"
        recommendation = min(outstanding, remaining)

    fingerprint_data = {
        "case": case.model_dump(mode="json"),
        "refunds": [
            record.model_dump(mode="json")
            for record in sorted(records, key=lambda record: record.refund_id)
        ],
        "condition_check": (
            condition_check.model_dump(mode="json") if condition_check else None
        ),
    }
    if capture_verification is not None:
        fingerprint_data["capture_verification"] = capture_verification.model_dump(
            mode="json"
        )
    if active_refund_execution_id is not None:
        fingerprint_data["active_refund_execution_id"] = str(active_refund_execution_id)
    if refund_verifications:
        fingerprint_data["refund_verifications"] = [
            item.model_dump(mode="json")
            for item in sorted(refund_verifications, key=lambda item: item.refund_id)
        ]
    if failed_refund_execution_id is not None:
        fingerprint_data["failed_refund_execution_id"] = str(failed_refund_execution_id)
    return ReconciliationResponse(
        case_id=case.id,
        capture_verification=capture_verification,
        active_refund_execution_id=active_refund_execution_id,
        failed_refund_execution_id=failed_refund_execution_id,
        refund_verifications=refund_verifications or [],
        state_fingerprint=hashlib.sha256(
            json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        currency=case.payment.currency,
        captured_amount=case.payment.captured_amount,
        committed_amount=commitment.amount if commitment else None,
        completed_refund_amount=completed,
        pending_refund_amount=pending,
        failed_refund_amount=totals["failed"],
        outstanding_commitment_amount=outstanding,
        uncovered_commitment_amount=uncovered,
        remaining_refundable_amount=remaining,
        recommended_refund_amount=recommendation,
        condition_check=condition_check,
        status=status,
        next_action=action,
    )
