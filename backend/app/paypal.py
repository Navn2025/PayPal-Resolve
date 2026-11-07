"""First-party sandbox payment APIs. Hosts are fixed; links are never followed."""

import re
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from .errors import StoreError
from .models import CaseResponse, Money, PayPalCaptureStatus, ProviderRefundStatus
from .settings import Settings


SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"


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


class PayPalLink(BaseModel):
    rel: str = Field(strict=True)
    href: str = Field(strict=True)
    method: str = Field(default="GET", strict=True)


class PayPalRefundDetails(BaseModel):
    id: str = Field(strict=True, pattern=r"^[A-Za-z0-9]{1,64}$")
    amount: PayPalAmount
    status: ProviderRefundStatus
    links: list[PayPalLink]


class PayPalWriteError(StoreError):
    def __init__(self, status_code: int, detail: str, *, outcome_unknown: bool):
        super().__init__(status_code, detail)
        self.outcome_unknown = outcome_unknown


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


class PayPalSandboxClient:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None):
        self.settings = settings
        # Test injection configures an actual local HTTP proxy, never a runtime base URL.
        self.http = (
            http_client
            if http_client is not None
            else httpx.Client(
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=False,
                trust_env=False,
            )
        )

    def close(self):
        self.http.close()

    def _configuration_for(self, case: CaseResponse):
        settings = self.settings
        if not settings.paypal_sandbox_enabled:
            raise StoreError(503, "PayPal Sandbox reads are disabled")
        if (
            settings.paypal_resolve_merchant_id is None
            or settings.paypal_sandbox_client_id is None
            or settings.paypal_sandbox_client_secret is None
            or not settings.paypal_sandbox_client_id.get_secret_value().strip()
            or not settings.paypal_sandbox_client_secret.get_secret_value().strip()
            or not settings.paypal_sandbox_merchant_id
        ):
            raise StoreError(503, "PayPal Sandbox configuration is incomplete")
        if settings.paypal_resolve_merchant_id != case.merchant_id:
            raise StoreError(403, "PayPal Sandbox is not configured for this merchant")
        if re.fullmatch(r"[A-Za-z0-9]{1,64}", case.payment.capture_id) is None:
            raise StoreError(
                422, "Use an actual PayPal capture ID, not a sample or URL"
            )
        return settings

    def _json_request(
        self,
        method,
        path,
        *,
        token_request=False,
        not_found_detail="PayPal Sandbox capture was not found",
        **kwargs,
    ):
        try:
            response = self.http.request(
                method, SANDBOX_BASE_URL + path, follow_redirects=False, **kwargs
            )
        except httpx.TimeoutException:
            raise StoreError(504, "PayPal Sandbox request timed out") from None
        except httpx.HTTPError:
            raise StoreError(502, "PayPal Sandbox connection failed") from None
        if response.status_code == 404 and not token_request:
            raise StoreError(404, not_found_detail)
        if response.status_code in (401, 403):
            if token_request:
                raise StoreError(503, "PayPal Sandbox credentials were rejected")
            raise StoreError(502, "PayPal Sandbox could not authorize the capture read")
        if response.status_code == 429 or response.status_code >= 500:
            raise StoreError(503, "PayPal Sandbox is temporarily unavailable")
        if response.status_code != 200:
            raise StoreError(502, "PayPal Sandbox returned an unexpected response")
        try:
            return response.json()
        except ValueError:
            raise StoreError(
                502, "PayPal Sandbox returned an invalid response"
            ) from None

    def _access_token(self, settings: Settings) -> str:
        data = self._json_request(
            "POST",
            "/v1/oauth2/token",
            token_request=True,
            auth=httpx.BasicAuth(
                settings.paypal_sandbox_client_id.get_secret_value(),
                settings.paypal_sandbox_client_secret.get_secret_value(),
            ),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        try:
            token = _OAuthToken.model_validate(data)
        except ValidationError:
            raise StoreError(
                502, "PayPal Sandbox returned an invalid token response"
            ) from None
        return token.access_token.get_secret_value()

    def read_capture(self, case: CaseResponse) -> PayPalCaptureDetails:
        settings = self._configuration_for(case)
        access_token = self._access_token(settings)
        data = self._json_request(
            "GET",
            "/v2/payments/captures/" + case.payment.capture_id,
            headers={
                "Authorization": "Bearer " + access_token,
                "Accept": "application/json",
            },
        )
        try:
            capture = PayPalCaptureDetails.model_validate(data)
        except ValidationError:
            raise StoreError(
                502, "PayPal Sandbox returned incomplete or invalid capture details"
            ) from None
        if capture.id != case.payment.capture_id:
            raise StoreError(502, "PayPal Sandbox returned a different capture ID")
        if (
            capture.amount.value != case.payment.captured_amount
            or capture.amount.currency_code != case.payment.currency
        ):
            raise StoreError(
                409, "PayPal capture amount or currency does not match this case"
            )
        if capture.payee.merchant_id != settings.paypal_sandbox_merchant_id:
            raise StoreError(
                409, "PayPal capture payee does not match the configured sandbox seller"
            )
        return capture

    @staticmethod
    def _validate_refund_parent(refund: PayPalRefundDetails, capture_id: str):
        # These are resource identifiers from an authenticated sandbox response,
        # not destinations. Some official examples use canonical live hostnames.
        # Actual requests always use SANDBOX_BASE_URL and never follow these links.
        hosts = {
            "api-m.sandbox.paypal.com",
            "api.sandbox.paypal.com",
            "api-m.paypal.com",
            "api.paypal.com",
        }
        for link in refund.links:
            try:
                parsed = urlsplit(link.href)
            except ValueError:
                continue
            if (
                link.rel == "up"
                and link.method == "GET"
                and parsed.scheme == "https"
                and parsed.netloc in hosts
                and parsed.path.rstrip("/") == "/v2/payments/captures/" + capture_id
                and not parsed.query
                and not parsed.fragment
            ):
                return
        raise StoreError(502, "PayPal refund parent capture could not be verified")

    def read_refund(self, case: CaseResponse, refund_id: str) -> PayPalRefundDetails:
        settings = self._configuration_for(case)
        if re.fullmatch(r"[A-Za-z0-9]{1,64}", refund_id) is None:
            raise StoreError(422, "Use an actual PayPal refund ID")
        access_token = self._access_token(settings)
        data = self._json_request(
            "GET",
            "/v2/payments/refunds/" + refund_id,
            headers={
                "Authorization": "Bearer " + access_token,
                "Accept": "application/json",
            },
            not_found_detail="PayPal Sandbox refund was not found",
        )
        try:
            refund = PayPalRefundDetails.model_validate(data)
        except ValidationError:
            raise StoreError(
                502, "PayPal Sandbox returned invalid refund details"
            ) from None
        if refund.id != refund_id or refund.amount.value > case.payment.captured_amount:
            raise StoreError(502, "PayPal Sandbox returned mismatched refund details")
        self._validate_refund_parent(refund, case.payment.capture_id)
        return refund

    def refund_capture(
        self, case: CaseResponse, provider_request_id: UUID
    ) -> PayPalRefundDetails:
        settings = self._configuration_for(case)
        if not settings.paypal_sandbox_refunds_enabled:
            raise StoreError(503, "PayPal Sandbox refund execution is disabled")
        try:
            access_token = self._access_token(settings)
        except StoreError as error:
            raise PayPalWriteError(
                error.status_code, error.detail, outcome_unknown=False
            ) from None
        try:
            response = self.http.post(
                SANDBOX_BASE_URL
                + "/v2/payments/captures/"
                + case.payment.capture_id
                + "/refund",
                headers={
                    "Authorization": "Bearer " + access_token,
                    "PayPal-Request-Id": str(provider_request_id),
                    "Prefer": "return=representation",
                    "Accept": "application/json",
                },
                # Explicit original amount: never silently refund a changed balance.
                json={
                    "amount": {
                        "value": format(case.payment.captured_amount, ".2f"),
                        "currency_code": "USD",
                    }
                },
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise PayPalWriteError(
                503, "PayPal refund outcome is not confirmed", outcome_unknown=True
            ) from None
        if response.status_code not in (200, 201):
            unknown = (
                response.status_code >= 500
                or response.status_code in (408, 409, 429)
                or 300 <= response.status_code < 400
            )
            raise PayPalWriteError(
                503 if unknown else 502,
                "PayPal refund request was not confirmed"
                if unknown
                else "PayPal refund request was rejected",
                outcome_unknown=unknown,
            )
        try:
            refund = PayPalRefundDetails.model_validate(response.json())
            self._validate_refund_parent(refund, case.payment.capture_id)
            if refund.amount.value != case.payment.captured_amount:
                raise ValueError("Refund amount mismatch")
        except (ValueError, ValidationError, StoreError):
            raise PayPalWriteError(
                503, "PayPal refund response needs reconciliation", outcome_unknown=True
            ) from None
        return refund
