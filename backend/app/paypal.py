"""First-party sandbox payment APIs. Hosts are fixed; links are never followed."""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from .errors import StoreError
from .models import (
    CaseResponse,
    Money,
    NonNegativeMoney,
    PayPalCaptureStatus,
    ProviderRefundStatus,
)
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

    def configuration(self):
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
        return settings

    def _configuration_for(self, case: CaseResponse):
        settings = self.configuration()
        if settings.paypal_resolve_merchant_id != case.merchant_id:
            raise StoreError(403, "PayPal Sandbox is not configured for this merchant")
        if re.fullmatch(r"[A-Za-z0-9]{1,64}", case.payment.capture_id) is None:
            raise StoreError(
                422, "Use an actual PayPal capture ID, not a sample or URL"
            )
        return settings

    def history_identity(self):
        settings = self.configuration()
        return hashlib.sha256(
            json.dumps(
                [
                    str(settings.paypal_resolve_merchant_id),
                    settings.paypal_sandbox_merchant_id,
                    settings.paypal_sandbox_client_id.get_secret_value(),
                ]
            ).encode()
        ).hexdigest()

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
        return self._read_capture(case, access_token)

    def _read_capture(self, case, access_token):
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
        if capture.payee.merchant_id != self.settings.paypal_sandbox_merchant_id:
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
        return self._read_refund(case, refund_id, self._access_token(settings))

    def _read_refund(self, case, refund_id, access_token):
        if re.fullmatch(r"[A-Za-z0-9]{1,64}", refund_id) is None:
            raise StoreError(422, "Use an actual PayPal refund ID")
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
            refund = PayPalHistoryRefund.model_validate(data)
        except ValidationError:
            raise StoreError(
                502, "PayPal Sandbox returned invalid refund details"
            ) from None
        if refund.id != refund_id or refund.amount.value > case.payment.captured_amount:
            raise StoreError(502, "PayPal Sandbox returned mismatched refund details")
        self._validate_refund_parent(refund, case.payment.capture_id)
        return refund

    def read_webhook_refund_links(self, refund_id):
        # Only the signed inbox calls this to route an event without a parent hint.
        if not re.fullmatch(r"[A-Za-z0-9]{1,64}", refund_id):
            raise StoreError(422, "Invalid PayPal refund ID")
        token = self._access_token(self.configuration())
        data = self._json_request(
            "GET",
            "/v2/payments/refunds/" + refund_id,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
        if not isinstance(data, dict) or data.get("id") != refund_id:
            raise StoreError(502, "PayPal returned a different refund resource")
        return data.get("links", [])

    def read_refund_history(self, case):
        settings = self._configuration_for(case)
        if not re.fullmatch(r"[A-Za-z0-9]{1,64}", case.order_id):
            raise StoreError(422, "Use an actual PayPal order ID")
        token = self._access_token(settings)
        capture = self._read_capture(case, token)
        raw = self._json_request(
            "GET",
            "/v2/checkout/orders/" + case.order_id,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            not_found_detail="PayPal Sandbox order was not found",
        )
        try:
            order = PayPalOrderDetails.model_validate(raw)
        except ValidationError:
            raise StoreError(
                409, "PayPal history requires one purchase unit and capture"
            ) from None
        unit = order.purchase_units[0]
        listed = unit.payments.captures[0]
        if (
            order.id != case.order_id
            or order.status != "COMPLETED"
            or unit.payee != capture.payee
            or listed.id != capture.id
            or listed.amount != capture.amount
            or listed.status != capture.status
            or listed.update_time != capture.update_time
        ):
            raise StoreError(409, "PayPal order and capture do not agree")
        refunds = []
        seen = set()
        for item in unit.payments.refunds:
            if item.id in seen:
                raise StoreError(409, "Duplicate refund in PayPal order history")
            seen.add(item.id)
            refund = self._read_refund(case, item.id, token)
            if refund.amount != item.amount or refund.status != item.status:
                raise StoreError(409, "PayPal order and refund details do not agree")
            refunds.append(refund)
        if self._read_capture(case, token) != capture:
            raise StoreError(409, "PayPal capture changed during history verification")
        completed = sum(
            (r.amount.value for r in refunds if r.status == "COMPLETED"), Decimal("0")
        )
        pending = sum(
            (r.amount.value for r in refunds if r.status == "PENDING"), Decimal("0")
        )
        totals = [
            r.seller_payable_breakdown.total_refunded_amount
            if r.seller_payable_breakdown
            else None
            for r in refunds
            if r.status == "COMPLETED"
        ]
        gross = capture.amount.value
        expected_status = (
            "REFUNDED"
            if completed == gross
            else "PARTIALLY_REFUNDED"
            if completed
            else "COMPLETED"
        )
        if (
            completed + pending > gross
            or capture.status != expected_status
            or (
                totals
                and (
                    any(t is None for t in totals)
                    or max(t.value for t in totals) != completed
                )
            )
        ):
            raise StoreError(
                409, "PayPal refund totals do not reconcile with the capture"
            )
        return capture, refunds

    def verify_webhook(self, headers, raw: bytes):
        settings = self.configuration()
        webhook_id = settings.paypal_sandbox_webhook_id
        if not webhook_id or not re.fullmatch(r"[A-Za-z0-9]{1,64}", webhook_id):
            raise StoreError(503, "PayPal Sandbox webhook is not configured")
        fields = {}
        for name in (
            "auth_algo",
            "cert_url",
            "transmission_id",
            "transmission_sig",
            "transmission_time",
        ):
            values = headers.getlist("paypal-" + name.replace("_", "-"))
            if len(values) != 1 or not 1 <= len(values[0]) <= 2048:
                raise StoreError(400, "Missing or invalid PayPal signature headers")
            fields[name] = values[0]
        try:
            cert = urlsplit(fields["cert_url"])
            sent_at = datetime.fromisoformat(fields["transmission_time"])
            if (
                cert.scheme != "https"
                or cert.netloc
                not in {
                    "api-m.sandbox.paypal.com",
                    "api.sandbox.paypal.com",
                    "api-m.paypal.com",
                    "api.paypal.com",
                }
                or not re.fullmatch(
                    r"/v1/notifications/certs/[A-Za-z0-9_-]+", cert.path
                )
                or cert.query
                or cert.fragment
                or sent_at.tzinfo is None
                or fields["auth_algo"] != "SHA256withRSA"
                or not re.fullmatch(r"[A-Za-z0-9+/=]+", fields["transmission_sig"])
            ):
                raise ValueError
        except ValueError:
            raise StoreError(400, "Invalid PayPal signature headers") from None
        fields["webhook_id"] = webhook_id
        # PayPal verifies a CRC over the original event bytes, including whitespace.
        envelope = json.dumps(fields).encode()[:-1] + b',"webhook_event":' + raw + b"}"
        try:
            result = self._json_request(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                headers={
                    "Authorization": "Bearer " + self._access_token(settings),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                content=envelope,
            )
        except StoreError:
            raise StoreError(
                503, "PayPal signature verification is unavailable"
            ) from None
        if not isinstance(result, dict) or result.get("verification_status") not in (
            "SUCCESS",
            "FAILURE",
        ):
            raise StoreError(503, "PayPal signature verification is unavailable")
        if result["verification_status"] != "SUCCESS":
            raise StoreError(401, "PayPal webhook signature did not verify")

    def refund_capture(
        self,
        case: CaseResponse,
        provider_request_id: UUID,
        amount: Decimal | None = None,
        *,
        custom_id: str | None = None,
    ) -> PayPalRefundDetails:
        settings = self._configuration_for(case)
        if not settings.paypal_sandbox_refunds_enabled:
            raise StoreError(503, "PayPal Sandbox refund execution is disabled")
        amount = case.payment.captured_amount if amount is None else amount
        if amount <= 0 or amount > case.payment.captured_amount:
            raise StoreError(409, "Refund amount is outside the capture balance")
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
                # An explicit amount prevents PayPal from choosing a changed balance.
                json={
                    "amount": {
                        "value": format(amount, ".2f"),
                        "currency_code": "USD",
                    },
                    **({"custom_id": custom_id} if custom_id else {}),
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
            if refund.amount.value != amount or (
                custom_id and refund.custom_id != custom_id
            ):
                raise ValueError("Refund amount mismatch")
        except (ValueError, ValidationError, StoreError):
            raise PayPalWriteError(
                503, "PayPal refund response needs reconciliation", outcome_unknown=True
            ) from None
        return refund
