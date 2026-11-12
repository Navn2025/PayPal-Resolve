"""Contracts and validation types for customer portal."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from app.schemas.customer_evidence import CustomerEvidence
from app.schemas.customer_progress import CustomerMilestone, CustomerNextStep
from app.schemas.payments import NonNegativeMoney
from app.schemas.resolution import Outcome

RemedyKind = Literal[
    "refund",
    "return",
    "replacement",
    "order_cancellation",
    "subscription",
    "store_credit_or_exchange",
    "billing_correction",
    "dispute_handoff",
]


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(default="Your resolution", min_length=1, max_length=120)
    show_order_reference: bool = False


class LinkStatus(BaseModel):
    active: bool
    expires_at: datetime | None = None
    title: str | None = None
    show_order_reference: bool = False


class IssuedLink(LinkStatus):
    token: str
    public_url: str | None = None


class PortalCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID
    body: str = Field(min_length=1, max_length=2000)


class CustomerMessageCreate(PortalCredentials, MessageCreate):
    pass


class PortalMessage(BaseModel):
    id: UUID
    sender: Literal["merchant", "customer"]
    body: str
    created_at: datetime


class PublicPromise(BaseModel):
    kind: RemedyKind
    promise: str
    outcome: Outcome
    due_at: datetime | None = None
    provider_confirmed: bool


class PublicRefund(BaseModel):
    promised_amount: NonNegativeMoney
    confirmed_amount: NonNegativeMoney | None
    pending_amount: NonNegativeMoney | None
    outstanding_amount: NonNegativeMoney | None
    verification: Literal["current", "unverified"]
    currency: Literal["USD"] = "USD"
    environment: Literal["sandbox"] = "sandbox"


class CustomerCase(BaseModel):
    title: str
    order_reference: str | None
    outcome: Outcome
    expires_at: datetime
    promises: list[PublicPromise]
    refund: PublicRefund | None
    messages: list[PortalMessage]
    evidence: list[CustomerEvidence]
    timeline: list[CustomerMilestone]
    next_step: CustomerNextStep
