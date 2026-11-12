"""Case-scoped customer access and a separate, explicitly shared conversation."""

from app.schemas.customer_portal import (
    CustomerCase as CustomerCase,
    CustomerMessageCreate as CustomerMessageCreate,
    IssuedLink as IssuedLink,
    LinkCreate as LinkCreate,
    LinkStatus as LinkStatus,
    MessageCreate as MessageCreate,
    PortalCredentials as PortalCredentials,
    PortalMessage as PortalMessage,
    PublicPromise as PublicPromise,
    PublicRefund as PublicRefund,
    RemedyKind as RemedyKind,
)


from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
from uuid import uuid4


from app.core.exceptions import StoreError
from app.services.customer.notifications import enqueue_reply
from app.services.customer.evidence import evidence_list
from app.services.customer.progress import customer_progress
from app.services.resolution.workspace import ResolutionWorkspace


LINK_LIFETIME = timedelta(days=7)
MESSAGE_LIMIT = 100
TOKEN_PATTERN = re.compile(r"(?:rsvp|rint|racp)_[A-Za-z0-9_-]{43}")
INACTIVE_LINK = "This customer link is invalid, expired, or revoked."


def _timestamp(value):
    return value.isoformat(timespec="microseconds")


class CustomerPortal:
    def __init__(self, store):
        self.store = store
        self.workspace = ResolutionWorkspace(store)

    @staticmethod
    def _status(row, now):
        return LinkStatus(
            active=bool(
                row
                and row["revoked_at"] is None
                and row["expires_at"] > _timestamp(now)
            ),
            expires_at=row["expires_at"] if row else None,
            title=row["title"] if row else None,
            show_order_reference=bool(row and row["show_order_reference"]),
        )

    @staticmethod
    def _link(connection, case):
        return connection.execute(
            "SELECT * FROM customer_portal_links WHERE resolution_id=? AND merchant_id=?",
            (case["id"], case["merchant_id"]),
        ).fetchone()

    def status(self, case_id, merchant_id):
        with self.store.transaction() as connection:
            case = self.workspace._case(connection, case_id, merchant_id)
            return self._status(
                self._link(connection, case), datetime.now(timezone.utc)
            )

    def issue(self, case_id, merchant_id, payload):
        with self.store.transaction(write=True) as connection:
            case = self.workspace._case(connection, case_id, merchant_id)
            return self._issue(connection, case, payload)

    @staticmethod
    def _issue(connection, case, payload):
        now = datetime.now(timezone.utc)
        token = "rsvp_" + secrets.token_urlsafe(32)
        connection.execute(
            """INSERT INTO customer_portal_links
               (resolution_id,merchant_id,token_hash,title,show_order_reference,created_at,expires_at)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT(resolution_id) DO UPDATE SET
               token_hash=excluded.token_hash, title=excluded.title,
               show_order_reference=excluded.show_order_reference, created_at=excluded.created_at,
               expires_at=excluded.expires_at, revoked_at=NULL""",
            (
                case["id"],
                case["merchant_id"],
                sha256(token.encode()).hexdigest(),
                payload.title,
                int(payload.show_order_reference),
                _timestamp(now),
                _timestamp(now + LINK_LIFETIME),
            ),
        )
        return IssuedLink(
            token=token,
            **CustomerPortal._status(
                CustomerPortal._link(connection, case), now
            ).model_dump(),
        )

    def revoke(self, case_id, merchant_id):
        with self.store.transaction(write=True) as connection:
            case = self.workspace._case(connection, case_id, merchant_id)
            now = datetime.now(timezone.utc)
            connection.execute(
                """UPDATE customer_portal_links SET revoked_at=? WHERE resolution_id=?
                   AND merchant_id=? AND revoked_at IS NULL""",
                (_timestamp(now), case["id"], case["merchant_id"]),
            )
            return self._status(self._link(connection, case), now)

    @staticmethod
    def _authorized_link(connection, secret):
        token = secret.get_secret_value()
        if not TOKEN_PATTERN.fullmatch(token):
            raise StoreError(404, INACTIVE_LINK)
        now = _timestamp(datetime.now(timezone.utc))
        digest = sha256(token.encode()).hexdigest()
        if token.startswith("racp_"):
            row = connection.execute(
                """SELECT l.resolution_id,l.merchant_id,l.title,l.show_order_reference,a.expires_at
                   FROM customer_account_links a JOIN customer_sessions s ON s.token_hash=a.session_hash
                   JOIN customer_case_contacts c ON c.resolution_id=a.resolution_id AND c.email=s.email
                   JOIN customer_portal_links l ON l.resolution_id=a.resolution_id AND l.token_hash=a.parent_hash
                   WHERE a.token_hash=? AND a.expires_at>? AND s.expires_at>? AND l.revoked_at IS NULL""",
                (digest, now, now),
            ).fetchone()
        else:
            row = connection.execute(
                """SELECT * FROM customer_portal_links WHERE token_hash=? AND revoked_at IS NULL
               AND expires_at>?""",
                (digest, now),
            ).fetchone()
        if row is None:
            raise StoreError(404, INACTIVE_LINK)
        return row

    @staticmethod
    def _messages(connection, case):
        return [
            PortalMessage.model_validate(dict(row))
            for row in connection.execute(
                """SELECT id,sender,body,created_at FROM customer_portal_messages
               WHERE resolution_id=? AND merchant_id=? ORDER BY sequence""",
                (case["id"], case["merchant_id"]),
            )
        ]

    def merchant_messages(self, case_id, merchant_id):
        with self.store.transaction() as connection:
            case = self.workspace._case(connection, case_id, merchant_id)
            return self._messages(connection, case)

    def read(self, secret):
        with self.store.transaction() as connection:
            link = self._authorized_link(connection, secret)
            case = self.workspace._case(
                connection, link["resolution_id"], link["merchant_id"]
            )
            view = self.workspace._view(connection, case)
            timeline, next_step = customer_progress(connection, self.store, case, view)
            refund = next(
                (
                    item.refund_progress
                    for item in view.promises
                    if item.refund_progress
                ),
                None,
            )
            return CustomerCase(
                title=link["title"],
                order_reference=view.order_reference
                if link["show_order_reference"]
                else None,
                outcome=view.outcome,
                expires_at=link["expires_at"],
                promises=[
                    PublicPromise(
                        kind=item.terms.target.kind,
                        promise=item.terms.promise,
                        outcome=item.outcome,
                        due_at=item.terms.due_at,
                        provider_confirmed=item.evidence_source == "provider_confirmed"
                        and item.outcome == "fulfilled",
                    )
                    for item in view.promises
                ],
                refund=PublicRefund(
                    promised_amount=refund.promised_amount,
                    confirmed_amount=refund.provider_completed_amount
                    if refund.history_current
                    else None,
                    pending_amount=refund.provider_pending_amount
                    if refund.history_current
                    else None,
                    outstanding_amount=refund.outstanding_amount
                    if refund.history_current
                    else None,
                    verification="current" if refund.history_current else "unverified",
                )
                if refund
                else None,
                messages=self._messages(connection, case),
                evidence=evidence_list(connection, case),
                timeline=timeline,
                next_step=next_step,
            )

    @staticmethod
    def _record(connection, case, sender, payload):
        identity = (case["id"], sender, str(payload.request_id))
        previous = connection.execute(
            """SELECT id,sender,body,created_at FROM customer_portal_messages
               WHERE resolution_id=? AND sender=? AND request_id=?""",
            identity,
        ).fetchone()
        if previous is not None:
            if previous["body"] != payload.body:
                raise StoreError(
                    409, "Message request ID was already used with different text."
                )
            return PortalMessage.model_validate(dict(previous))
        now = datetime.now(timezone.utc)
        count = connection.execute(
            "SELECT count(*) FROM customer_portal_messages WHERE resolution_id=?",
            (case["id"],),
        ).fetchone()[0]
        if count >= MESSAGE_LIMIT:
            raise StoreError(409, "This conversation has reached its message limit.")
        if (
            sender == "customer"
            and connection.execute(
                """SELECT count(*) FROM customer_portal_messages WHERE resolution_id=?
               AND sender='customer' AND created_at>=?""",
                (case["id"], _timestamp(now - timedelta(minutes=1))),
            ).fetchone()[0]
            >= 6
        ):
            raise StoreError(429, "Too many messages. Wait a minute and try again.")
        message = PortalMessage(
            id=uuid4(), sender=sender, body=payload.body, created_at=now
        )
        connection.execute(
            """INSERT INTO customer_portal_messages
               (id,resolution_id,merchant_id,sender,request_id,body,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                str(message.id),
                case["id"],
                case["merchant_id"],
                sender,
                str(payload.request_id),
                message.body,
                _timestamp(now),
            ),
        )
        return message

    def customer_send(self, payload):
        with self.store.transaction(write=True) as connection:
            link = self._authorized_link(connection, payload.token)
            case = self.workspace._case(
                connection, link["resolution_id"], link["merchant_id"]
            )
            previous = connection.execute(
                """SELECT 1 FROM customer_portal_messages WHERE resolution_id=?
                   AND sender='customer' AND request_id=?""",
                (case["id"], str(payload.request_id)),
            ).fetchone()
            message = self._record(connection, case, "customer", payload)
            if not previous:
                connection.execute(
                    """UPDATE resolution_operations SET waiting_on_customer=0,revision=revision+1
                       WHERE resolution_id=? AND merchant_id=? AND waiting_on_customer=1""",
                    (case["id"], case["merchant_id"]),
                )
            return message

    def merchant_send(self, case_id, merchant_id, payload):
        with self.store.transaction(write=True) as connection:
            case = self.workspace._case(connection, case_id, merchant_id)
            message = self._record(connection, case, "merchant", payload)
            enqueue_reply(connection, case, message)
            return message
