"""Contracts and validation types for sdk events."""

from uuid import UUID
from pydantic import BaseModel, Field
from app.schemas.commerce import Source
from app.schemas.identity import Input


class EventPull(Input):
    source: Source
    after_sequence: int = Field(default=0, strict=True, ge=0, le=9007199254740991)
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class AppResolutionEvent(BaseModel):
    id: UUID
    sequence: int
    source: str
    order_reference: str
    revision: int
    snapshot: dict
    created_at: str
    type: str = "resolution.updated"


class EventPage(BaseModel):
    merchant_id: UUID
    source: str
    items: list[AppResolutionEvent]
    next_after_sequence: int
    has_more: bool
    reconciled_orders: int
