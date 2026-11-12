"""Contracts and validation types for merchant auth."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from app.schemas.payments import MerchantIdentity


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MerchantKeyInput(Input):
    key: SecretStr


class PayPalStart(Input):
    intent: Literal["signin", "link"] = "signin"


class PayPalFinish(Input):
    state: SecretStr
    browser_token: SecretStr
    code: SecretStr


class MerchantSession(BaseModel):
    merchant: MerchantIdentity
    method: Literal["key", "paypal", "password"]
    expires_at: datetime
    paypal_linked: bool
    staff: dict | None = None


class IssuedMerchantSession(MerchantSession):
    token: str


class PayPalRedirect(BaseModel):
    authorize_url: str
    browser_token: str


class PayPalResult(BaseModel):
    intent: Literal["signin", "link"]
    session: IssuedMerchantSession | None = None


class CommerceKeySummary(BaseModel):
    key_id: UUID
    created_at: datetime


class CommerceKeys(BaseModel):
    keys: list[CommerceKeySummary]
    can_manage: bool


class IssuedCommerceKey(BaseModel):
    key_id: UUID
    api_key: str = Field(repr=False)
