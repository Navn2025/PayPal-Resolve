"""Allowlisted, merchant-reported order evidence and PayPal comparison contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import NonNegativeMoney
from .resolution_models import Input

Source = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
RecordID = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")]
PaymentID = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,64}$")]
Label = Annotated[str, Field(min_length=1, max_length=120)]
PaymentState = Literal[
    "pending", "completed", "partially_refunded", "refunded", "failed"
]


class CommercePayment(Input):
    paypal_order_id: PaymentID | None = None
    paypal_capture_id: PaymentID | None = None
    currency: Literal["USD"] = "USD"
    status: PaymentState | None = None
    captured_amount: NonNegativeMoney | None = None
    refunded_amount: NonNegativeMoney | None = None

    @field_validator("captured_amount", "refunded_amount")
    @classmethod
    def normalize_amount(cls, value):
        return value.quantize(Decimal("0.01")) if value is not None else None


class CommerceItem(Input):
    product_id: RecordID
    name: Label | None = None
    sku: Label | None = None
    quantity: int = Field(strict=True, ge=1, le=1_000_000)
    unit_amount: NonNegativeMoney | None = None

    @field_validator("unit_amount")
    @classmethod
    def normalize_amount(cls, value):
        return value.quantize(Decimal("0.01")) if value is not None else None


class CommerceContact(Input):
    name: Label | None = None
    email: (
        Annotated[str, Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
        | None
    ) = None
    phone: Annotated[str, Field(pattern=r"^\+?[0-9][0-9 ()-]{5,24}$")] | None = None

    @model_validator(mode="after")
    def require_shared_field(self) -> Self:
        if not (self.name or self.email or self.phone):
            raise ValueError("Provide at least one explicitly shared contact field")
        return self


class CommerceSnapshot(Input):
    source: Source
    order_reference: RecordID
    revision: int = Field(strict=True, ge=1, le=2**53 - 1)
    order_status: Label | None = None
    customer_reference: RecordID | None = None
    payment: CommercePayment | None = None
    items: list[CommerceItem] = Field(default_factory=list, max_length=50)


class CommerceRegisterInput(CommerceSnapshot):
    contact: CommerceContact | None = None


class CommerceSyncInput(CommerceRegisterInput):
    case_id: UUID | None = None


class CommerceSyncResult(BaseModel):
    case_id: UUID
    source: Source
    order_reference: RecordID
    revision: int
    synced_at: datetime


class CommerceOrderReceipt(BaseModel):
    id: UUID
    case_id: UUID | None
    source: Source
    order_reference: RecordID
    revision: int
    synced_at: datetime


class CommerceOrderSummary(CommerceOrderReceipt):
    order_status: Label | None
    payment: CommercePayment | None
    line_count: int


class CommerceOrderDetail(CommerceOrderReceipt):
    app: CommerceSnapshot


class CommerceOrdersPage(BaseModel):
    items: list[CommerceOrderSummary]
    total: int
    limit: int
    offset: int


class CommerceFieldCheck(BaseModel):
    field: Literal[
        "paypal_order_id",
        "paypal_capture_id",
        "currency",
        "payment_status",
        "captured_amount",
        "refunded_amount",
    ]
    app_value: str | None
    paypal_value: str | None
    status: Literal["match", "mismatch", "missing_app", "unverified"]
    checked_at: datetime | None = None


class CommerceProviderIssue(BaseModel):
    kind: str
    reference: str | None = None
    status: Literal["missing", "unsupported", "unavailable", "mismatch"]
    detail: str


class CommerceReport(BaseModel):
    case_id: UUID
    app: CommerceSnapshot
    synced_at: datetime
    app_source: Literal["merchant_reported"] = "merchant_reported"
    provider_source: Literal["paypal_sandbox"] = "paypal_sandbox"
    status: Literal["match", "mismatch", "incomplete"]
    checks: list[CommerceFieldCheck]
    last_checked_at: datetime | None = None
    provider_issues: list[CommerceProviderIssue] = Field(default_factory=list)
