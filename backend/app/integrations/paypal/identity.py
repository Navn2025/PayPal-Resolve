"""Contracts and validation types for merchant auth."""

from dataclasses import dataclass
from hashlib import sha256
import re
from urllib.parse import urlencode, urlsplit
import httpx
from pydantic import SecretStr
from app.core.exceptions import StoreError

CALLBACK_PATH = "/api/auth/paypal/callback"


def _digest(value):
    return sha256(value.encode()).hexdigest()


def web_origin(value):
    try:
        url = urlsplit(value or "")
        host, port = url.hostname, url.port
        if (
            not host
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or (
                url.scheme != "https"
                and not (
                    url.scheme == "http"
                    and url.hostname in ("127.0.0.1", "localhost", "::1")
                )
            )
        ):
            return None
        hostname = f"[{host}]" if ":" in host else host.encode("idna").decode("ascii")
        default = 443 if url.scheme == "https" else 80
        return f"{url.scheme}://{hostname}" + (
            f":{port}" if port is not None and port != default else ""
        )
    except ValueError:
        return None


@dataclass(frozen=True)
class PayPalLogin:
    environment: str
    client_id: SecretStr
    client_secret: SecretStr
    origin: str

    @property
    def issuer_key(self):
        return _digest(self.environment + ":" + self.client_id.get_secret_value())

    @property
    def api(self):
        return (
            "https://api-m.sandbox.paypal.com"
            if self.environment == "sandbox"
            else "https://api-m.paypal.com"
        )

    @property
    def redirect(self):
        return self.origin + CALLBACK_PATH

    def authorization_url(self, state):
        host = (
            "https://www.sandbox.paypal.com"
            if self.environment == "sandbox"
            else "https://www.paypal.com"
        )
        return (
            host
            + "/connect?"
            + urlencode(
                {
                    "flowEntry": "static",
                    "fullPage": "true",
                    "client_id": self.client_id.get_secret_value(),
                    "response_type": "code",
                    "scope": "openid",
                    "redirect_uri": self.redirect,
                    "state": state,
                }
            )
        )

    def subject(self, code, client: httpx.Client):
        try:
            response = client.post(
                self.api + "/v1/oauth2/token",
                auth=(
                    self.client_id.get_secret_value(),
                    self.client_secret.get_secret_value(),
                ),
                headers={"Accept": "application/json"},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect,
                },
            )
            if response.status_code in (400, 401, 403):
                raise StoreError(400, "PayPal did not accept the sign-in code")
            response.raise_for_status()
            grant = response.json()
            token = grant.get("access_token") if isinstance(grant, dict) else None
            if not isinstance(token, str) or not re.fullmatch(r"[!-~]{1,4096}", token):
                raise ValueError
            response = client.get(
                self.api + "/v1/identity/openidconnect/userinfo",
                params={"schema": "openid"},
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            profile = response.json()
            if not isinstance(profile, dict):
                raise ValueError
            field = "sub" if profile.get("sub") else "user_id"
            subject = profile.get(field)
            if not isinstance(subject, str) or not re.fullmatch(
                r"[!-~]{1,512}", subject
            ):
                raise ValueError
            return _digest(field + ":" + subject)
        except (httpx.HTTPError, ValueError):
            raise StoreError(
                503, "PayPal sign-in could not be verified; try again"
            ) from None


def paypal_config(settings):
    origin = web_origin(settings.merchant_web_origin)
    client_id, client_secret = (
        settings.paypal_login_client_id,
        settings.paypal_login_client_secret,
    )
    if not (
        settings.paypal_login_enabled
        and origin
        and client_id
        and client_id.get_secret_value()
        and client_secret
        and client_secret.get_secret_value()
        and (
            settings.paypal_login_environment == "sandbox"
            or origin.startswith("https://")
        )
    ):
        return None
    return PayPalLogin(
        settings.paypal_login_environment, client_id, client_secret, origin
    )
