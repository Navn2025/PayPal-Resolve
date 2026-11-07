"""Persist exact merchant approval decisions; this module never executes refunds."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from .errors import StoreError
from .models import (
    RefundApproval,
    RefundApprovalCreate,
    RefundApprovalEvent,
    RefundApprovalRevoke,
)

if TYPE_CHECKING:
    from .storage import SQLiteStore


APPROVAL_LIFETIME = timedelta(minutes=15)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _transition(
    connection, approval_id, status, note, actor, now, *, revocation_reason=None
):
    connection.execute(
        """UPDATE refund_approvals SET status = ?, status_reason = ?, updated_at = ?,
           revocation_reason = ? WHERE id = ?""",
        (status, note, _timestamp(now), revocation_reason, str(approval_id)),
    )
    connection.execute(
        """INSERT INTO refund_approval_events
           (approval_id, event_type, actor_merchant_id, note, recorded_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            str(approval_id),
            status,
            str(actor) if actor is not None else None,
            note,
            _timestamp(now),
        ),
    )


def expire_approvals(connection, merchant_id, capture_id, now):
    rows = connection.execute(
        """SELECT id, expires_at FROM refund_approvals
           WHERE merchant_id = ? AND capture_id = ? AND status = 'approved'""",
        (str(merchant_id), capture_id),
    ).fetchall()
    for row in rows:
        if datetime.fromisoformat(row["expires_at"]) <= now:
            _transition(connection, row["id"], "expired", "Approval expired", None, now)


def invalidate_approvals(connection, merchant_id, capture_id, reason):
    now = utc_now()
    expire_approvals(connection, merchant_id, capture_id, now)
    rows = connection.execute(
        """SELECT id FROM refund_approvals WHERE merchant_id = ?
           AND capture_id = ? AND status = 'approved'""",
        (str(merchant_id), capture_id),
    ).fetchall()
    for row in rows:
        _transition(connection, row["id"], "invalidated", reason, merchant_id, now)


