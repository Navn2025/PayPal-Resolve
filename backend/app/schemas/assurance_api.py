"""Contracts and validation types for assurance routes."""

from uuid import UUID
from pydantic import AwareDatetime, Field
from app.schemas.aftercare import OrderLocator
from app.schemas.customer_portal import PortalCredentials
from app.schemas.identity import Input
from app.schemas.platform_operations import ReturnItem


class ContextRequest(OrderLocator):
    before_sequence: int | None = Field(default=None, ge=1)


class EligibilityInput(OrderLocator):
    items: list[ReturnItem] = Field(min_length=1, max_length=50)
    delivered_at: AwareDatetime | None = None


class SupportReturn(EligibilityInput):
    request_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class ReturnLocator(OrderLocator):
    return_id: UUID


class LabelLocator(ReturnLocator):
    label_id: UUID


class LabelInput(Input):
    filename: str = Field(max_length=120)
    content_base64: str = Field(max_length=2800000)


class BuyerReturnLocator(PortalCredentials):
    return_id: UUID


class BuyerLabelLocator(BuyerReturnLocator):
    label_id: UUID
