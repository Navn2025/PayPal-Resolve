"""Durable merchant browser sessions and optional PayPal identity login."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import re
import secrets
from typing import Literal
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from .errors import StoreError
from .models import MerchantIdentity
from .storage import LEGACY_MERCHANT_ID


SESSION_TTL = timedelta(hours=8)
FLOW_TTL = timedelta(minutes=10)
KEY_PROOF_TTL = timedelta(minutes=30)
SESSION_PATTERN = re.compile(r"rweb_[A-Za-z0-9_-]{43}")
KEY_PATTERN = re.compile(r"rslv_[A-Za-z0-9_-]{20,120}")
RANDOM_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
CALLBACK_PATH = "/api/auth/paypal/callback"


def _now():
    return datetime.now(timezone.utc)


def _stamp(moment):
    return moment.isoformat(timespec="microseconds")


def _digest(value):
    return sha256(value.encode()).hexdigest()


def _secret(value, pattern):
    raw = value.get_secret_value() if value else ""
    return raw if pattern.fullmatch(raw) else None


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
    method: Literal["key", "paypal"]
    expires_at: datetime
    paypal_linked: bool


class IssuedMerchantSession(MerchantSession):
    token: str


class PayPalRedirect(BaseModel):
    authorize_url: str
    browser_token: str


class PayPalResult(BaseModel):
    intent: Literal["signin", "link"]
    session: IssuedMerchantSession | None = None


class MerchantAuth:
    def __init__(self, store, settings):
        self.store = store
        self.paypal = paypal_config(settings)

    @staticmethod
    def _clean(db, now):
        db.execute(
            "DELETE FROM merchant_paypal_flows WHERE expires_at<=?", (_stamp(now),)
        )
        db.execute(
            "DELETE FROM merchant_web_sessions WHERE expires_at<=?", (_stamp(now),)
        )

    def _find(self, db, token, now):
        if not token or not SESSION_PATTERN.fullmatch(token):
            return None
        return db.execute(
            """SELECT m.*,s.token_hash,s.issued_at,s.expires_at,s.api_key_id,s.paypal_link_id
               FROM merchant_web_sessions s JOIN merchants m ON m.id=s.merchant_id
               LEFT JOIN merchant_api_keys k ON k.id=s.api_key_id AND k.merchant_id=s.merchant_id
               LEFT JOIN merchant_paypal_links l ON l.id=s.paypal_link_id AND l.merchant_id=s.merchant_id
               WHERE s.token_hash=? AND s.expires_at>? AND m.id<>?
               AND ((k.id IS NOT NULL AND k.revoked_at IS NULL) OR (l.id IS NOT NULL AND l.issuer_key=?))""",
            (
                _digest(token),
                _stamp(now),
                str(LEGACY_MERCHANT_ID),
                self.paypal.issuer_key if self.paypal else None,
            ),
        ).fetchone()

    def _view(self, db, row):
        linked = (
            self.paypal
            and db.execute(
                "SELECT 1 FROM merchant_paypal_links WHERE merchant_id=? AND issuer_key=?",
                (row["id"], self.paypal.issuer_key),
            ).fetchone()
        )
        return MerchantSession(
            merchant=MerchantIdentity.model_validate(
                {"id": row["id"], "name": row["name"], "created_at": row["created_at"]}
            ),
            method="key" if row["api_key_id"] else "paypal",
            expires_at=row["expires_at"],
            paypal_linked=bool(linked),
        )

    def session(self, token):
        with self.store.transaction() as db:
            row = self._find(db, token, _now())
            return self._view(db, row) if row else None

    def merchant(self, token):
        with self.store.transaction() as db:
            row = self._find(db, token, _now())
            return (
                MerchantIdentity(
                    id=row["id"], name=row["name"], created_at=row["created_at"]
                )
                if row
                else None
            )

    def _issue(self, db, merchant_id, now, *, key_id=None, link_id=None):
        token = "rweb_" + secrets.token_urlsafe(32)
        db.execute(
            """INSERT INTO merchant_web_sessions (token_hash,merchant_id,api_key_id,paypal_link_id,issued_at,expires_at)
               VALUES (?,?,?,?,?,?)""",
            (
                _digest(token),
                merchant_id,
                key_id,
                link_id,
                _stamp(now),
                _stamp(now + SESSION_TTL),
            ),
        )
        return IssuedMerchantSession(
            token=token, **self._view(db, self._find(db, token, now)).model_dump()
        )

    def sign_in_key(self, secret):
        key = _secret(secret, KEY_PATTERN)
        if not key:
            raise StoreError(401, "Invalid or revoked Resolve access key")
        now = _now()
        with self.store.transaction(write=True) as db:
            row = db.execute(
                """SELECT id,merchant_id FROM merchant_api_keys WHERE token_hash=?
                   AND revoked_at IS NULL AND merchant_id<>?""",
                (_digest(key), str(LEGACY_MERCHANT_ID)),
            ).fetchone()
            if not row:
                raise StoreError(401, "Invalid or revoked Resolve access key")
            self._clean(db, now)
            return self._issue(db, row["merchant_id"], now, key_id=row["id"])

    def sign_out(self, token):
        if token and SESSION_PATTERN.fullmatch(token):
            with self.store.transaction(write=True) as db:
                db.execute(
                    "DELETE FROM merchant_web_sessions WHERE token_hash=?",
                    (_digest(token),),
                )

    def _key_session(self, db, token, now):
        row = self._find(db, token, now)
        if (
            not row
            or not row["api_key_id"]
            or datetime.fromisoformat(row["issued_at"]) + KEY_PROOF_TTL <= now
        ):
            raise StoreError(
                403, "Sign in again with a Resolve access key to manage PayPal sign-in"
            )
        return row

    def _provider(self):
        if not self.paypal:
            raise StoreError(503, "PayPal sign-in is not configured")
        return self.paypal

    def start(self, intent, token):
        paypal = self._provider()
        now = _now()
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.transaction(write=True) as db:
            self._clean(db, now)
            session_hash = (
                self._key_session(db, token, now)["token_hash"]
                if intent == "link"
                else None
            )
            db.execute(
                """INSERT INTO merchant_paypal_flows
                   (state_hash,browser_hash,issuer_key,intent,session_hash,expires_at) VALUES (?,?,?,?,?,?)""",
                (
                    _digest(state),
                    _digest(browser),
                    paypal.issuer_key,
                    intent,
                    session_hash,
                    _stamp(now + FLOW_TTL),
                ),
            )
        return PayPalRedirect(
            authorize_url=paypal.authorization_url(state), browser_token=browser
        )

    def finish(self, payload, token, client):
        paypal = self._provider()
        state, browser = (
            _secret(payload.state, RANDOM_PATTERN),
            _secret(payload.browser_token, RANDOM_PATTERN),
        )
        code = payload.code.get_secret_value()
        if not state or not browser or not re.fullmatch(r"[!-~]{1,2048}", code):
            raise StoreError(400, "This PayPal sign-in attempt is invalid or expired")
        now = _now()
        with self.store.transaction(write=True) as db:
            row = db.execute(
                """SELECT * FROM merchant_paypal_flows
                   WHERE state_hash=? AND issuer_key=? AND expires_at>? AND claimed_at IS NULL""",
                (_digest(state), paypal.issuer_key, _stamp(now)),
            ).fetchone()
            if not row or not hmac.compare_digest(
                row["browser_hash"], _digest(browser)
            ):
                raise StoreError(
                    400, "This PayPal sign-in attempt is invalid or expired"
                )
            if (
                row["intent"] == "link"
                and self._key_session(db, token, now)["token_hash"]
                != row["session_hash"]
            ):
                raise StoreError(403, "Link PayPal from the same signed-in browser")
            db.execute(
                "UPDATE merchant_paypal_flows SET claimed_at=? WHERE state_hash=?",
                (_stamp(now), _digest(state)),
            )

        subject = paypal.subject(code, client)
        now = _now()
        with self.store.transaction(write=True) as db:
            if not db.execute(
                "DELETE FROM merchant_paypal_flows WHERE state_hash=? AND expires_at>? AND claimed_at IS NOT NULL",
                (_digest(state), _stamp(now)),
            ).rowcount:
                raise StoreError(
                    400, "This PayPal sign-in attempt is invalid or expired"
                )
            link = db.execute(
                "SELECT id,merchant_id FROM merchant_paypal_links WHERE issuer_key=? AND subject_hash=?",
                (paypal.issuer_key, subject),
            ).fetchone()
            if row["intent"] == "link":
                merchant_id = self._key_session(db, token, now)["id"]
                if link and link["merchant_id"] != merchant_id:
                    raise StoreError(
                        409,
                        "This PayPal account is already linked to a different workspace",
                    )
                if not link:
                    exists = db.execute(
                        "SELECT 1 FROM merchant_paypal_links WHERE merchant_id=? AND issuer_key=?",
                        (merchant_id, paypal.issuer_key),
                    ).fetchone()
                    if exists:
                        raise StoreError(
                            409,
                            "Unlink the existing PayPal account before linking another",
                        )
                    db.execute(
                        "INSERT INTO merchant_paypal_links VALUES (?,?,?,?,?)",
                        (
                            str(uuid4()),
                            merchant_id,
                            paypal.issuer_key,
                            subject,
                            _stamp(now),
                        ),
                    )
                return PayPalResult(intent="link")
            if not link:
                raise StoreError(
                    403,
                    "Sign in with a Resolve access key and link PayPal in settings first",
                )
            return PayPalResult(
                intent="signin",
                session=self._issue(db, link["merchant_id"], now, link_id=link["id"]),
            )

    def unlink(self, token):
        paypal = self._provider()
        with self.store.transaction(write=True) as db:
            row = self._key_session(db, token, _now())
            db.execute(
                "DELETE FROM merchant_paypal_links WHERE merchant_id=? AND issuer_key=?",
                (row["id"], paypal.issuer_key),
            )
            db.execute(
                "DELETE FROM merchant_paypal_flows WHERE session_hash IN (SELECT token_hash FROM merchant_web_sessions WHERE merchant_id=?)",
                (row["id"],),
            )
