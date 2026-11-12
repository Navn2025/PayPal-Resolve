"""Contracts and validation types for customer intake."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.core.validation import normalize_email
from app.schemas.customer_portal import PortalCredentials

IssueType = Literal[
    "missing_item", "duplicate_charge", "damaged_delivery", "refund_delay", "other"
]


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    order_reference: str = Field(min_length=1, max_length=160)
    customer_email: str | None = None
    send_email: bool = True

    @field_validator("customer_email")
    @classmethod
    def check_email(cls, value):
        return normalize_email(value) if value is not None else None


class InviteIssued(BaseModel):
    token: str
    order_reference: str
    expires_at: datetime
    email_queued: bool = False
    public_url: str | None = None


class IntakeView(BaseModel):
    order_reference: str
    submitted: bool


class IntakeSubmit(PortalCredentials):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    issue_type: IssueType
    description: str = Field(min_length=1, max_length=2000)
