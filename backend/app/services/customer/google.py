"""One-time Google OIDC for the buyer portal; reuses mailbox-scoped sessions."""

from app.schemas.customer_google import (
    GoogleFinish as GoogleFinish,
    GoogleStart as GoogleStart,
)


from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
import re
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from pydantic import SecretStr

from app.services.customer.accounts import CustomerAccounts
from app.services.customer.notifications import normalize_email, stamp, token_hash
from app.core.exceptions import StoreError
from app.integrations.paypal.identity import web_origin


AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
KEYS = "https://www.googleapis.com/oauth2/v3/certs"
CALLBACK = "/api/customer-account/google/callback"
TTL = timedelta(minutes=10)
RANDOM = re.compile(r"[A-Za-z0-9_-]{43}")


def _challenge(value):
    return urlsafe_b64encode(sha256(value.encode()).digest()).decode().rstrip("=")


@dataclass(frozen=True)
class GoogleConfig:
    client_id: SecretStr
    client_secret: SecretStr
    origin: str

    @property
    def app_key(self):
        return token_hash(self.client_id.get_secret_value() + "|" + self.origin)

    @property
    def callback(self):
        return self.origin + CALLBACK


def google_config(settings):
    origin = web_origin(settings.customer_public_origin or settings.merchant_web_origin)
    client_id, secret = settings.google_client_id, settings.google_client_secret
    if (
        settings.customer_google_enabled
        and origin
        and client_id
        and client_id.get_secret_value().strip()
        and secret
        and secret.get_secret_value().strip()
    ):
        return GoogleConfig(client_id, secret, origin)
    return None


class GoogleCustomerSignIn:
    def __init__(self, store, settings):
        self.store = store
        self.config = google_config(settings)

    def _require(self):
        if self.config is None:
            raise StoreError(503, "Google sign-in is not configured")
        return self.config

    def start(self):
        config = self._require()
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with self.store.transaction(write=True) as db:
            db.execute(
                "DELETE FROM customer_google_flows WHERE expires_at<=?", (stamp(now),)
            )
            db.execute(
                """INSERT INTO customer_google_flows (state_hash,browser_hash,app_key,expires_at)
                   VALUES (?,?,?,?)""",
                (
                    token_hash(state),
                    token_hash(verifier),
                    config.app_key,
                    stamp(now + TTL),
                ),
            )
        query = {
            "client_id": config.client_id.get_secret_value(),
            "redirect_uri": config.callback,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "nonce": _challenge("nonce:" + state + ":" + verifier),
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return GoogleStart(
            authorize_url=AUTHORIZE + "?" + urlencode(query), browser_token=verifier
        )

    def finish(self, payload, http: httpx.Client):
        config = self._require()
        state = payload.state.get_secret_value()
        verifier = payload.browser_token.get_secret_value()
        code = payload.code.get_secret_value()
        invalid = StoreError(400, "This Google sign-in attempt is invalid or expired")
        if (
            not RANDOM.fullmatch(state)
            or not RANDOM.fullmatch(verifier)
            or not re.fullmatch(r"[!-~]{1,2048}", code)
        ):
            raise invalid
        with self.store.transaction(write=True) as db:
            row = db.execute(
                """SELECT browser_hash FROM customer_google_flows
                   WHERE state_hash=? AND app_key=? AND expires_at>?""",
                (token_hash(state), config.app_key, stamp(datetime.now(timezone.utc))),
            ).fetchone()
            if not row or not compare_digest(row["browser_hash"], token_hash(verifier)):
                raise invalid
            # Claim the callback before calling Google. A second browser or
            # request cannot redeem the same state while Google responds.
            db.execute(
                "DELETE FROM customer_google_flows WHERE state_hash=?",
                (token_hash(state),),
            )
        claims = self._verify(config, http, code, verifier)
        nonce = claims["nonce"]
        if (
            not isinstance(nonce, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce)
            or not compare_digest(nonce, _challenge("nonce:" + state + ":" + verifier))
        ):
            raise invalid
        try:
            email = normalize_email(claims["email"])
        except ValueError:
            raise StoreError(
                403, "Use the email sign-in option to verify this address"
            ) from None
        domain = email.rsplit("@", 1)[1]
        hosted_domain = claims.get("hd")
        if claims["email_verified"] is not True or (
            domain != "gmail.com"
            and (not isinstance(hosted_domain, str) or hosted_domain.lower() != domain)
        ):
            raise StoreError(403, "Use the email sign-in option to verify this address")
        return CustomerAccounts(self.store).from_verified_email(email)

    @staticmethod
    def _verify(config, http, code, verifier):
        try:
            client_id = config.client_id.get_secret_value()
            result = http.post(
                TOKEN,
                data={
                    "client_id": client_id,
                    "client_secret": config.client_secret.get_secret_value(),
                    "redirect_uri": config.callback,
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                },
            )
            if result.status_code == 400:
                raise StoreError(400, "Google did not accept this sign-in attempt")
            result.raise_for_status()
            grant = result.json()
            token = grant.get("id_token") if isinstance(grant, dict) else None
            if not isinstance(token, str) or not 0 < len(token) <= 8192:
                raise ValueError
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or not isinstance(kid, str)
                or not 0 < len(kid) <= 128
            ):
                raise ValueError
            response = http.get(KEYS)
            response.raise_for_status()
            jwks = response.json()
            keys = jwks.get("keys") if isinstance(jwks, dict) else None
            if not isinstance(keys, list):
                raise ValueError
            matches = [
                key
                for key in keys
                if isinstance(key, dict)
                and key.get("kid") == kid
                and key.get("kty") == "RSA"
            ]
            if len(matches) != 1:
                raise ValueError
            claims = jwt.decode(
                token,
                jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=("https://accounts.google.com", "accounts.google.com"),
                options={
                    "strict_aud": True,
                    "require": [
                        "sub",
                        "iss",
                        "aud",
                        "exp",
                        "iat",
                        "nonce",
                        "email",
                        "email_verified",
                    ],
                },
            )
            if not claims["sub"] or claims.get("azp", client_id) != client_id:
                raise ValueError
            return claims
        except (httpx.HTTPError, jwt.PyJWTError, TypeError, ValueError):
            raise StoreError(503, "Google sign-in could not be verified") from None
