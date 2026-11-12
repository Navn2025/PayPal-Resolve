"""Contracts and validation types for dispute evidence."""

from typing import Literal
from uuid import UUID
from pydantic import Field
from app.schemas.identity import Input


class DisputeDocument(Input):
    request_id: UUID
    requirement: Literal[
        "original_delivery",
        "product_description",
        "return_policy",
        "buyer_authorization",
        "service_fulfilled",
        "credit_agreement",
        "cancellation",
        "duplicate_charge",
        "other",
    ]
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=10)
    note: str = Field(min_length=1, max_length=2000)
