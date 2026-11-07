from decimal import Decimal
from datetime import datetime, timezone
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


Money = Annotated[
    Decimal,
    Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False),
]

NonNegativeMoney = Annotated[
    Decimal,
    Field(ge=0, decimal_places=2, allow_inf_nan=False),
]

RefundStatus = Literal["pending", "completed", "failed"]


class PaymentReference(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    capture_id: str = Field(min_length=1, max_length=100)
    captured_amount: Money
    currency: Literal["USD"] = "USD"


class RefundCommitment(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    amount: Money
    currency: Literal["USD"] = "USD"
    source_message: str = Field(min_length=1, max_length=5000)
    condition: str | None = Field(default=None, min_length=1)
    status: Literal["proposed", "accepted"] = "proposed"


class CaseCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    order_id: str = Field(min_length=1, max_length=100)
    complaint: str = Field(min_length=1, max_length=5000)
    payment: PaymentReference
    commitment: RefundCommitment | None = None

    @model_validator(mode="after")
    def validate_commitment(self) -> Self:
        if self.commitment is not None:
            if self.commitment.currency != self.payment.currency:
                raise ValueError("Commitment and payment currencies must match")

            if self.commitment.amount > self.payment.captured_amount:
                raise ValueError("Refund commitment cannot exceed the captured amount")

        return self


class CaseResponse(CaseCreate):
    id: UUID
    merchant_id: UUID
    status: Literal["open"] = "open"


class CasePage(BaseModel):
    items: list[CaseResponse]
    total: int
    limit: int
    offset: int


class CommitmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    commitment: RefundCommitment


class CaseTimelineEntry(BaseModel):
    id: str
    source: Literal[
        "case",
        "approval",
        "execution",
        "capture_verification",
        "refund_verification",
        "condition_check",
    ]
    case_id: UUID
    capture_id: str
    event_type: str
    actor_merchant_id: UUID | None
    actor_kind: Literal["merchant", "system", "unknown"]
    occurred_at: datetime
    data: dict


class CaseTimelinePage(BaseModel):
    items: list[CaseTimelineEntry]
    total: int
    limit: int
    offset: int


class RefundRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    refund_id: str = Field(min_length=1, max_length=100)
    capture_id: str = Field(min_length=1, max_length=100)
    amount: Money
    currency: Literal["USD"] = "USD"
    status: RefundStatus


class RefundStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RefundStatus


class ConditionCheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: Literal["met", "not_met"]
    evidence_note: str = Field(min_length=1, max_length=5000)


class ConditionCheck(ConditionCheckCreate):
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by_merchant_id: UUID | None = None


class MerchantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)


class MerchantIdentity(MerchantCreate):
    id: UUID
    created_at: datetime


PayPalCaptureStatus = Literal[
    "COMPLETED", "DECLINED", "PARTIALLY_REFUNDED", "PENDING", "REFUNDED", "FAILED"
]


class PayPalCaptureVerification(BaseModel):
    id: UUID
    merchant_id: UUID
    case_id: UUID
    capture_id: str
    paypal_merchant_id: str
    captured_amount: Money
    currency: Literal["USD"]
    capture_status: PayPalCaptureStatus
    checked_at: datetime
    environment: Literal["sandbox"] = "sandbox"
    capture_details_verified: Literal[True] = True
    refund_history_verified: Literal[False] = False
    refund_eligibility_verified: Literal[False] = False


class ReconciliationResponse(BaseModel):
    case_id: UUID
    capture_verification: PayPalCaptureVerification | None = None
    refund_verifications: list["PayPalRefundVerification"] = Field(default_factory=list)
    active_refund_execution_id: UUID | None = None
    failed_refund_execution_id: UUID | None = None
    state_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    currency: Literal["USD"]
    captured_amount: NonNegativeMoney
    committed_amount: NonNegativeMoney | None
    completed_refund_amount: NonNegativeMoney
    pending_refund_amount: NonNegativeMoney
    failed_refund_amount: NonNegativeMoney
    outstanding_commitment_amount: NonNegativeMoney | None
    uncovered_commitment_amount: NonNegativeMoney | None
    remaining_refundable_amount: NonNegativeMoney
    recommended_refund_amount: NonNegativeMoney
    condition_check: ConditionCheck | None
    status: Literal[
        "no_commitment",
        "awaiting_acceptance",
        "refund_pending",
        "fulfilled",
        "awaiting_condition",
        "refund_required",
        "execution_pending",
        "execution_failed",
    ]
    next_action: Literal[
        "review_complaint",
        "confirm_agreement",
        "monitor_pending_refund",
        "none",
        "verify_condition",
        "request_merchant_approval",
        "monitor_refund_execution",
        "review_failed_execution",
    ]
    verified_with_paypal: Literal[False] = False


class RefundApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID
    capture_id: str = Field(min_length=1, max_length=100)
    amount: Money
    currency: Literal["USD"] = "USD"
    state_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision_note: str = Field(min_length=1, max_length=5000)


class RefundApprovalRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=5000)


ApprovalStatus = Literal["approved", "revoked", "expired", "invalidated"]


class RefundApproval(BaseModel):
    id: UUID
    merchant_id: UUID
    case_id: UUID
    request_id: UUID
    capture_id: str
    amount: Money
    currency: Literal["USD"]
    state_fingerprint: str
    decision_note: str
    status: ApprovalStatus
    approved_at: datetime
    expires_at: datetime
    updated_at: datetime
    status_reason: str
    basis: ReconciliationResponse
    verified_with_paypal: Literal[False] = False


class RefundApprovalEvent(BaseModel):
    sequence: int
    approval_id: UUID
    event_type: ApprovalStatus
    actor_merchant_id: UUID | None
    note: str
    recorded_at: datetime


ProviderRefundStatus = Literal["CANCELLED", "FAILED", "PENDING", "COMPLETED"]
ExecutionStatus = Literal[
    "reserved", "submitting", "unknown", "pending", "completed", "failed"
]


class PayPalRefundVerificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    refund_id: str = Field(pattern=r"^[A-Za-z0-9]{1,64}$")


class PayPalRefundVerification(BaseModel):
    id: UUID
    merchant_id: UUID
    case_id: UUID
    capture_id: str
    refund_id: str
    amount: Money
    currency: Literal["USD"]
    provider_status: ProviderRefundStatus
    checked_at: datetime
    execution_id: UUID | None = None
    environment: Literal["sandbox"] = "sandbox"
    refund_details_verified: Literal[True] = True
    refund_history_verified: Literal[False] = False


class RefundExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    approval_id: UUID


class ExecutionCaptureCheck(BaseModel):
    capture_id: str
    captured_amount: Money
    currency: Literal["USD"]
    paypal_merchant_id: str
    capture_status: PayPalCaptureStatus
    checked_at: datetime


class RefundExecution(BaseModel):
    id: UUID
    merchant_id: UUID
    case_id: UUID
    capture_id: str
    approval_id: UUID
    request_id: UUID
    provider_request_id: UUID
    amount: Money
    currency: Literal["USD"]
    status: ExecutionStatus
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    approval_snapshot: RefundApproval
    final_capture_check: ExecutionCaptureCheck
    provider_refund: PayPalRefundVerification | None = None
    environment: Literal["sandbox"] = "sandbox"
    full_refund_only: Literal[True] = True


class RefundExecutionEvent(BaseModel):
    sequence: int
    execution_id: UUID
    status: ExecutionStatus
    note: str
    recorded_at: datetime
    snapshot: dict | None = None


ReconciliationResponse.model_rebuild()
RefundApproval.model_rebuild()
