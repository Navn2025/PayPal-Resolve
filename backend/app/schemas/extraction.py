"""Contracts and validation types for ai extraction."""

from typing import Annotated, Literal, Self, get_args
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from app.schemas.privacy import InjectionFlag
from app.schemas.resolution import Target

PROMISE_KINDS = tuple(
    get_args(model.model_fields["kind"].annotation)[0]
    for model in get_args(get_args(Target)[0])
)

PromiseKind = Literal[PROMISE_KINDS]

ReviewReason = Literal[
    "not_configured",
    "no_messages",
    "auth_error",
    "model_not_found",
    "rate_limited",
    "bad_request",
    "timeout",
    "connection_error",
    "provider_error",
    "unexpected_error",
    "extraction_disabled",
    "data_policy_blocked",
    "budget_exceeded",
    "invalid_json",
    "schema_invalid",
    "low_confidence",
]

DropReason = Literal[
    "schema_invalid",
    "unknown_kind",
    "unknown_message",
    "buyer_message",
    "quote_not_found",
    "amount_not_allowed",
    "amount_not_in_quote",
    "duplicate",
    "limit_exceeded",
]

SkipReason = Literal[
    "extraction_disabled",
    "no_messages",
    "no_merchant_messages",
    "not_configured",
    "data_policy_blocked",
    "budget_exceeded",
]

AdjustmentReason = Literal[
    "quote_normalized", "quote_unmasked", "amount_removed", "action_removed"
]

MessageID = Annotated[str, Field(min_length=1, max_length=80)]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: MessageID
    sender: Literal["buyer", "merchant"]
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    sent_at: AwareDatetime


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Omit to use the case's stored customer conversation.",
    )

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = {message.id for message in self.messages or []}
        if len(ids) != len(self.messages or []):
            raise ValueError("Message IDs must be distinct")
        return self


class RawProposal(BaseModel):
    """One item as the model returned it, before any cross-checking."""

    model_config = ConfigDict(extra="ignore")

    kind: Annotated[str, Field(min_length=1, max_length=60)]
    amount_cents: Annotated[int, Field(ge=1, le=100_000_000)] | None = None
    action: Annotated[str, Field(max_length=60)] | None = None
    condition: Annotated[str, Field(max_length=500)] | None = None
    deadline: Annotated[str, Field(max_length=160)] | None = None
    source_message_id: MessageID
    exact_quote: Annotated[str, Field(min_length=1, max_length=1000)]
    confidence: Annotated[float, Field(ge=0, le=1)]


class PromiseProposal(RawProposal):
    kind: PromiseKind
    needs_review: bool
    action: str | None = Field(
        default=None,
        description="Target action for subscription, store credit/exchange and billing kinds.",
    )
    supporting_message_ids: list[MessageID] = Field(
        default_factory=list,
        description="Later merchant messages restating this promise with the same amount and action.",
    )
    possible_revision: bool = Field(
        default=False,
        description="An earlier message has a same-kind proposal with a different amount or action.",
    )


class DroppedProposal(BaseModel):
    reason: DropReason
    detail: str
    kind: str | None = None
    source_message_id: str | None = None
    exact_quote: str | None = None


class Adjustment(BaseModel):
    """A kept proposal that the validators changed."""

    reason: AdjustmentReason
    detail: str
    kind: str
    source_message_id: str


class ExtractionResult(BaseModel):
    case_id: UUID
    status: Literal["ok", "needs_review"]
    source: Literal["case_conversation", "merchant_supplied"]
    review_reasons: list[ReviewReason]
    model: str | None
    proposals: list[PromiseProposal]
    dropped: list[DroppedProposal]
    adjustments: list[Adjustment] = Field(default_factory=list)
    tokens: int = Field(
        0, description="Provider tokens used by this request; 0 on a cache hit."
    )
    flags: list[InjectionFlag] = Field(
        default_factory=list,
        description="Buyer messages matching an injection rule. Informational: never blocks.",
    )
    cache_hit: bool = False
    skipped_reason: SkipReason | None = Field(
        None, description="Why no model call was made, when none was."
    )
