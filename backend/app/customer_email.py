"""Transactional delivery queue for optional customer emails."""

from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import re
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import SecretStr

from .customer_smtp import send_smtp, smtp_runtime
from .errors import StoreError

EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
)
MAIL_WINDOW = timedelta(hours=23)
SIGNIN_WINDOW = timedelta(minutes=15)
RESEND_URL = "https://api.resend.com/emails"


def stamp(moment):
    return moment.isoformat(timespec="microseconds")


def token_hash(value):
    return sha256(value.encode()).hexdigest()


def normalize_email(value):
    if (
        not isinstance(value, str)
        or len(value) > 254
        or not EMAIL.fullmatch(value.strip())
    ):
        raise ValueError("Enter a valid email address")
    return value.strip().lower()


@dataclass(frozen=True)
class MailConfig:
    origin: str
    key: bytes = field(repr=False)
    sender: str
    transport: str
    resend_key: SecretStr | None


def mail_config(settings) -> MailConfig:
    if not settings.customer_email_enabled:
        raise StoreError(503, "Customer email is not configured")
    origin = settings.customer_public_origin or ""
    try:
        url = urlsplit(origin)
        port = url.port
    except ValueError:
        raise StoreError(503, "Customer email configuration is invalid") from None
    key = settings.customer_signing_key
    transport = settings.customer_email_transport
    sender = settings.smtp_from if transport == "smtp" else settings.resend_from
    if (
        url.scheme != "https"
        or not url.hostname
        or url.hostname in ("localhost", "127.0.0.1", "::1")
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or port not in (None, 443)
        or not key
        or len(key.get_secret_value()) < 32
        or not sender
        or not EMAIL.fullmatch(sender)
    ):
        raise StoreError(503, "Customer email configuration is invalid")
    if transport == "smtp":
        if (
            not settings.smtp_host
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", settings.smtp_host)
            or not 1 <= settings.smtp_port <= 65535
            or not settings.smtp_user
            or not settings.smtp_password
        ):
            raise StoreError(503, "Customer SMTP configuration is incomplete")
    elif not settings.resend_api_key:
        raise StoreError(503, "Customer Resend configuration is incomplete")
    return MailConfig(
        origin.rstrip("/"),
        key.get_secret_value().encode(),
        sender,
        transport,
        settings.resend_api_key,
    )


def email_available(settings):
    try:
        mail_config(settings)
        return True
    except StoreError:
        return False


def mail_token(key, kind, identifier):
    prefix = {"invite": "rint_", "signin": "rlog_"}[kind]
    digest = hmac.digest(key, (kind + ":" + identifier).encode(), "sha256")
    return prefix + urlsafe_b64encode(digest).decode().rstrip("=")


def enqueue(
    db,
    kind,
    event_key,
    email,
    now,
    *,
    case_id=None,
    identifier=None,
    lifetime=MAIL_WINDOW,
):
    identifier = identifier or str(uuid4())
    db.execute(
        """INSERT INTO customer_mail_outbox
           (id,event_key,kind,recipient,resolution_id,created_at,expires_at,next_attempt_at)
           VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(event_key) DO NOTHING""",
        (
            identifier,
            event_key,
            kind,
            email,
            case_id,
            stamp(now),
            stamp(now + lifetime),
            stamp(now),
        ),
    )


def enqueue_reply(db, case, message):
    contact = db.execute(
        """SELECT c.email FROM customer_case_contacts c JOIN customer_portal_links l
           ON l.resolution_id=c.resolution_id WHERE c.resolution_id=? AND l.revoked_at IS NULL
           AND c.email_notifications=1""",
        (case["id"],),
    ).fetchone()
    if contact:
        enqueue(
            db,
            "reply",
            "reply:" + str(message.id),
            contact["email"],
            message.created_at,
            case_id=case["id"],
        )


def enqueue_verified_refunds(store, now, limit):
    with store.transaction(write=True) as db:
        rows = db.execute(
            """SELECT c.resolution_id,c.email,v.refund_id FROM customer_case_contacts c
               JOIN resolution_cases r ON r.id=c.resolution_id AND r.merchant_id=c.merchant_id
               JOIN customer_portal_links l ON l.resolution_id=r.id AND l.revoked_at IS NULL
               JOIN cases p ON p.id=r.refund_case_id AND p.merchant_id=r.merchant_id
               JOIN paypal_refund_verifications v ON v.merchant_id=p.merchant_id AND v.capture_id=p.capture_id
               WHERE c.email_notifications=1 AND v.provider_status='COMPLETED'
               AND julianday(v.checked_at)>=julianday(c.created_at)
               AND julianday(v.checked_at)>=julianday(?) AND NOT EXISTS (
                   SELECT 1 FROM paypal_refund_verifications n WHERE n.merchant_id=v.merchant_id
                   AND n.capture_id=v.capture_id AND n.refund_id=v.refund_id AND n.sequence>v.sequence)
               AND EXISTS (SELECT 1 FROM resolution_promises a WHERE a.resolution_id=r.id AND a.kind='refund')
               AND NOT EXISTS (SELECT 1 FROM customer_mail_outbox o
                   WHERE o.event_key='refund:'||r.id||':'||v.refund_id)
               ORDER BY v.sequence LIMIT ?""",
            (stamp(now - MAIL_WINDOW), limit),
        ).fetchall()
        for row in rows:
            case_id = row["resolution_id"]
            enqueue(
                db,
                "refund",
                "refund:" + case_id + ":" + row["refund_id"],
                row["email"],
                now,
                case_id=case_id,
            )
        return len(rows)