class RefundApprovalService:
    def __init__(self, store: "SQLiteStore"):
        self.store = store

    @staticmethod
    def _require_row(connection, case_id, approval_id, merchant_id):
        row = connection.execute(
            """SELECT * FROM refund_approvals
               WHERE id = ? AND case_id = ? AND merchant_id = ?""",
            (str(approval_id), str(case_id), str(merchant_id)),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Refund approval not found")
        return row

    @staticmethod
    def _response(row) -> RefundApproval:
        return RefundApproval(
            id=row["id"],
            merchant_id=row["merchant_id"],
            case_id=row["case_id"],
            request_id=row["request_id"],
            capture_id=row["capture_id"],
            amount=Decimal(row["amount_cents"]).scaleb(-2),
            currency=row["currency"],
            state_fingerprint=row["state_fingerprint"],
            decision_note=row["decision_note"],
            status=row["status"],
            approved_at=row["approved_at"],
            expires_at=row["expires_at"],
            updated_at=row["updated_at"],
            status_reason=row["status_reason"],
            basis=json.loads(row["snapshot_json"])["basis"],
        )

    def create(
        self, case_id: UUID, payload: RefundApprovalCreate, merchant_id: UUID
    ) -> tuple[RefundApproval, bool]:
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            now = utc_now()
            expire_approvals(connection, merchant_id, case.payment.capture_id, now)
            existing = connection.execute(
                "SELECT * FROM refund_approvals WHERE merchant_id = ? AND request_id = ?",
                (str(merchant_id), str(payload.request_id)),
            ).fetchone()
            if existing is not None:
                original = RefundApprovalCreate.model_validate_json(
                    existing["request_json"]
                )
                if existing["case_id"] != str(case_id) or original != payload:
                    raise StoreError(
                        409, "Approval request ID already has different details"
                    )
                return self._response(existing), False

            refunds = self.store._payment_refunds(
                connection, case.payment.capture_id, merchant_id
            )
            history = self.store._condition_history(connection, case_id)
            basis = self.store._reconcile(connection, case)
            if basis.status != "refund_required":
                raise StoreError(409, "Case is not ready for a refund approval")
            if (
                payload.capture_id != case.payment.capture_id
                or payload.currency != case.payment.currency
                or payload.amount != basis.recommended_refund_amount
                or payload.state_fingerprint != basis.state_fingerprint
            ):
                raise StoreError(
                    409, "Approval does not match the current refund recommendation"
                )
            active = connection.execute(
                """SELECT 1 FROM refund_approvals WHERE merchant_id = ?
                   AND capture_id = ? AND status = 'approved'""",
                (str(merchant_id), case.payment.capture_id),
            ).fetchone()
            if active is not None:
                raise StoreError(
                    409, "This payment already has an active refund approval"
                )

            approval_id = uuid4()
            snapshot = {
                "case": case.model_dump(mode="json"),
                "refunds": [refund.model_dump(mode="json") for refund in refunds],
                "condition_checks": [
                    check.model_dump(mode="json") for check in history
                ],
                "basis": basis.model_dump(mode="json"),
            }
            connection.execute(
                """INSERT INTO refund_approvals
                   (id, merchant_id, case_id, capture_id, request_id, amount_cents, currency,
                    state_fingerprint, request_json, snapshot_json, decision_note, status,
                    approved_at, expires_at, updated_at, status_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(approval_id),
                    str(merchant_id),
                    str(case_id),
                    case.payment.capture_id,
                    str(payload.request_id),
                    int(payload.amount * 100),
                    payload.currency,
                    payload.state_fingerprint,
                    payload.model_dump_json(),
                    json.dumps(snapshot),
                    payload.decision_note,
                    "approved",
                    _timestamp(now),
                    _timestamp(now + APPROVAL_LIFETIME),
                    _timestamp(now),
                    "Merchant approved",
                ),
            )
            connection.execute(
                """INSERT INTO refund_approval_events
                   (approval_id, event_type, actor_merchant_id, note, recorded_at)
                   VALUES (?, 'approved', ?, ?, ?)""",
                (
                    str(approval_id),
                    str(merchant_id),
                    payload.decision_note,
                    _timestamp(now),
                ),
            )
            return self._response(
                self._require_row(connection, case_id, approval_id, merchant_id)
            ), True

    def list(self, case_id: UUID, merchant_id: UUID) -> list[RefundApproval]:
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            expire_approvals(
                connection, merchant_id, case.payment.capture_id, utc_now()
            )
            rows = connection.execute(
                """SELECT * FROM refund_approvals WHERE case_id = ? AND merchant_id = ?
                   ORDER BY approved_at, id""",
                (str(case_id), str(merchant_id)),
            ).fetchall()
            return [self._response(row) for row in rows]

    def get(
        self, case_id: UUID, approval_id: UUID, merchant_id: UUID
    ) -> RefundApproval:
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            self._require_row(connection, case_id, approval_id, merchant_id)
            expire_approvals(
                connection, merchant_id, case.payment.capture_id, utc_now()
            )
            return self._response(
                self._require_row(connection, case_id, approval_id, merchant_id)
            )

    def revoke(
        self,
        case_id: UUID,
        approval_id: UUID,
        payload: RefundApprovalRevoke,
        merchant_id: UUID,
    ) -> RefundApproval:
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            self._require_row(connection, case_id, approval_id, merchant_id)
            now = utc_now()
            claimed = connection.execute(
                "SELECT 1 FROM refund_executions WHERE approval_id = ?",
                (str(approval_id),),
            ).fetchone()
            if claimed:
                raise StoreError(
                    409, "This approval has already been claimed for execution"
                )
            expire_approvals(connection, merchant_id, case.payment.capture_id, now)
            row = self._require_row(connection, case_id, approval_id, merchant_id)
            if (
                row["status"] == "revoked"
                and row["revocation_reason"] == payload.reason
            ):
                return self._response(row)
            if row["status"] != "approved":
                raise StoreError(409, "Only active approvals can be revoked")
            _transition(
                connection,
                approval_id,
                "revoked",
                payload.reason,
                merchant_id,
                now,
                revocation_reason=payload.reason,
            )
            return self._response(
                self._require_row(connection, case_id, approval_id, merchant_id)
            )

    def events(
        self, case_id: UUID, approval_id: UUID, merchant_id: UUID
    ) -> list[RefundApprovalEvent]:
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            self._require_row(connection, case_id, approval_id, merchant_id)
            expire_approvals(
                connection, merchant_id, case.payment.capture_id, utc_now()
            )
            rows = connection.execute(
                "SELECT * FROM refund_approval_events WHERE approval_id = ? ORDER BY sequence",
                (str(approval_id),),
            ).fetchall()
            return [RefundApprovalEvent(**dict(row)) for row in rows]
