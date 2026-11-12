"""Contracts and validation types for return assurance."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, Field
from app.schemas.commerce import RecordID
from app.schemas.payments import NonNegativeMoney
from app.schemas.identity import Input


class ReturnPolicy(Input):
    enabled: bool = False
    window_days: int = Field(strict=True, ge=1, le=365)
    restocking_fee: NonNegativeMoney = Decimal("0.00")
    shipping_paid_by: Literal["merchant", "buyer"] = "merchant"
    inspection_required: bool = True
    photos_required: bool = False
    excluded_products: list[RecordID] = Field(default_factory=list, max_length=50)
    instructions: str = Field(
        default="Contact the merchant for return instructions before shipping.",
        min_length=1,
        max_length=3000,
    )


class PolicyUpdate(ReturnPolicy):
    expected_revision: int = Field(ge=0)


class PolicyView(BaseModel):
    revision: int
    policy: ReturnPolicy


class GuideInput(Input):
    expected_revision: int = Field(ge=0)
    instructions: str = Field(min_length=1, max_length=3000)
    return_address: str = Field(default="", max_length=1000)
    shipping_paid_by: Literal["merchant", "buyer"] = "merchant"


class InspectionInput(Input):
    expected_revision: int = Field(ge=1)
    request_id: UUID
    finding: Literal["clear", "needs_review", "reject"]
    quantities_match: bool
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=10)
    override_policy: bool = False
    note: str = Field(min_length=1, max_length=2000)


class PublicReturnPolicy(BaseModel):
    policy_enabled: bool
    revision: int
    window_days: int | None
    shipping_paid_by: Literal["merchant", "buyer"] | None
    restocking_fee: NonNegativeMoney | None
    currency: Literal["USD"] = "USD"
    inspection_required: bool
    evidence_required: bool
    instructions: str


class EligibilityView(BaseModel):
    policy_enabled: bool = False
    decision: Literal["eligible", "needs_review"]
    policy_revision: int
    delivered_at: AwareDatetime | None = None
    flags: list[str]
    shipping_paid_by: Literal["merchant", "buyer"]
    restocking_fee: NonNegativeMoney | None
    currency: Literal["USD"] = "USD"
    instructions: str
    authorizes_refund: Literal[False] = False


class LabelMetadata(BaseModel):
    id: UUID
    filename: str
    sha256: str
    created_at: datetime


class ReturnGuideView(BaseModel):
    policy_enabled: bool
    revision: int
    instructions: str
    return_address: str
    shipping_paid_by: Literal["merchant", "buyer"]
    restocking_fee: NonNegativeMoney | None
    currency: Literal["USD"]
    labels: list[LabelMetadata]
    eligibility: EligibilityView | None
    inspection_status: Literal["unknown", "clear", "needs_review", "reject"]
    policy_revision: int
    save_label_for_later: Literal[True]


class ReturnLabelFile(BaseModel):
    filename: str
    content_type: Literal["application/pdf"]
    content_base64: str
