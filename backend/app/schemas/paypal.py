"""Contracts and validation types for paypal."""

from pydantic import BaseModel, Field, SecretStr, field_validator
from app.schemas.payments import (
    Money,
    NonNegativeMoney,
    PayPalCaptureStatus,
    ProviderRefundStatus,
)


class PayPalAmount(BaseModel):
    value: Money
    currency_code: str = Field(strict=True, pattern=r"^USD$")

    @field_validator("value", mode="before")
    @classmethod
    def require_decimal_string(cls, value):
        if not isinstance(value, str):
            raise ValueError("Provider amount must be a decimal string")
        return value


class PayPalPayee(BaseModel):
    merchant_id: str = Field(strict=True, min_length=1, max_length=64)


class PayPalCaptureDetails(BaseModel):
    id: str = Field(strict=True, pattern=r"^[A-Za-z0-9]{1,64}$")
    amount: PayPalAmount
    status: PayPalCaptureStatus
    payee: PayPalPayee
    update_time: str | None = None


class PayPalLink(BaseModel):
    rel: str = Field(strict=True)
    href: str = Field(strict=True)
    method: str = Field(default="GET", strict=True)


class PayPalRefundDetails(BaseModel):
    id: str = Field(strict=True, pattern=r"^[A-Za-z0-9]{1,64}$")
    amount: PayPalAmount
    status: ProviderRefundStatus
    links: list[PayPalLink]
    custom_id: str | None = None


class PayPalCumulativeAmount(PayPalAmount):
    value: NonNegativeMoney


class PayPalRefundBreakdown(BaseModel):
    total_refunded_amount: PayPalCumulativeAmount | None = None


class PayPalHistoryRefund(PayPalRefundDetails):
    seller_payable_breakdown: PayPalRefundBreakdown | None = None


class PayPalOrderRefund(BaseModel):
    id: str = Field(strict=True, pattern=r"^[A-Za-z0-9]{1,64}$")
    amount: PayPalAmount
    status: ProviderRefundStatus


class PayPalOrderCapture(BaseModel):
    id: str
    amount: PayPalAmount
    status: PayPalCaptureStatus
    update_time: str | None = None


class PayPalOrderPayments(BaseModel):
    captures: list[PayPalOrderCapture] = Field(min_length=1, max_length=1)
    refunds: list[PayPalOrderRefund] = Field(default_factory=list, max_length=100)


class PayPalOrderUnit(BaseModel):
    payee: PayPalPayee
    payments: PayPalOrderPayments


class PayPalOrderDetails(BaseModel):
    id: str
    status: str
    purchase_units: list[PayPalOrderUnit] = Field(min_length=1, max_length=1)


class _OAuthToken(BaseModel):
    access_token: SecretStr
    token_type: str = Field(pattern=r"^Bearer$")
    expires_in: int = Field(gt=0)

    @field_validator("access_token")
    @classmethod
    def require_token(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("Missing provider token")
        return value
