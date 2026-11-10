"""Reusable response contracts for merchant operations and buyer decisions."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .ai_extraction import ExtractionResult
from .commerce_models import CommerceItem
from .models import MerchantIdentity, NonNegativeMoney
from .platform_operations import ReturnItem, Shipment
from .resolution_models import Target

Role = Literal["owner", "manager", "finance", "agent", "viewer"]
SummaryAmount = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=2)]


class StaffView(BaseModel):
    id: UUID
    merchant_id: UUID
    email: str
    name: str
    role: Role
    active: int
    created_at: datetime


class StaffPage(BaseModel):
    items: list[StaffView]


class AccountSession(BaseModel):
    token: str = Field(repr=False)
    merchant: MerchantIdentity
    method: Literal["password"]
    expires_at: datetime
    paypal_linked: bool
    staff: StaffView


class PlatformIdentity(BaseModel):
    merchant: MerchantIdentity
    actor_id: str
    role: Role


class Invitation(BaseModel):
    id: UUID
    token: str = Field(repr=False)
    expires_at: datetime


class ConnectionView(BaseModel):
    provider: Literal["paypal", "zendesk", "shopify", "easypost"]
    config: dict[str, str | bool]
    enabled: bool
    revision: int
    check_status: str
    checked_at: datetime | None
    updated_at: datetime
    credentials_stored: bool


class ConnectionPage(BaseModel):
    items: list[ConnectionView]
    encryption_configured: bool


class TicketMessage(BaseModel):
    source_id: str
    sender: Literal["buyer", "merchant"]
    body: str
    public: int
    sent_at: datetime


class TicketView(BaseModel):
    id: UUID
    merchant_id: UUID
    provider: Literal["zendesk"]
    ticket_id: str
    case_id: UUID | None
    order_reference: str | None
    title: str
    state: Literal["matched", "needs_match"]
    suggestions: ExtractionResult | None
    created_at: datetime
    updated_at: datetime


class TicketDetail(TicketView):
    messages: list[TicketMessage]


class TicketPage(BaseModel):
    items: list[TicketView]


class OfferOption(BaseModel):
    id: UUID
    promise_id: UUID
    promise_revision: int
    promise: str
    target: Target
    requires: list[UUID]
    due_at: datetime | None


class OfferView(BaseModel):
    id: UUID
    case_id: UUID
    revision: int
    choices: list[OfferOption]
    expires_at: datetime
    status: Literal["published", "accepted", "declined", "superseded"]
    selected_choice: UUID | None
    decision_at: datetime | None
    decision_actor: str | None
    created_at: datetime


class OfferPage(BaseModel):
    items: list[OfferView]


class BuyerChoice(BaseModel):
    id: UUID
    promise: str
    kind: str
    amount: NonNegativeMoney | None
    currency: str | None
    due_at: datetime | None
    conditions_required: bool


class BuyerOffer(BaseModel):
    id: UUID
    revision: int
    status: str
    stale: bool
    expires_at: datetime
    selected_choice: UUID | None
    decision_at: datetime | None
    choices: list[BuyerChoice]


class BuyerOfferPage(BaseModel):
    items: list[BuyerOffer]


class DecisionReceipt(BaseModel):
    status: Literal["accepted", "declined"]
    decision_at: datetime
    authorizes_payment: Literal[False]


class ReturnView(BaseModel):
    id: UUID
    case_id: UUID
    order_id: UUID
    request_id: UUID
    revision: int
    status: Literal[
        "requested",
        "approved",
        "rejected",
        "in_transit",
        "received",
        "inspection_passed",
        "replacement_shipped",
        "completed",
    ]
    items: list[ReturnItem]
    reason: str
    tracking: Shipment | None
    replacement: Shipment | None
    created_at: datetime
    updated_at: datetime


class ReturnableItem(CommerceItem):
    available_quantity: int


class ReturnableOrder(BaseModel):
    id: UUID
    order_reference: str
    items: list[ReturnableItem]


class ReturnCatalog(BaseModel):
    orders: list[ReturnableOrder]
    items: list[ReturnView]


class AlertView(BaseModel):
    id: UUID
    case_id: UUID
    promise_id: UUID
    promise_revision: int
    day: date
    state: str
    assignee: str | None
    reason: str
    customer_draft: str
    created_at: datetime
    resolved_at: datetime | None


class AlertPage(BaseModel):
    items: list[AlertView]


class LedgerSummary(BaseModel):
    currency: Literal["USD"]
    source: Literal["recorded_ledger_not_independent_provider_verification"]
    shared_capture_count: int
    promised: SummaryAmount
    completed: SummaryAmount
    pending: SummaryAmount
    outstanding_excluding_pending: SummaryAmount


class ResolutionTime(BaseModel):
    sample_count: int
    average_hours: float | None


class Dashboard(BaseModel):
    case_count: int
    outcomes: dict[str, int]
    remedies: dict[str, int]
    complaint_reasons: dict[str, int]
    overdue_promises: int
    awaiting_evidence: int
    financial: LedgerSummary
    resolution_time: ResolutionTime


class EvidenceChecklist(BaseModel):
    item: str
    present: bool
    evidence_type: str = "OTHER"
    source: str = "unspecified"


class PackageReceipt(BaseModel):
    id: UUID
    snapshot_hash: str
    checklist: list[EvidenceChecklist]
    submitted_to_paypal: Literal[False]


class PackageSummary(BaseModel):
    id: UUID
    dispute_id: str
    reason: str
    snapshot_hash: str
    created_at: datetime
    reviewed_at: datetime | None
    reviewer_id: str | None


class PackagePage(BaseModel):
    items: list[PackageSummary]


class PackageDetail(BaseModel):
    id: UUID
    snapshot_hash: str
    reviewed: bool
    stale: bool
    snapshot: dict
    submitted_to_paypal: Literal[False]
