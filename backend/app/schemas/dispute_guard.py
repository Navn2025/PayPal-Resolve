"""Contracts and validation types for dispute guard."""

from typing import Literal
from pydantic import Field
from app.schemas.identity import Input


class DisputeEvent(Input):
    provider: Literal["paypal", "stripe", "bank", "merchant"]
    reference: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    event_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    version: int = Field(strict=True, ge=1)
    state: Literal["open", "under_review", "resolved_no_refund", "resolved_refunded"]
    note: str = Field(min_length=1, max_length=2000)