def _mail(row, origin, key, sender):
    kind = row["kind"]
    if kind == "invite":
        subject, copy = (
            "Your private Resolve support link",
            "Open this private link to report an issue with your order:",
        )
        url = origin + "/customer#" + mail_token(key, kind, row["id"])
    elif kind == "signin":
        subject, copy = (
            "Sign in to Resolve",
            "Use this single-use link within 15 minutes to open My cases:",
        )
        url = origin + "/customer/account#" + mail_token(key, kind, row["id"])
    else:
        subject = (
            "A merchant replied in Resolve"
            if kind == "reply"
            else "PayPal confirmed a refund"
        )
        copy = subject + ". Sign in to My cases to see the latest update:"
        url = origin + "/customer/account"
    return {
        "from": sender,
        "to": [row["recipient"]],
        "subject": subject,
        "text": copy + "\n\n" + url,
    }


def _claim(store, now, transport):
    with store.transaction(write=True) as db:
        db.execute(
            "UPDATE customer_mail_outbox SET status='failed',lease_id=NULL WHERE status='queued' AND expires_at<=?",
            (stamp(now),),
        )
        db.execute(
            """UPDATE customer_mail_outbox SET status='failed',lease_id=NULL
               WHERE status='queued' AND delivery_transport='smtp' AND lease_id IS NOT NULL AND next_attempt_at<=?""",
            (stamp(now),),
        )
        row = db.execute(
            """SELECT * FROM customer_mail_outbox WHERE status='queued' AND next_attempt_at<=?
               AND (delivery_transport IS NULL OR delivery_transport=?)
               ORDER BY next_attempt_at,id LIMIT 1""",
            (stamp(now), transport),
        ).fetchone()
        if row:
            lease = str(uuid4())
            db.execute(
                """UPDATE customer_mail_outbox SET lease_id=?,next_attempt_at=?,attempts=attempts+1,
                   delivery_transport=? WHERE id=?""",
                (lease, stamp(now + timedelta(minutes=1)), transport, row["id"]),
            )
            return row, lease
    return None


def _eligible(store, row, key, now):
    with store.transaction() as db:
        if row["kind"] == "signin":
            return bool(
                db.execute(
                    "SELECT 1 FROM customer_signins WHERE token_hash=? AND consumed_at IS NULL AND expires_at>?",
                    (token_hash(mail_token(key, "signin", row["id"])), stamp(now)),
                ).fetchone()
            )
        if row["kind"] == "invite":
            return bool(
                db.execute(
                    """SELECT 1 FROM customer_intake_invites WHERE token_hash=? AND expires_at>?
                   AND resolution_id IS NULL""",
                    (token_hash(mail_token(key, "invite", row["id"])), stamp(now)),
                ).fetchone()
            )
        return bool(
            db.execute(
                """SELECT 1 FROM customer_case_contacts c JOIN customer_portal_links l ON l.resolution_id=c.resolution_id
               WHERE c.resolution_id=? AND c.email=? AND l.revoked_at IS NULL AND c.email_notifications=1""",
                (row["resolution_id"], row["recipient"]),
            ).fetchone()
        )


def _send_resend(client, config, message, identifier):
    try:
        response = client.post(
            RESEND_URL,
            json=message,
            headers={
                "Authorization": "Bearer " + config.resend_key.get_secret_value(),
                "Idempotency-Key": "resolve/" + identifier,
            },
        )
        if response.is_success:
            data = response.json()
            provider_id = data.get("id") if isinstance(data, dict) else None
            if isinstance(provider_id, str) and 0 < len(provider_id) <= 100:
                return "accepted", provider_id
            return "retry", None
        if response.status_code in (408, 409, 429) or response.status_code >= 500:
            return "retry", None
        return "failed", None
    except (httpx.HTTPError, ValueError):
        return "retry", None


def deliver(store, settings, client: httpx.Client, *, limit=20, now=None):
    config = mail_config(settings)
    node = smtp_runtime() if config.transport == "smtp" else None
    counts = {"accepted": 0, "retry": 0, "failed": 0, "cancelled": 0}
    for _ in range(limit):
        # Refresh wall time each iteration: a previous SMTP attempt may have blocked.
        attempt_at = now or datetime.now(timezone.utc)
        claim = _claim(store, attempt_at, config.transport)
        if not claim:
            break
        row, lease = claim
        status, provider_id = "cancelled", None
        if _eligible(store, row, config.key, attempt_at):
            message = _mail(row, config.origin, config.key, config.sender)
            if node:
                status, provider_id = send_smtp(node, settings, message, row["id"])
            else:
                status, provider_id = _send_resend(client, config, message, row["id"])
        retry_at = attempt_at + timedelta(
            seconds=min(3600, 30 * 2 ** min(row["attempts"], 7))
        )
        if status == "retry" and retry_at >= datetime.fromisoformat(row["expires_at"]):
            status = "failed"
        with store.transaction(write=True) as db:
            updated = db.execute(
                """UPDATE customer_mail_outbox SET status=?,provider_id=?,next_attempt_at=?,lease_id=NULL
                   WHERE id=? AND lease_id=?""",
                (
                    "queued" if status == "retry" else status,
                    provider_id,
                    stamp(retry_at),
                    row["id"],
                    lease,
                ),
            )
            counts[status] += updated.rowcount
    return counts
