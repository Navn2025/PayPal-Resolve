"""Contracts and validation types for platform operations."""

from uuid import UUID
from pydantic import AwareDatetime, Field, SecretStr, model_validator
from app.schemas.identity import Input


class OfferChoice(Input):
    promise_id: UUID
    expected_revision: int = Field(ge=1)


class OfferCreate(Input):
    choices: list[OfferChoice] = Field(min_length=1, max_length=4)
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def distinct_choices(self):
        if len({c.promise_id for c in self.choices}) != len(self.choices):
            raise ValueError("Offer choices must refer to distinct promises")
        return self


class OfferDecision(Input):
    token: SecretStr
    offer_id: UUID
    expected_revision: int = Field(ge=1)
    choice_id: UUID | None = None
    decision: str = Field(pattern=r"^(accept|decline)$")


class ReturnItem(Input):
    product_id: str = Field(min_length=1, max_length=160)
    quantity: int = Field(strict=True, ge=1, le=10000)


class ReturnCreate(Input):
    request_id: UUID
    order_id: UUID
    items: list[ReturnItem] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=2000)
    delivered_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def distinct_items(self):
        if len({i.product_id for i in self.items}) != len(self.items):
            raise ValueError("List each product once")
        return self


class BuyerReturn(ReturnCreate):
    token: SecretStr


class Shipment(Input):
    carrier: str = Field(min_length=1, max_length=60)
    tracking_code: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=160)


class ReturnUpdate(Input):
    expected_revision: int = Field(ge=1)
    action: str = Field(
        pattern=r"^(approve|reject|ship_return|receive|pass_inspection|ship_replacement|complete)$"
    )
    note: str = Field(min_length=1, max_length=2000)
    shipment: Shipment | None = None
    promise_id: UUID | None = None
    promise_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def complete_promise_reference(self):
        if bool(self.promise_id) != bool(self.promise_revision):
            raise ValueError("Select an exact promise revision")
        return self


class PackageCreate(Input):
    dispute_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    reason: str = Field(
        pattern=r"^(item_not_received|not_as_described|unauthorized|credit_not_processed|duplicate_charge|canceled_recurring|other)$"
    )
