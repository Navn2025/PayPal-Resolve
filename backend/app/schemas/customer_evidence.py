"""Contracts and validation types for customer evidence."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel


class CustomerEvidence(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    source: Literal["customer_submitted"] = "customer_submitted"
