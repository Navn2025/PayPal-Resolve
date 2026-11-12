"""Durable merchant browser sessions and optional PayPal identity login."""

from app.schemas.merchant_auth import (
    CommerceKeySummary as CommerceKeySummary,
    CommerceKeys as CommerceKeys,
    Input as Input,
    IssuedCommerceKey as IssuedCommerceKey,
    IssuedMerchantSession as IssuedMerchantSession,
    MerchantKeyInput as MerchantKeyInput,
    MerchantSession as MerchantSession,
    PayPalFinish as PayPalFinish,
    PayPalRedirect as PayPalRedirect,
    PayPalResult as PayPalResult,
    PayPalStart as PayPalStart,
)

from app.integrations.paypal.identity import (
    CALLBACK_PATH as CALLBACK_PATH,
    PayPalLogin as PayPalLogin,
    _digest as _digest,
    paypal_config as paypal_config,
    web_origin as web_origin,
)


from datetime import datetime, timedelta, timezone
import hmac
import re
import secrets
from uuid import uuid4


from app.core.exceptions import StoreError
from app.schemas.payments import MerchantIdentity
from app.repositories.sqlite import LEGACY_MERCHANT_ID


SESSION_TTL = timedelta(hours=8)
FLOW_TTL = timedelta(minutes=10)
KEY_PROOF_TTL = timedelta(minutes=30)
COMMERCE_KEY_LIMIT = 25
SESSION_PATTERN = re.compile(r"rweb_[A-Za-z0-9_-]{43}")
KEY_PATTERN = re.compile(r"rslv_[A-Za-z0-9_-]{20,120}")
RANDOM_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def _now():
    return datetime.now(timezone.utc)


def _stamp(moment):
    return moment.isoformat(timespec="microseconds")


def _secret(value, pattern):
    raw = value.get_secret_value() if value else ""
    return raw if pattern.fullmatch(raw) else None


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
               AND ((k.id IS NOT NULL AND k.revoked_at IS NULL AND k.scope='full') OR (l.id IS NOT NULL AND l.issuer_key=?))""",
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
        from app.services.merchant.identity import Identities

        with self.store.transaction() as db:
            row = self._find(db, token, _now())
            if row:
                return self._view(db, row)
            result = Identities(self.store).session_in(db, token) if token else None
            return MerchantSession.model_validate(result) if result else None

    def merchant(self, token):
        session = self.session(token)
        return session.merchant if session else None

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
                   AND revoked_at IS NULL AND scope='full' AND merchant_id<>?""",
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
                db.execute(
                    "DELETE FROM platform_sessions WHERE token_hash=?",
                    (_digest(token),),
                )

    @staticmethod
    def _recent_key_session(row, now):
        return bool(
            row
            and row["api_key_id"]
            and datetime.fromisoformat(row["issued_at"]) + KEY_PROOF_TTL > now
        )

    def _key_session(self, db, token, now, *, purpose="manage PayPal sign-in"):
        row = self._find(db, token, now)
        if not self._recent_key_session(row, now):
            raise StoreError(
                403, f"Sign in again with a Resolve access key to {purpose}"
            )
        return row

    def commerce_keys(self, token):
        now = _now()
        with self.store.transaction() as db:
            row = self._find(db, token, now)
            if not row:
                raise StoreError(401, "Sign in to your merchant workspace")
            keys = db.execute(
                """SELECT id,created_at FROM merchant_api_keys
                   WHERE merchant_id=? AND scope='commerce' AND revoked_at IS NULL
                   ORDER BY created_at DESC,id DESC""",
                (row["id"],),
            ).fetchall()
            return CommerceKeys(
                keys=[
                    CommerceKeySummary(key_id=key["id"], created_at=key["created_at"])
                    for key in keys
                ],
                can_manage=self._recent_key_session(row, now),
            )

    def issue_commerce_key(self, token):
        with self.store.transaction(write=True) as db:
            row = self._key_session(db, token, _now(), purpose="manage SDK keys")
            count = db.execute(
                """SELECT count(*) FROM merchant_api_keys
                   WHERE merchant_id=? AND scope='commerce' AND revoked_at IS NULL""",
                (row["id"],),
            ).fetchone()[0]
            if count >= COMMERCE_KEY_LIMIT:
                raise StoreError(
                    409, "Revoke an unused SDK key before generating another"
                )
            merchant = MerchantIdentity(
                id=row["id"], name=row["name"], created_at=row["created_at"]
            )
            issued = self.store._issue_key(db, merchant, scope="commerce")
            return IssuedCommerceKey(key_id=issued.key_id, api_key=issued.api_key)

    def revoke_commerce_key(self, token, key_id):
        with self.store.transaction(write=True) as db:
            now = _now()
            row = self._key_session(db, token, now, purpose="manage SDK keys")
            result = db.execute(
                """UPDATE merchant_api_keys SET revoked_at=COALESCE(revoked_at,?)
                   WHERE id=? AND merchant_id=? AND scope='commerce'""",
                (_stamp(now), str(key_id), row["id"]),
            )
            if result.rowcount == 0:
                raise StoreError(404, "SDK key not found")

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
