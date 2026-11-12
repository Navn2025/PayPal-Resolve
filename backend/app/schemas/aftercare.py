"""Contracts and validation types for aftercare."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field
from app.schemas.commerce import RecordID, Source
from app.schemas.customer_portal import PublicPromise
from app.schemas.customer_progress import CustomerNextStep
from app.schemas.identity import Input


class SupportKeyInput(Input):
    source: Source


class SupportKeyReceipt(BaseModel):
    key_id: UUID
    api_key: str
    source: str
    capabilities: list[Literal["order_sync", "customer_support"]]


class OrderLocator(Input):
    source: Source
    order_reference: RecordID


class IssueInput(OrderLocator):
    request_id: UUID
    reason: Literal[
        "item_not_received",
        "damaged_item",
        "wrong_item",
        "refund_not_received",
        "other",
    ]
    message: str = Field(min_length=1, max_length=2000)
    requested_resolution: Literal["refund", "replacement", "return", "help"] = "help"


class IssueReceipt(BaseModel):
    issue_id: UUID
    case_id: UUID
    order_reference: str
    created_at: datetime
    status: Literal["received"] = "received"
    authorizes_payment: Literal[False] = False


class SupportRefund(BaseModel):
    promised_amount: Decimal | None
    completed_amount: Decimal | None
    pending_amount: Decimal | None
    remaining_amount: Decimal | None
    currency: Literal["USD"] = "USD"
    environment: Literal["sandbox"] = "sandbox"
    verification: Literal["current", "unverified"]
    last_checked_at: datetime | None


class OrderResolution(BaseModel):
    order_reference: str
    case_id: UUID | None
    stage: Literal[
        "no_issue",
        "under_review",
        "action_required",
        "pending",
        "resolved",
        "needs_review",
    ]
    next_action: Literal["report_issue", "wait", "open_portal", "review_offer", "none"]
    next_step: CustomerNextStep
    promises: list[PublicPromise]
    refund: SupportRefund | None
    issue_count: int
    authorizes_payment: Literal[False] = False


class SupportRequestView(BaseModel):
    issue_id: UUID
    source: str
    reason: str
    requested_resolution: str
    message: str
    created_at: datetime


class SupportRequestPage(BaseModel):
    items: list[SupportRequestView]
