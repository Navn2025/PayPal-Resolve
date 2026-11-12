"""Contracts and validation types for next action."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel

MissingCode = Literal[
    "no_linked_payment",
    "no_refund_promise",
    "no_amount",
    "agreement_not_accepted",
    "no_deadline",
    "unmet_condition",
    "pending_refund_unconfirmed",
]


class MissingItem(BaseModel):
    code: MissingCode
    text: str
    promise_id: UUID | None = None


class Prerequisite(BaseModel):
    name: str
    done: bool


class RefundFacts(BaseModel):
    promise_id: UUID
    promised_amount: Decimal
    refunded_amount: Decimal
    pending_amount: Decimal
    remaining_amount: Decimal
    due_date: date | None
    days_since_promise: int
    prerequisites: list[Prerequisite]


class CaseFacts(BaseModel):
    """Structured, message-free facts. This is all the model ever sees."""

    currency: str = "USD"
    payment_linked: bool
    captured_amount: Decimal | None = None
    agreed_amount: Decimal | None = None
    agreement_status: str | None = None
    reconciliation_status: str | None = None
    recommended_refund_amount: Decimal | None = None
    refunds: list[RefundFacts] = []


class NextAction(BaseModel):
    case_id: UUID
    facts: CaseFacts
    missing: list[MissingItem]
    summary: str


class Explanation(BaseModel):
    case_id: UUID
    text: str
    source: Literal["ai", "template"]
    label: str | None
    fallback_reason: str | None
    guard_violations: list[str]
    model: str | None
    tokens: int = 0
    cache_hit: bool = False
    facts: CaseFacts
    missing: list[MissingItem]
    authorizes: Literal["nothing"] = "nothing"
