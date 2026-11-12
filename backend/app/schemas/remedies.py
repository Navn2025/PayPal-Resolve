"""Contracts and validation types for remedies."""

from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, Field
from app.schemas.resolution import Input, PromiseView, Short

OptionId = Literal["refund_after_return", "partial_refund"]

UnavailableKind = Literal[
    "refund_after_return", "partial_refund", "store_credit", "replacement"
]

Issue = Literal[
    "damaged",
    "not_received",
    "wrong_item",
    "not_as_described",
    "changed_mind",
    "other",
    "unknown",
]

Preference = Literal[
    "full_refund",
    "partial_refund",
    "replacement",
    "store_credit",
    "keep_item",
    "unknown",
]


class RemedyFacts(BaseModel):
    payment_linked: bool
    currency: str = "USD"
    captured_amount: Decimal | None = None
    completed_refund_amount: Decimal | None = None
    pending_refund_amount: Decimal | None = None
    refundable_amount: Decimal | None = None
    payment_hold: bool = False
    return_policy_enabled: bool
    return_policy_revision: int
    restocking_fee: Decimal
    return_window_days: int | None
    inspection_required: bool
    partial_refund_percent: int


class RemedyOption(BaseModel):
    id: OptionId
    title: str
    description: str
    amount: Decimal
    currency: str
    requires_return: bool
    return_milestone: Literal["warehouse_received", "inspection_passed"] | None = None
    reason: str


class Unavailable(BaseModel):
    kind: UnavailableKind
    reason: str


class RemedySuggestions(BaseModel):
    case_id: UUID
    facts: RemedyFacts
    options: list[RemedyOption]
    unavailable: list[Unavailable]


class CreateRemedy(Input):
    """The one option the merchant chose. A capture holds one cumulative refund promise
    (ResolutionWorkspace rule), so refund options cannot be recorded side by side."""

    option_id: OptionId
    expected_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    return_reference: Short | None = None
    due_at: AwareDatetime | None = None


class OfferChoiceDraft(BaseModel):
    promise_id: UUID
    expected_revision: int


class CreatedRemedy(BaseModel):
    option_id: OptionId
    promises: list[PromiseView]
    # Ready for POST /platform/cases/{id}/offers; nothing is published by this request.
    offer_choice: OfferChoiceDraft


class RankedOption(BaseModel):
    option_id: OptionId
    reason: str


class RemedyRanking(BaseModel):
    case_id: UUID
    source: Literal["ai", "code"]
    label: str | None
    fallback_reason: str | None
    issue: Issue
    buyer_preference: Preference
    ranking: list[RankedOption]
    buyer_message: str
    guard_violations: list[str] = Field(default_factory=list)
    model: str | None = None
    tokens: int = 0
    cache_hit: bool = False
