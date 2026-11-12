"""Private merchant contracts for the Evidence SDK."""

from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from app.schemas.commerce import CommerceReport
from app.schemas.payments import Money, NonNegativeMoney
from app.schemas.resolution import (
    Input,
    ResolutionBundle,
    ResolutionCreate,
    ResolutionView,
    Short,
)


RecordKind = Literal[
    "order", "paypal_order", "paypal_capture", "paypal_refund", "support_ticket"
]
PayPalKind = Literal["paypal_order", "paypal_capture", "paypal_refund"]
EvidenceKind = Literal["refund_approved", "return_confirmed", "support_note"]


class EvidenceCaseUpsert(ResolutionCreate):
    external_reference: Short


class EvidenceRecordInput(Input):
    kind: RecordKind
    reference: Short
    source: Short = "merchant_app"

    @model_validator(mode="after")
    def check_paypal_id(self) -> Self:
        if self.kind.startswith("paypal_") and not re.fullmatch(
            r"[A-Za-z0-9]{1,64}", self.reference
        ):
            raise ValueError("Use the PayPal record ID, not a URL")
        return self


class LinkedEvidenceRecord(EvidenceRecordInput):
    id: UUID
    linked_at: AwareDatetime
    verification: Literal["association_only"] = "association_only"


class EvidenceInput(Input):
    source: Short
    source_event_id: Short
    evidence_type: EvidenceKind
    occurred_at: AwareDatetime
    summary: str = Field(min_length=1, max_length=500)
    amount: Money | None = None
    currency: Literal["USD"] | None = None

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def check_money(self) -> Self:
        if self.evidence_type == "refund_approved":
            if self.amount is None or self.currency is None:
                raise ValueError("A refund approval record needs amount and currency")
            self.amount = self.amount.quantize(Decimal("0.01"))
        elif self.amount is not None or self.currency is not None:
            raise ValueError(
                "Amount and currency are only supported on refund approval records"
            )
        return self


class EvidenceReceipt(EvidenceInput):
    id: UUID
    recorded_at: AwareDatetime
    verification: Literal["merchant_reported"] = "merchant_reported"


class EvidenceIssue(BaseModel):
    kind: str
    reference: str | None = None
    status: Literal["missing", "unsupported", "unavailable", "mismatch"]
    detail: str


class PayPalEvidenceFact(BaseModel):
    kind: PayPalKind
    reference: str
    status: str
    amount: Money | None = None
    currency: Literal["USD"] | None = None
    capture_id: str | None = None
    provider: Literal["paypal"] = "paypal"
    environment: Literal["sandbox"] = "sandbox"
    verification: Literal["provider_confirmed"] = "provider_confirmed"
    checked_at: AwareDatetime

    @field_validator("amount")
    @classmethod
    def canonical_cents(cls, value):
        return value.quantize(Decimal("0.01")) if value is not None else None


class EvidenceRefreshResult(BaseModel):
    checked_at: AwareDatetime
    verified: list[PayPalEvidenceFact]
    issues: list[EvidenceIssue]
    order_history_verified: bool = False


class EvidenceSummary(BaseModel):
    last_check_started_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_verified_at: datetime | None = None
    order_history_verified: bool = False
    verified: list[PayPalEvidenceFact] = Field(default_factory=list)
    issues: list[EvidenceIssue] = Field(default_factory=list)
    last_merchant_approval: EvidenceReceipt | None = None
    captured_amount: Money | None = None
    provider_completed_amount: NonNegativeMoney = Decimal("0.00")
    provider_pending_amount: NonNegativeMoney = Decimal("0.00")
    refund_status: Literal[
        "unconfirmed", "pending", "partially_refunded", "refunded"
    ] = "unconfirmed"
    currency: Literal["USD"] = "USD"


class EvidenceCaseView(ResolutionView):
    external_reference: str | None = None
    evidence_summary: EvidenceSummary | None = None


class EvidenceBundle(ResolutionBundle):
    case: EvidenceCaseView
    linked_records: list[LinkedEvidenceRecord]
    commerce: CommerceReport | None = None
