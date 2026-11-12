"""Contracts and validation types for customer account."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from app.core.validation import normalize_email


class EmailSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str

    @field_validator("email")
    @classmethod
    def check_email(cls, value):
        return normalize_email(value)


class RedeemSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


class AccountToken(BaseModel):
    token: str
    expires_at: datetime


class AccountCase(BaseModel):
    id: UUID
    title: str
    order_reference: str | None
    merchant_name: str
    created_at: datetime
