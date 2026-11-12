"""One-use order invites. Redeeming an invite never looks up another case."""

from app.schemas.customer_intake import (
    IntakeSubmit as IntakeSubmit,
    IntakeView as IntakeView,
    InviteCreate as InviteCreate,
    InviteIssued as InviteIssued,
    IssueType as IssueType,
)


from datetime import datetime, timezone
from hashlib import sha256
import re
import secrets
from uuid import uuid4


from app.services.customer.notifications import enqueue, mail_config, mail_token

from app.services.customer.portal import CustomerPortal, LINK_LIFETIME, _timestamp
from app.schemas.customer_portal import MessageCreate
from app.core.exceptions import StoreError
from app.integrations.paypal.identity import web_origin


ISSUE_LABELS = {
    "missing_item": "Missing item",
    "duplicate_charge": "Duplicate charge",
    "damaged_delivery": "Damaged delivery",
    "refund_delay": "Refund delay",
    "other": "Order support request",
}
INVITE_PATTERN = re.compile(r"rint_[A-Za-z0-9_-]{43}")


class Intake:
    def __init__(self, store):
        self.store = store
        self.portal = CustomerPortal(store)

    def invite(
        self,
        merchant_id,
        order_reference,
        customer_email=None,
        settings=None,
        *,
        send_email=True,
    ):
        now = datetime.now(timezone.utc)
        identifier = str(uuid4())
        origin = (
            web_origin(settings.customer_public_origin or settings.merchant_web_origin)
            if settings
            else None
        )
        email_queued = bool(customer_email and send_email)
        if email_queued:
            config = mail_config(settings)
            origin = config.origin
            if merchant_id != (
                settings.customer_email_merchant_id
                or settings.paypal_resolve_merchant_id
            ):
                raise StoreError(
                    503, "Customer email is not configured for this merchant"
                )
            token = mail_token(config.key, "invite", identifier)
        else:
            token = "rint_" + secrets.token_urlsafe(32)
        with self.store.transaction(write=True) as db:
            self.store._require_merchant(db, merchant_id)
            db.execute(
                """INSERT INTO customer_intake_invites
                   (token_hash,merchant_id,order_reference,created_at,expires_at,customer_email,email_notifications)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    sha256(token.encode()).hexdigest(),
                    str(merchant_id),
                    order_reference,
                    _timestamp(now),
                    _timestamp(now + LINK_LIFETIME),
                    customer_email,
                    int(email_queued),
                ),
            )
            if email_queued:
                enqueue(
                    db,
                    "invite",
                    "invite:" + identifier,
                    customer_email,
                    now,
                    identifier=identifier,
                )
        return InviteIssued(
            token=token,
            order_reference=order_reference,
            expires_at=now + LINK_LIFETIME,
            email_queued=email_queued,
            public_url=origin + "/customer#" + token if origin else None,
        )

    def _require(self, db, secret):
        token = secret.get_secret_value()
        error = StoreError(404, "This order invite is invalid, expired, or revoked.")
        if not INVITE_PATTERN.fullmatch(token):
            raise error
        row = db.execute(
            "SELECT * FROM customer_intake_invites WHERE token_hash=?",
            (sha256(token.encode()).hexdigest(),),
        ).fetchone()
        if not row:
            raise error
        if row["resolution_id"]:
            self.portal._authorized_link(db, secret)
        elif row["expires_at"] <= _timestamp(datetime.now(timezone.utc)):
            raise error
        return row

    def view(self, secret):
        with self.store.transaction() as db:
            invite = self._require(db, secret)
            return IntakeView(
                order_reference=invite["order_reference"],
                submitted=invite["resolution_id"] is not None,
            )

    def submit(self, payload):
        with self.store.transaction(write=True) as db:
            invite = self._require(db, payload.token)
            if not invite["resolution_id"]:
                now = datetime.now(timezone.utc)
                identifier = str(uuid4())
                title = ISSUE_LABELS[payload.issue_type]
                db.execute(
                    "INSERT INTO resolution_cases VALUES (?,?,?,?,?,?)",
                    (
                        identifier,
                        invite["merchant_id"],
                        None,
                        title,
                        invite["order_reference"],
                        _timestamp(now),
                    ),
                )
                case = self.portal.workspace._case(
                    db, identifier, invite["merchant_id"]
                )
                self.portal.workspace._event(
                    db,
                    case,
                    "case_created",
                    "system",
                    {"note": "Customer submitted an order issue."},
                )
                db.execute(
                    """UPDATE customer_intake_invites SET resolution_id=?,submitted_at=?,issue_type=?
                    WHERE token_hash=?""",
                    (
                        identifier,
                        _timestamp(now),
                        payload.issue_type,
                        invite["token_hash"],
                    ),
                )
                db.execute(
                    """INSERT INTO customer_portal_links
                    (resolution_id,merchant_id,token_hash,title,show_order_reference,created_at,expires_at)
                    VALUES (?,?,?,?,1,?,?)""",
                    (
                        identifier,
                        invite["merchant_id"],
                        invite["token_hash"],
                        title,
                        _timestamp(now),
                        _timestamp(now + LINK_LIFETIME),
                    ),
                )
                if invite["customer_email"]:
                    db.execute(
                        """INSERT INTO customer_case_contacts
                           (resolution_id,merchant_id,email,created_at,email_notifications) VALUES (?,?,?,?,?)""",
                        (
                            identifier,
                            invite["merchant_id"],
                            invite["customer_email"],
                            _timestamp(now),
                            invite["email_notifications"],
                        ),
                    )
                self.portal._record(
                    db,
                    case,
                    "customer",
                    MessageCreate(request_id=uuid4(), body=payload.description),
                )
        return self.portal.read(payload.token)
