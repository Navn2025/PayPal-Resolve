"""Order-scoped Sandbox history and a durable inbox for authenticated events."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4

from .approvals import invalidate_approvals
from .case_workspace import add_exception, auto_resolve, now_text, provider_hold
from .errors import StoreError
from .models import PayPalRefundHistory

HISTORY_MAX_AGE = timedelta(minutes=5)
WEBHOOK_MAX_BYTES = 256 * 1024
REFUND_EVENTS = {
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.REFUND.PENDING",
    "PAYMENT.REFUND.FAILED",
}
REVERSAL = "PAYMENT.CAPTURE.REVERSED"
PAYPAL_HOSTS = {
    "api-m.sandbox.paypal.com",
    "api.sandbox.paypal.com",
    "api-m.paypal.com",
    "api.paypal.com",
}


def _history_row(connection, case):
    return connection.execute(
        "SELECT * FROM paypal_refund_history WHERE merchant_id=? AND capture_id=?",
        (str(case.merchant_id), case.payment.capture_id),
    ).fetchone()


def history_state(connection, case, refunds, capture_verification=None):
    row = _history_row(connection, case)
    if row is None or row["order_id"] != case.order_id:
        return None, False
    data = json.loads(row["snapshot_json"])
    snapshot = PayPalRefundHistory.model_validate(data)
    ledger = {r.refund_id: [format(r.amount, ".2f"), r.status] for r in refunds}
    capture_conflict = capture_verification and (
        capture_verification.checked_at > snapshot.checked_at
        and capture_verification.capture_status != snapshot.capture_status
    )
    current = (
        data["ledger"] == ledger
        and not capture_conflict
        and datetime.now(timezone.utc) - snapshot.checked_at <= HISTORY_MAX_AGE
        and not provider_hold(connection, case.merchant_id, case.payment.capture_id)
    )
    return snapshot, bool(current)


def _digest(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _valid_id(value, *, event=False):
    return (
        isinstance(value, str)
        and re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}" if event else r"[A-Za-z0-9]{1,64}", value
        )
        is not None
    )


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError("Invalid JSON constant")


def _event_hint(event):
    kind = event["event_type"]
    resource = event.get("resource")
    if not isinstance(resource, dict):
        return None, None
    resource_id = resource.get("id")
    resource_id = resource_id if _valid_id(resource_id) else None
    if kind == REVERSAL:
        # The v2 reversal resource is the capture.
        return resource_id, None
    if kind not in REFUND_EVENTS:
        return None, None
    links = resource.get("links", [])
    parents = set()
    for link in links if isinstance(links, list) else []:
        if (
            not isinstance(link, dict)
            or link.get("rel") != "up"
            or not isinstance(link.get("href"), str)
        ):
            continue
        try:
            url = urlsplit(link["href"])
        except ValueError:
            continue
        match = re.fullmatch(r"/v2/payments/captures/([A-Za-z0-9]{1,64})/?", url.path)
        if (
            match
            and url.scheme == "https"
            and url.netloc in PAYPAL_HOSTS
            and not url.query
            and not url.fragment
        ):
            parents.add(match[1])
    if event.get("resource_type") == "capture":
        return resource_id, None
    if len(parents) != 1:
        return None, resource_id
    return parents.pop(), resource_id


class PayPalHistoryService:
    def __init__(self, store, paypal):
        self.store = store
        self.paypal = paypal

    def refresh(self, case_id, merchant_id, *, expected_refund_id=None):
        with self.store.transaction() as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            previous = _history_row(connection, case)
            revision = previous["revision"] if previous else None
            initial_basis = self.store._reconcile(connection, case).state_fingerprint
        self.paypal._configuration_for(case)
        source = "paypal-history:" + case.payment.capture_id
        try:
            capture, refunds = self.paypal.read_refund_history(case)
            if expected_refund_id and expected_refund_id not in {r.id for r in refunds}:
                raise StoreError(
                    409, "Signed refund is not yet in the PayPal order history"
                )
            with self.store.transaction(write=True) as connection:
                current = self.store._require_case(connection, case_id, merchant_id)
                latest = _history_row(connection, current)
                if (
                    latest["revision"] if latest else None
                ) != revision or self.store._reconcile(
                    connection, current
                ).state_fingerprint != initial_basis:
                    raise StoreError(
                        409,
                        "Case evidence changed while PayPal history was read; retry",
                    )
                result = self._project(connection, current, capture, refunds, latest)
                auto_resolve(
                    connection,
                    merchant_id,
                    source,
                    "Order and provider refund records reconciled",
                )
                self._clear_reconciled_events(connection, current, result)
                return result, capture
        except StoreError as error:
            # An overlapping successful refresh wins; do not replace it with a stale exception.
            if error.status_code in (404, 409, 422, 502):
                with self.store.transaction(write=True) as connection:
                    current = self.store._require_case(connection, case_id, merchant_id)
                    latest = _history_row(connection, current)
                    if (latest["revision"] if latest else None) == revision and (
                        self.store._reconcile(connection, current).state_fingerprint
                        == initial_basis
                    ):
                        add_exception(
                            connection,
                            merchant_id,
                            source,
                            "paypal_history_conflict",
                            case=current,
                            blocking=True,
                        )
            raise

    @staticmethod
    def _clear_reconciled_events(connection, case, history):
        rows = connection.execute(
            """SELECT event_id,refund_id FROM paypal_webhook_events
               WHERE merchant_id=? AND capture_id=? AND status='exception' AND event_type!=?""",
            (str(case.merchant_id), case.payment.capture_id, REVERSAL),
        ).fetchall()
        for row in rows:
            if row["refund_id"] is None or row["refund_id"] in history.refund_ids:
                auto_resolve(
                    connection,
                    case.merchant_id,
                    "paypal-webhook:" + row["event_id"],
                    "Verified PayPal order history accounts for this event",
                )
                connection.execute(
                    "UPDATE paypal_webhook_events SET status='processed' WHERE merchant_id=? AND event_id=?",
                    (str(case.merchant_id), row["event_id"]),
                )

    def _project(self, connection, case, capture, refunds, previous):
        merchant_id, capture_id = case.merchant_id, case.payment.capture_id
        existing = self.store._payment_refunds(connection, capture_id, merchant_id)
        by_id = {r.id: r for r in refunds}
        if any(r.refund_id not in by_id for r in existing):
            raise StoreError(
                409, "Local refund records are missing from the verified PayPal history"
            )
        latest = {
            r.refund_id: r
            for r in self.store._refund_verifications(
                connection, capture_id, merchant_id, latest=True
            )
        }
        # Release failed pending reservations before applying new financial records.
        for refund in sorted(
            refunds, key=lambda r: r.status not in ("FAILED", "CANCELLED")
        ):
            old = latest.get(refund.id)
            if (
                old
                and old.provider_status == refund.status
                and old.amount == refund.amount.value
            ):
                continue
            self.store._record_provider_refund(connection, case, refund)
        status_map = {
            "PENDING": "pending",
            "COMPLETED": "completed",
            "FAILED": "failed",
            "CANCELLED": "failed",
        }
        ledger = {
            r.id: [format(r.amount.value, ".2f"), status_map[r.status]] for r in refunds
        }
        completed = sum(
            (r.amount.value for r in refunds if r.status == "COMPLETED"),
            Decimal("0.00"),
        )
        pending = sum(
            (r.amount.value for r in refunds if r.status == "PENDING"), Decimal("0.00")
        )
        identity = self.paypal.history_identity()
        digest = _digest(
            [
                identity,
                case.order_id,
                capture_id,
                capture.status,
                format(capture.amount.value, ".2f"),
                ledger,
            ]
        )
        result = PayPalRefundHistory(
            order_id=case.order_id,
            capture_id=capture_id,
            capture_status=capture.status,
            checked_at=now_text(),
            digest=digest,
            refund_ids=sorted(by_id),
            completed_amount=completed,
            pending_amount=pending,
            remaining_amount=capture.amount.value - completed - pending,
        )
        if previous is None or previous["digest"] != digest:
            invalidate_approvals(
                connection,
                merchant_id,
                capture_id,
                "Verified PayPal refund history changed",
            )
        connection.execute(
            """INSERT INTO paypal_refund_history
               (merchant_id,capture_id,revision,digest,order_id,identity_hash,checked_at,snapshot_json)
               VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(merchant_id,capture_id) DO UPDATE SET
               revision=excluded.revision,digest=excluded.digest,order_id=excluded.order_id,
               identity_hash=excluded.identity_hash,checked_at=excluded.checked_at,snapshot_json=excluded.snapshot_json""",
            (
                str(merchant_id),
                capture_id,
                str(uuid4()),
                digest,
                case.order_id,
                identity,
                result.checked_at.isoformat(),
                json.dumps({**result.model_dump(mode="json"), "ledger": ledger}),
            ),
        )
        return result

    def receive(self, headers, raw):
        try:
            event = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_constant,
            )
            if not isinstance(event, dict) or not _valid_id(
                event.get("id"), event=True
            ):
                raise ValueError
            if not isinstance(event.get("event_type"), str) or not re.fullmatch(
                r"[A-Z0-9._]{1,100}", event["event_type"]
            ):
                raise ValueError
        except (ValueError, RecursionError):
            raise StoreError(400, "Malformed PayPal webhook event") from None
        self.paypal.verify_webhook(headers, raw)
        merchant_id = self.paypal.settings.paypal_resolve_merchant_id
        capture_id, refund_id = _event_hint(event)
        relevant = (
            event["event_type"] in REFUND_EVENTS or event["event_type"] == REVERSAL
        )
        digest = hashlib.sha256(raw).hexdigest()
        now = now_text()
        with self.store.transaction(write=True) as connection:
            self.store._require_merchant(connection, merchant_id)
            previous = connection.execute(
                "SELECT payload_sha256 FROM paypal_webhook_events WHERE merchant_id=? AND event_id=?",
                (str(merchant_id), event["id"]),
            ).fetchone()
            if previous:
                if previous["payload_sha256"] != digest:
                    raise StoreError(
                        409, "Verified PayPal event ID has a conflicting payload"
                    )
                return
            connection.execute(
                """INSERT INTO paypal_webhook_events
                   (merchant_id,event_id,payload_sha256,event_type,capture_id,refund_id,received_at,status,next_attempt_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(merchant_id),
                    event["id"],
                    digest,
                    event["event_type"],
                    capture_id,
                    refund_id,
                    now,
                    "queued" if relevant else "ignored",
                    now,
                ),
            )
            if relevant and capture_id:
                invalidate_approvals(
                    connection,
                    merchant_id,
                    capture_id,
                    "Signed PayPal event awaiting reconciliation",
                )

    def process(self, merchant_id, limit, *, now=None):
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat(timespec="microseconds")
        counts = {"processed": 0, "retrying": 0, "exceptions": 0}
        for _ in range(limit):
            with self.store.transaction(write=True) as connection:
                event = connection.execute(
                    """SELECT * FROM paypal_webhook_events WHERE merchant_id=? AND status='queued'
                       AND next_attempt_at<=? ORDER BY next_attempt_at,event_id LIMIT 1""",
                    (str(merchant_id), stamp),
                ).fetchone()
                if event is None:
                    break
                attempt = event["attempts"] + 1
                connection.execute(
                    """UPDATE paypal_webhook_events SET attempts=?,next_attempt_at=?
                       WHERE merchant_id=? AND event_id=?""",
                    (
                        attempt,
                        (now + timedelta(minutes=30)).isoformat(
                            timespec="microseconds"
                        ),
                        str(merchant_id),
                        event["event_id"],
                    ),
                )
                case_row = connection.execute(
                    """SELECT id FROM cases WHERE merchant_id=? AND capture_id=?
                       ORDER BY closed_at IS NOT NULL,rowid LIMIT 1""",
                    (str(merchant_id), event["capture_id"]),
                ).fetchone()
            capture_id = event["capture_id"]
            reason = None
            try:
                if (
                    not capture_id
                    and event["refund_id"]
                    and event["event_type"] in REFUND_EVENTS
                ):
                    links = self.paypal.read_webhook_refund_links(event["refund_id"])
                    capture_id, _ = _event_hint(
                        {
                            "event_type": event["event_type"],
                            "resource": {"id": event["refund_id"], "links": links},
                        }
                    )
                    if capture_id:
                        with self.store.transaction(write=True) as connection:
                            connection.execute(
                                "UPDATE paypal_webhook_events SET capture_id=? WHERE merchant_id=? AND event_id=?",
                                (capture_id, str(merchant_id), event["event_id"]),
                            )
                            invalidate_approvals(
                                connection,
                                merchant_id,
                                capture_id,
                                "Signed PayPal event awaiting reconciliation",
                            )
                            case_row = connection.execute(
                                """SELECT id FROM cases WHERE merchant_id=? AND capture_id=?
                                   ORDER BY closed_at IS NOT NULL,rowid LIMIT 1""",
                                (str(merchant_id), capture_id),
                            ).fetchone()
                if event["event_type"] == REVERSAL:
                    reason = "paypal_capture_reversed"
                elif not case_row:
                    reason = "paypal_event_without_matching_case"
                else:
                    self.refresh(
                        case_row["id"],
                        merchant_id,
                        expected_refund_id=event["refund_id"],
                    )
            except StoreError:
                reason = "paypal_event_history_unconfirmed"
            source = "paypal-webhook:" + event["event_id"]
            with self.store.transaction(write=True) as connection:
                if reason is None:
                    state, key = "processed", "processed"
                    auto_resolve(
                        connection, merchant_id, source, "PayPal event reconciled"
                    )
                elif reason == "paypal_event_history_unconfirmed" and attempt < 5:
                    state, key = "queued", "retrying"
                else:
                    state, key = "exception", "exceptions"
                    case = (
                        self.store._require_case(
                            connection, case_row["id"], merchant_id
                        )
                        if case_row
                        else None
                    )
                    add_exception(
                        connection,
                        merchant_id,
                        source,
                        reason,
                        case=case,
                        capture_id=capture_id,
                        blocking=bool(capture_id),
                    )
                connection.execute(
                    """UPDATE paypal_webhook_events SET status=?,next_attempt_at=?
                       WHERE merchant_id=? AND event_id=? AND attempts=?""",
                    (
                        state,
                        (now + timedelta(seconds=min(300, 10 * 2**attempt))).isoformat(
                            timespec="microseconds"
                        ),
                        str(merchant_id),
                        event["event_id"],
                        attempt,
                    ),
                )
            counts[key] += 1
        return counts
