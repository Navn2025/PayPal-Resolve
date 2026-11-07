"""Mailbox verification and case access, separate from merchant sessions."""

from datetime import datetime, timedelta, timezone
import re
import secrets
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from .customer_email import (
    SIGNIN_WINDOW,
    enqueue,
    mail_config,
    mail_token,
    normalize_email,
    stamp,
    token_hash,
)
from .errors import StoreError

SESSION_LIFETIME = timedelta(days=7)
CASE_LIFETIME = timedelta(hours=1)
LOGIN_PATTERN = re.compile(r"rlog_[A-Za-z0-9_-]{43}")
SESSION_PATTERN = re.compile(r"racs_[A-Za-z0-9_-]{43}")


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


def _session_hash(authorization):
    token = (
        authorization[7:]
        if authorization and authorization.startswith("Bearer ")
        else ""
    )
    if not SESSION_PATTERN.fullmatch(token):
        raise StoreError(401, "Sign in to view your cases")
    return token_hash(token)


_ACTIVE_CASES = """FROM customer_case_contacts c
    JOIN resolution_cases r ON r.id=c.resolution_id AND r.merchant_id=c.merchant_id
    JOIN merchants m ON m.id=c.merchant_id
    JOIN customer_portal_links l ON l.resolution_id=r.id AND l.revoked_at IS NULL"""


class CustomerAccounts:
    def __init__(self, store):
        self.store = store

    def request(self, email, settings):
        _, key, _, _ = mail_config(settings)
        now = datetime.now(timezone.utc)
        with self.store.transaction(write=True) as db:
            if not db.execute(
                "SELECT 1 " + _ACTIVE_CASES + " WHERE c.email=? LIMIT 1", (email,)
            ).fetchone():
                return
            recent = db.execute(
                "SELECT created_at FROM customer_signins WHERE email=? AND created_at>? ORDER BY created_at DESC LIMIT 5",
                (email, stamp(now - timedelta(hours=1))),
            ).fetchall()
            if len(recent) >= 5 or (
                recent and recent[0]["created_at"] > stamp(now - timedelta(minutes=1))
            ):
                return
            identifier = str(uuid4())
            token = mail_token(key, "signin", identifier)
            db.execute(
                """INSERT INTO customer_signins (token_hash,email,created_at,expires_at) VALUES (?,?,?,?)""",
                (token_hash(token), email, stamp(now), stamp(now + SIGNIN_WINDOW)),
            )
            enqueue(
                db,
                "signin",
                "signin:" + identifier,
                email,
                now,
                identifier=identifier,
                lifetime=SIGNIN_WINDOW,
            )

    def redeem(self, secret):
        token = secret.get_secret_value()
        error = StoreError(
            404, "This sign-in link is invalid, expired, or already used"
        )
        if not LOGIN_PATTERN.fullmatch(token):
            raise error
        digest = token_hash(token)
        now = datetime.now(timezone.utc)
        expiry = now + SESSION_LIFETIME
        session = "racs_" + secrets.token_urlsafe(32)
        with self.store.transaction(write=True) as db:
            row = db.execute(
                """SELECT email FROM customer_signins WHERE token_hash=? AND consumed_at IS NULL AND expires_at>?""",
                (digest, stamp(now)),
            ).fetchone()
            if not row:
                raise error
            db.execute(
                "UPDATE customer_signins SET consumed_at=? WHERE token_hash=?",
                (stamp(now), digest),
            )
            db.execute(
                "INSERT INTO customer_sessions (token_hash,email,expires_at) VALUES (?,?,?)",
                (token_hash(session), row["email"], stamp(expiry)),
            )
        return AccountToken(token=session, expires_at=expiry)

    @staticmethod
    def _email(db, session, now):
        row = db.execute(
            "SELECT email FROM customer_sessions WHERE token_hash=? AND expires_at>?",
            (session, stamp(now)),
        ).fetchone()
        if not row:
            raise StoreError(401, "Sign in to view your cases")
        return row["email"]

    def cases(self, authorization):
        session = _session_hash(authorization)
        with self.store.transaction() as db:
            email = self._email(db, session, datetime.now(timezone.utc))
            rows = db.execute(
                """SELECT r.id,l.title,CASE WHEN l.show_order_reference=1 THEN r.order_reference END AS order_reference,
                   m.name AS merchant_name,r.created_at """
                + _ACTIVE_CASES
                + " WHERE c.email=? ORDER BY r.created_at DESC,r.id",
                (email,),
            )
            return [AccountCase.model_validate(dict(row)) for row in rows]

    def open_case(self, authorization, case_id):
        session = _session_hash(authorization)
        now = datetime.now(timezone.utc)
        token = "racp_" + secrets.token_urlsafe(32)
        with self.store.transaction(write=True) as db:
            email = self._email(db, session, now)
            row = db.execute(
                "SELECT l.token_hash " + _ACTIVE_CASES + " WHERE c.email=? AND r.id=?",
                (email, str(case_id)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Case not found")
            expiry = now + CASE_LIFETIME
            db.execute(
                "DELETE FROM customer_account_links WHERE expires_at<=?", (stamp(now),)
            )
            db.execute(
                "INSERT INTO customer_account_links VALUES (?,?,?,?,?)",
                (
                    token_hash(token),
                    session,
                    str(case_id),
                    row["token_hash"],
                    stamp(expiry),
                ),
            )
        return AccountToken(token=token, expires_at=expiry)

    def sign_out(self, authorization):
        session = _session_hash(authorization)
        with self.store.transaction(write=True) as db:
            db.execute("DELETE FROM customer_sessions WHERE token_hash=?", (session,))
