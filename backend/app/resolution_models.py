"""Public contracts for the shared remedy workspace."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .models import CaseAttachment, CaseTimelineEntry, Money, NonNegativeMoney


PayPalID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
ShopifyID = Annotated[str, Field(pattern=r"^gid://shopify/[A-Za-z]+/[0-9]{1,32}$")]
Short = Annotated[str, Field(min_length=1, max_length=160)]
Note = Annotated[str, Field(min_length=1, max_length=3000)]
Outcome = Literal["waiting", "pending", "fulfilled", "needs_review"]
EvidenceSource = Literal["merchant_recorded", "provider_confirmed", "system"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RefundTarget(Input):
    kind: Literal["refund"]
    amount: Money
    currency: Literal["USD"] = "USD"


class TrackingReference(Input):
    tracker_id: Annotated[str, Field(pattern=r"^trk_[A-Za-z0-9]{1,80}$")]
    tracking_code: Annotated[str, Field(pattern=r"^[A-Za-z0-9 -]{1,100}$")]
    carrier: Annotated[str, Field(pattern=r"^[A-Za-z0-9_ -]{1,60}$")]


class ReturnTarget(Input):
    kind: Literal["return"]
    milestone: Literal["carrier_delivered", "warehouse_received", "inspection_passed"]
    return_reference: Short
    tracking: TrackingReference | None = None

    @model_validator(mode="after")
    def require_tracker(self) -> Self:
        if self.milestone == "carrier_delivered" and self.tracking is None:
            raise ValueError("Carrier delivery requires a tracker reference")
        return self


class ReplacementTarget(Input):
    kind: Literal["replacement"]
    replacement_reference: Short
    milestone: Literal["shipped", "delivered"]
    tracking: TrackingReference


class OrderCancellationTarget(Input):
    kind: Literal["order_cancellation"]
    shopify_order_id: ShopifyID | None = None
    paypal_authorization_id: PayPalID | None = None

    @model_validator(mode="after")
    def require_reference(self) -> Self:
        if not (self.shopify_order_id or self.paypal_authorization_id):
            raise ValueError("A Shopify order or PayPal authorization is required")
        if self.shopify_order_id and not self.shopify_order_id.startswith(
            "gid://shopify/Order/"
        ):
            raise ValueError("Expected a Shopify Order ID")
        return self


class SubscriptionTarget(Input):
    kind: Literal["subscription"]
    paypal_subscription_id: PayPalID
    action: Literal["cancel", "pause"]


class StoreCreditOrExchangeTarget(Input):
    kind: Literal["store_credit_or_exchange"]
    action: Literal["store_credit", "exchange"]
    credit_transaction_id: ShopifyID | None = None
    credit_account_id: ShopifyID | None = None
    amount: Money | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    fulfillment_id: ShopifyID | None = None
    shopify_order_id: ShopifyID | None = None
    exchange_line_item_id: ShopifyID | None = None

    @model_validator(mode="after")
    def require_action_fields(self) -> Self:
        credit = (
            self.credit_transaction_id,
            self.credit_account_id,
            self.amount,
            self.currency,
        )
        exchange = (
            self.fulfillment_id,
            self.shopify_order_id,
            self.exchange_line_item_id,
        )
        if self.action == "store_credit":
            if (
                not all(credit)
                or any(exchange)
                or not (
                    self.credit_transaction_id.startswith(
                        "gid://shopify/StoreCreditAccountCreditTransaction/"
                    )
                    and self.credit_account_id.startswith(
                        "gid://shopify/StoreCreditAccount/"
                    )
                )
            ):
                raise ValueError(
                    "Store credit requires the credit transaction, account, amount and currency"
                )
        elif (
            not all(exchange)
            or any(credit)
            or not all(
                value.startswith("gid://shopify/" + kind + "/")
                for value, kind in zip(
                    exchange, ("Fulfillment", "Order", "LineItem"), strict=True
                )
            )
        ):
            raise ValueError(
                "Exchange requires a Shopify fulfillment, order and exchange line item"
            )
        return self


class BillingCorrectionTarget(Input):
    kind: Literal["billing_correction"]
    action: Literal["cancel_invoice", "duplicate_charge", "incorrect_amount"]
    paypal_invoice_id: PayPalID | None = None
    original_capture_id: PayPalID | None = None

    @model_validator(mode="after")
    def require_action_fields(self) -> Self:
        if self.action == "cancel_invoice":
            if not self.paypal_invoice_id or self.original_capture_id:
                raise ValueError(
                    "Invoice cancellation requires only a PayPal invoice ID"
                )
        elif self.paypal_invoice_id or (self.action == "duplicate_charge") != bool(
            self.original_capture_id
        ):
            raise ValueError(
                "Only a duplicate charge requires the other PayPal capture ID"
            )
        return self


class DisputeHandoffTarget(Input):
    kind: Literal["dispute_handoff"]
    paypal_dispute_id: PayPalID


Target = Annotated[
    RefundTarget
    | ReturnTarget
    | ReplacementTarget
    | OrderCancellationTarget
    | SubscriptionTarget
    | StoreCreditOrExchangeTarget
    | BillingCorrectionTarget
    | DisputeHandoffTarget,
    Field(discriminator="kind"),
]


class ResolutionCreate(Input):
    title: Short
    order_reference: Short | None = None
    refund_case_id: UUID | None = None


class PromiseTerms(Input):
    promise: Note
    source_note: Note
    source_reference: Short | None = None
    due_at: AwareDatetime | None = None
    requires: list[UUID] = Field(default_factory=list, max_length=8)
    target: Target

    @model_validator(mode="after")
    def unique_dependencies(self) -> Self:
        if len(self.requires) != len(set(self.requires)):
            raise ValueError("Prerequisites must be distinct")
        return self


class PromiseRevision(PromiseTerms):
    expected_revision: int = Field(ge=1, strict=True)


class MerchantEvidence(Input):
    expected_revision: int = Field(ge=1, strict=True)
    note: Note
    reference: Short | None = None
    finding: Literal["note", "confirmed", "not_confirmed"] = "note"


class RefreshEvidence(Input):
    expected_revision: int = Field(ge=1, strict=True)


class ProviderProof(BaseModel):
    provider: Literal["paypal", "shopify", "easypost"]
    resource_id: str
    status: str
    outcome: Outcome
    detail: str
    environment: Literal["sandbox", "test", "production"] | None = None
    response_due_at: AwareDatetime | None = None
    amount: NonNegativeMoney | None = None
    currency: str | None = None


class RefundProgress(BaseModel):
    refund_case_id: UUID
    captured_amount: NonNegativeMoney
    promised_amount: NonNegativeMoney
    provider_completed_amount: NonNegativeMoney
    provider_pending_amount: NonNegativeMoney
    outstanding_amount: NonNegativeMoney
    history_current: bool
    verified_remaining_refundable_amount: NonNegativeMoney | None = None
    refund_ids: list[str]


class PromiseView(BaseModel):
    id: UUID
    revision: int
    terms: PromiseTerms
    outcome: Outcome
    evidence_source: EvidenceSource
    reason: str
    checked_at: datetime | None = None
    overdue: bool
    provider_proofs: list[ProviderProof] = Field(default_factory=list)
    refund_progress: RefundProgress | None = None
    created_at: datetime
    updated_at: datetime


class ResolutionSummary(BaseModel):
    id: UUID
    title: str
    order_reference: str | None
    refund_case_id: UUID | None
    created_at: datetime


class ResolutionView(ResolutionSummary):
    outcome: Outcome
    promises: list[PromiseView]


class ResolutionPage(BaseModel):
    items: list[ResolutionSummary]
    total: int
    limit: int
    offset: int


class ResolutionEvent(BaseModel):
    sequence: int
    id: UUID
    promise_id: UUID | None
    revision: int | None
    event_type: str
    source: EvidenceSource
    actor_merchant_id: UUID | None
    recorded_at: datetime
    data: dict


class ResolutionTimeline(BaseModel):
    items: list[ResolutionEvent]
    total: int
    limit: int
    offset: int
    refund_items: list[CaseTimelineEntry] = Field(default_factory=list)
    refund_total: int = 0


class ResolutionBundle(BaseModel):
    case: ResolutionView
    timeline: ResolutionTimeline
    refund_attachments: list[CaseAttachment]
