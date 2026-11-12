"""Contracts and validation types for resolution assurance."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, Field
from app.schemas.aftercare import OrderLocator, OrderResolution
from app.schemas.customer_portal import PortalMessage
from app.schemas.identity import Input


class TraceInput(Input):
    request_id: UUID
    refund_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    reference_type: Literal["ARN", "STAN", "RRN", "bank_reference"]
    reference: str = Field(pattern=r"^[A-Za-z0-9 -]{4,100}$")
    stage: Literal[
        "initiated", "processor_pending", "sent_to_bank", "bank_processing", "failed"
    ]
    expected_by: AwareDatetime | None = None
    note: str = Field(min_length=1, max_length=1000)


class TraceView(BaseModel):
    refund_id: str
    reference_type: str
    reference: str
    stage: str
    expected_by: datetime | None
    source: Literal["merchant_recorded"]
    recorded_at: datetime


class RefundJourney(BaseModel):
    stage: Literal[
        "not_promised",
        "needs_verification",
        "promised",
        "processor_pending",
        "sent_to_original_method",
        "buyer_reports_received",
        "needs_review",
    ]
    explanation: str
    last_checked_at: datetime | None
    buyer_reported_received_at: datetime | None
    bank_receipt_verified: Literal[False] = False
    resolution: OrderResolution
    traces: list[TraceView]
    authorizes_payment: Literal[False] = False


class ContextView(BaseModel):
    resolution: OrderResolution
    issues: list[dict]
    messages: list[PortalMessage]
    next_before_sequence: int | None
    has_more_messages: bool
    identity_source: Literal["merchant_app_or_private_buyer_link"] = (
        "merchant_app_or_private_buyer_link"
    )


class LookupIssue(OrderLocator):
    request_id: UUID
