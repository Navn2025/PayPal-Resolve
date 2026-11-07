"""Resolve repository and its local SQLite transaction implementation."""

import sqlite3
import json
import hashlib
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4
from pydantic import ValidationError

from .models import (
    CaseCreate,
    CaseResponse,
    ConditionCheck,
    ConditionCheckCreate,
    ReconciliationResponse,
    RefundCommitment,
    RefundRecord,
    RefundStatusUpdate,
    MerchantCreate,
    MerchantIdentity,
    PayPalCaptureVerification,
    PayPalRefundVerification,
    CasePage,
    CommitmentUpdate,
    CaseTimelineEntry,
    CaseTimelinePage,
)
from .paypal import PayPalCaptureDetails, PayPalRefundDetails
from .reconciliation import reconcile_case, validate_refund_record
from .approvals import invalidate_approvals
from .errors import StoreError
from .case_workspace import provider_hold, require_open
from .paypal_history import history_state
from .resolution_state import refund_promise_gate


LEGACY_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000000")
_SQLITE_FORWARD_ADDITIONS = {
    "015_merchant_paypal_flow_claim.sql": (("merchant_paypal_flows", "claimed_at"),),
    "017_customer_email_notifications.sql": (
        ("customer_intake_invites", "email_notifications"),
        ("customer_case_contacts", "email_notifications"),
    ),
}


def _already_added(connection, migration, statement):
    # SQLite lacks ADD COLUMN IF NOT EXISTS. Skip only the exact forward
    # additions that some databases already received from an interim script.
    return any(
        statement.lstrip().startswith(f"ALTER TABLE {table} ADD COLUMN {column} ")
        and connection.execute(
            "SELECT 1 FROM pragma_table_info(?) WHERE name=?", (table, column)
        ).fetchone()
        for table, column in _SQLITE_FORWARD_ADDITIONS.get(migration, ())
    )


@dataclass
class IssuedMerchantKey:
    merchant: MerchantIdentity
    key_id: UUID
    api_key: str = field(repr=False)


def to_cents(amount: Decimal) -> int:
    return int(amount * 100)


def from_cents(amount: int) -> Decimal:
    return (Decimal(amount) / 100).quantize(Decimal("0.01"))


class _SQLiteTransactions:
    def __init__(self, path: Path, timeout: float = 5.0):
        self.path = Path(path).resolve()
        self.timeout = timeout

    @contextmanager
    def transaction(self, *, write: bool = False):
        connection = sqlite3.connect(
            self.path, timeout=self.timeout, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.OperationalError as error:
            connection.rollback()
            if error.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise StoreError(503, "Database is busy; retry the request") from error
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        directory = Path(__file__).resolve().parent.parent / "migrations"
        migrations = [
            directory / "001_initial.sql",
            directory / "002_merchants.sql",
            directory / "003_refund_approvals.sql",
            directory / "004_capture_verifications.sql",
            directory / "005_refund_executions.sql",
            directory / "006_execution_identity.sql",
            directory / "007_case_events.sql",
            directory / "008_refund_history_and_case_lifecycle.sql",
            directory / "009_resolution_workspace.sql",
            directory / "010_customer_portal.sql",
            directory / "011_customer_intake_and_triage.sql",
            directory / "012_hosted_followup.sql",
            directory / "013_case_order.sql",
            directory / "014_merchant_web_auth.sql",
            directory / "015_merchant_paypal_flow_claim.sql",
            directory / "016_customer_google_and_smtp.sql",
            directory / "017_customer_email_notifications.sql",
            directory / "018_resolution_evidence_sdk.sql",
        ]
        with self.transaction(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in range(len(migrations) + 1):
                raise RuntimeError(f"Unsupported database schema version: {version}")
            for index in range(version, len(migrations)):
                migration = migrations[index]
                statement = ""
                for line in migration.read_text(encoding="utf-8").splitlines(True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        if not _already_added(connection, migration.name, statement):
                            connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise RuntimeError(
                        f"Incomplete migration: {migration.name}"
                    )
                connection.execute(f"PRAGMA user_version = {index + 1}")


class ResolveStore:
    def initialize(self) -> None:
        raise NotImplementedError

    def transaction(self, *, write: bool = False):
        raise NotImplementedError

    @staticmethod
    def _require_merchant(connection, merchant_id: UUID) -> MerchantIdentity:
        if merchant_id == LEGACY_MERCHANT_ID:
            raise StoreError(404, "Merchant not found")
        row = connection.execute(
            "SELECT * FROM merchants WHERE id = ?", (str(merchant_id),)
        ).fetchone()
        if row is None:
            raise StoreError(404, "Merchant not found")
        return MerchantIdentity(
            id=row["id"], name=row["name"], created_at=row["created_at"]
        )

    @staticmethod
    def _issue_key(connection, merchant: MerchantIdentity) -> IssuedMerchantKey:
        api_key = "rslv_" + secrets.token_urlsafe(32)
        key_id = uuid4()
        connection.execute(
            """INSERT INTO merchant_api_keys
               (id, merchant_id, token_hash, created_at) VALUES (?, ?, ?, ?)""",
            (
                str(key_id),
                str(merchant.id),
                hashlib.sha256(api_key.encode()).hexdigest(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return IssuedMerchantKey(merchant=merchant, key_id=key_id, api_key=api_key)

    def create_merchant(self, name: str) -> IssuedMerchantKey:
        validated = MerchantCreate(name=name)
        merchant = MerchantIdentity(
            id=uuid4(), name=validated.name, created_at=datetime.now(timezone.utc)
        )
        with self.transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO merchants VALUES (?, ?, ?)",
                (str(merchant.id), merchant.name, merchant.created_at.isoformat()),
            )
            return self._issue_key(connection, merchant)

    def issue_key(self, merchant_id: UUID) -> IssuedMerchantKey:
        with self.transaction(write=True) as connection:
            return self._issue_key(
                connection, self._require_merchant(connection, merchant_id)
            )

    def authenticate(self, api_key: str) -> MerchantIdentity | None:
        if not api_key.startswith("rslv_") or len(api_key) > 512:
            return None
        digest = hashlib.sha256(api_key.encode()).hexdigest()
        with self.transaction() as connection:
            row = connection.execute(
                """SELECT merchants.* FROM merchant_api_keys
                   JOIN merchants ON merchants.id = merchant_api_keys.merchant_id
                   WHERE token_hash = ? AND revoked_at IS NULL AND merchants.id != ?""",
                (digest, str(LEGACY_MERCHANT_ID)),
            ).fetchone()
            if row is None:
                return None
            return MerchantIdentity(
                id=row["id"], name=row["name"], created_at=row["created_at"]
            )

    def revoke_key(self, key_id: UUID) -> None:
        with self.transaction(write=True) as connection:
            result = connection.execute(
                """UPDATE merchant_api_keys SET revoked_at = COALESCE(revoked_at, ?)
                   WHERE id = ?""",
                (datetime.now(timezone.utc).isoformat(), str(key_id)),
            )
            if result.rowcount == 0:
                raise StoreError(404, "Key not found")

    def claim_legacy(self, merchant_id: UUID) -> dict[str, int]:
        """Trusted local admin operation; never called by an HTTP endpoint."""
        with self.transaction(write=True) as connection:
            self._require_merchant(connection, merchant_id)
            for table, identifier in (
                ("captures", "capture_id"),
                ("refunds", "refund_id"),
            ):
                conflict = connection.execute(
                    f"""SELECT 1 FROM {table} AS old JOIN {table} AS target
                        ON old.{identifier} = target.{identifier}
                        WHERE old.merchant_id = ? AND target.merchant_id = ? LIMIT 1""",
                    (str(LEGACY_MERCHANT_ID), str(merchant_id)),
                ).fetchone()
                if conflict is not None:
                    raise StoreError(
                        409, "Target merchant has conflicting capture or refund IDs"
                    )
            counts = {
                table: connection.execute(
                    f"SELECT count(*) FROM {table} WHERE merchant_id = ?",
                    (str(LEGACY_MERCHANT_ID),),
                ).fetchone()[0]
                for table in ("captures", "cases", "refunds")
            }
            # Composite foreign keys cascade ownership to cases and refunds.
            connection.execute(
                "UPDATE captures SET merchant_id = ? WHERE merchant_id = ?",
                (str(merchant_id), str(LEGACY_MERCHANT_ID)),
            )
            return counts

    @staticmethod
    def _require_case(connection, case_id: UUID, merchant_id: UUID) -> CaseResponse:
        row = connection.execute(
            """SELECT cases.*, captures.captured_cents, captures.currency
               FROM cases JOIN captures ON cases.merchant_id = captures.merchant_id
               AND cases.capture_id = captures.capture_id
               WHERE cases.id = ? AND cases.merchant_id = ?""",
            (str(case_id), str(merchant_id)),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Case not found")
        return CaseResponse(
            id=row["id"],
            merchant_id=row["merchant_id"],
            order_id=row["order_id"],
            complaint=row["complaint"],
            status="closed" if row["closed_at"] else row["status"],
            payment={
                "capture_id": row["capture_id"],
                "captured_amount": from_cents(row["captured_cents"]),
                "currency": row["currency"],
            },
            commitment=(
                RefundCommitment.model_validate_json(row["commitment_json"])
                if row["commitment_json"] is not None
                else None
            ),
        )

    @staticmethod
    def _refund_from_row(row) -> RefundRecord:
        return RefundRecord(
            refund_id=row["refund_id"],
            capture_id=row["capture_id"],
            amount=from_cents(row["amount_cents"]),
            currency=row["currency"],
            status=row["status"],
        )

    def _payment_refunds(
        self, connection, capture_id: str, merchant_id: UUID
    ) -> list[RefundRecord]:
        rows = connection.execute(
            """SELECT * FROM refunds WHERE capture_id = ? AND merchant_id = ?
               ORDER BY sequence""",
            (capture_id, str(merchant_id)),
        ).fetchall()
        return [self._refund_from_row(row) for row in rows]

    @staticmethod
    def _condition_history(connection, case_id: UUID) -> list[ConditionCheck]:
        rows = connection.execute(
            "SELECT * FROM condition_checks WHERE case_id = ? ORDER BY sequence",
            (str(case_id),),
        ).fetchall()
        return [
            ConditionCheck(
                status=row["status"],
                evidence_note=row["evidence_note"],
                recorded_at=row["recorded_at"],
                recorded_by_merchant_id=row["recorded_by_merchant_id"],
            )
            for row in rows
        ]

    def create_case(self, payload: CaseCreate, merchant_id: UUID) -> CaseResponse:
        with self.transaction(write=True) as connection:
            self._require_merchant(connection, merchant_id)
            payment = payload.payment
            existing = connection.execute(
                "SELECT * FROM captures WHERE capture_id = ? AND merchant_id = ?",
                (payment.capture_id, str(merchant_id)),
            ).fetchone()
            if existing is not None:
                if (
                    existing["captured_cents"] != to_cents(payment.captured_amount)
                    or existing["currency"] != payment.currency
                ):
                    raise StoreError(
                        409, "Cases sharing a capture must agree on payment details"
                    )
            else:
                connection.execute(
                    "INSERT INTO captures VALUES (?, ?, ?, ?)",
                    (
                        str(merchant_id),
                        payment.capture_id,
                        to_cents(payment.captured_amount),
                        payment.currency,
                    ),
                )
            case_id = uuid4()
            connection.execute(
                """INSERT INTO cases
                   (id, merchant_id, order_id, complaint, capture_id, commitment_json, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(case_id),
                    str(merchant_id),
                    payload.order_id,
                    payload.complaint,
                    payment.capture_id,
                    payload.commitment.model_dump_json()
                    if payload.commitment
                    else None,
                    "open",
                ),
            )
            case = self._require_case(connection, case_id, merchant_id)
            self._case_event(
                connection,
                case,
                "case.created",
                {
                    "order_id": case.order_id,
                    "commitment": case.commitment.model_dump(mode="json")
                    if case.commitment
                    else None,
                },
            )
            return case

    def get_case(self, case_id: UUID, merchant_id: UUID) -> CaseResponse:
        with self.transaction() as connection:
            return self._require_case(connection, case_id, merchant_id)

    @staticmethod
    def _case_event(connection, case, event_type, payload):
        connection.execute(
            """INSERT INTO case_events (id,merchant_id,case_id,capture_id,event_type,payload_json,recorded_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                str(case.merchant_id),
                str(case.id),
                case.payment.capture_id,
                event_type,
                json.dumps(payload),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def list_cases(self, merchant_id, *, limit=20, offset=0, capture_id=None):
        with self.transaction() as connection:
            self._require_merchant(connection, merchant_id)
            where, parameters = "merchant_id = ?", [str(merchant_id)]
            if capture_id is not None:
                where += " AND capture_id = ?"
                parameters.append(capture_id.strip())
            total = connection.execute(
                "SELECT count(*) FROM cases WHERE " + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT id FROM cases WHERE "
                + where
                + " ORDER BY case_sequence DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return CasePage(
                items=[
                    self._require_case(connection, UUID(row["id"]), merchant_id)
                    for row in rows
                ],
                total=total,
                limit=limit,
                offset=offset,
            )

    def _applicable_condition(self, connection, case):
        history = self._condition_history(connection, case.id)
        epoch = connection.execute(
            "SELECT condition_epoch FROM cases WHERE id=?", (str(case.id),)
        ).fetchone()[0]
        if epoch is not None:
            history = [
                item
                for item in history
                if item.recorded_at >= datetime.fromisoformat(epoch)
            ]
        return history[-1] if history else None

    def _reconcile(self, connection, case, *, ignore_active=False):
        failed = connection.execute(
            """SELECT e.id FROM refund_executions e WHERE merchant_id=? AND capture_id=? AND status='failed'
               AND NOT EXISTS (SELECT 1 FROM review_exceptions r WHERE r.merchant_id=e.merchant_id
                   AND r.source_key='execution:'||e.id AND r.status='resolved')
               ORDER BY e.updated_at DESC LIMIT 1""",
            (str(case.merchant_id), case.payment.capture_id),
        ).fetchone()
        refunds = self._payment_refunds(
            connection, case.payment.capture_id, case.merchant_id
        )
        capture = self._latest_capture_verification(
            connection, case.payment.capture_id, case.merchant_id
        )
        history, current = history_state(connection, case, refunds, capture)
        revision = connection.execute(
            "SELECT lifecycle_revision FROM cases WHERE id=?", (str(case.id),)
        ).fetchone()[0]
        return reconcile_case(
            case,
            refunds,
            self._applicable_condition(connection, case),
            capture,
            self._active_execution_id(
                connection, case.payment.capture_id, case.merchant_id
            ),
            self._refund_verifications(
                connection, case.payment.capture_id, case.merchant_id, latest=True
            ),
            UUID(failed["id"]) if failed else None,
            paypal_history=history,
            history_current=current,
            provider_review=provider_hold(
                connection, case.merchant_id, case.payment.capture_id
            ),
            lifecycle_revision=revision,
            ignore_active=ignore_active,
            promise_gate=refund_promise_gate(connection, case),
        )

    def update_commitment(self, case_id, payload: CommitmentUpdate, merchant_id):
        with self.transaction(write=True) as connection:
            case = self._require_case(connection, case_id, merchant_id)
            require_open(case)
            if case.commitment == payload.commitment:
                return case
            if self._active_execution_id(
                connection, case.payment.capture_id, merchant_id
            ):
                raise StoreError(
                    409, "A refund execution holds this payment; reconcile it first"
                )
            if (
                self._reconcile(connection, case).state_fingerprint
                != payload.state_fingerprint
            ):
                raise StoreError(409, "Commitment update is based on stale case state")
            try:
                CaseCreate(
                    order_id=case.order_id,
                    complaint=case.complaint,
                    payment=case.payment,
                    commitment=payload.commitment,
                )
            except ValidationError:
                raise StoreError(
                    422,
                    "Commitment must match payment currency and not exceed captured amount",
                ) from None
            old_condition = case.commitment.condition if case.commitment else None
            changed_condition = old_condition != payload.commitment.condition
            if changed_condition:
                connection.execute(
                    "UPDATE cases SET condition_epoch=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), str(case_id)),
                )
            connection.execute(
                "UPDATE cases SET commitment_json=? WHERE id=?",
                (payload.commitment.model_dump_json(), str(case_id)),
            )
            invalidate_approvals(
                connection,
                merchant_id,
                case.payment.capture_id,
                "Refund commitment changed",
            )
            self._case_event(
                connection,
                case,
                "commitment.updated",
                {
                    "previous": case.commitment.model_dump(mode="json")
                    if case.commitment
                    else None,
                    "current": payload.commitment.model_dump(mode="json"),
                    "condition_epoch_reset": changed_condition,
                },
            )
            return self._require_case(connection, case_id, merchant_id)

    def timeline(self, case_id, merchant_id, *, limit=50, offset=0):
        with self.transaction() as connection:
            case = self._require_case(connection, case_id, merchant_id)
            capture_id = case.payment.capture_id
            parameters = (str(merchant_id), capture_id)
            entries = []

            def add(
                identifier, source, origin, event_type, actor, kind, occurred_at, data
            ):
                entries.append(
                    CaseTimelineEntry(
                        id=identifier,
                        source=source,
                        case_id=origin,
                        capture_id=capture_id,
                        event_type=event_type,
                        actor_merchant_id=actor,
                        actor_kind=kind,
                        occurred_at=occurred_at,
                        data=data,
                    )
                )

            for row in connection.execute(
                "SELECT * FROM case_events WHERE merchant_id=? AND capture_id=?",
                parameters,
            ):
                if row["event_type"] in (
                    "case_closed",
                    "case_reopened",
                    "evidence_attached",
                    "review_resolved",
                ) and row["case_id"] != str(case.id):
                    continue
                add(
                    f"case:{row['sequence']:020d}",
                    "case",
                    row["case_id"],
                    row["event_type"],
                    merchant_id,
                    "merchant",
                    row["recorded_at"],
                    json.loads(row["payload_json"]),
                )
            for row in connection.execute(
                """SELECT e.*,a.case_id FROM refund_approval_events e JOIN refund_approvals a ON a.id=e.approval_id WHERE a.merchant_id=? AND a.capture_id=?""",
                parameters,
            ):
                add(
                    f"approval:{row['sequence']:020d}",
                    "approval",
                    row["case_id"],
                    "approval." + row["event_type"],
                    row["actor_merchant_id"],
                    "merchant"
                    if row["event_type"] in ("approved", "revoked")
                    else "system",
                    row["recorded_at"],
                    {"approval_id": row["approval_id"], "note": row["note"]},
                )
            for row in connection.execute(
                """SELECT e.*,x.case_id FROM refund_execution_events e JOIN refund_executions x ON x.id=e.execution_id WHERE x.merchant_id=? AND x.capture_id=?""",
                parameters,
            ):
                add(
                    f"execution:{row['sequence']:020d}",
                    "execution",
                    row["case_id"],
                    "execution." + row["status"],
                    merchant_id,
                    "system",
                    row["recorded_at"],
                    {
                        "execution_id": row["execution_id"],
                        "note": row["note"],
                        "snapshot": json.loads(row["snapshot_json"])
                        if row["snapshot_json"]
                        else None,
                    },
                )
            for table, source, prefix, event_type in (
                (
                    "paypal_capture_verifications",
                    "capture_verification",
                    "capture",
                    "paypal.capture_verified",
                ),
                (
                    "paypal_refund_verifications",
                    "refund_verification",
                    "refund",
                    "paypal.refund_verified",
                ),
            ):
                for row in connection.execute(
                    "SELECT * FROM " + table + " WHERE merchant_id=? AND capture_id=?",
                    parameters,
                ):
                    model = (
                        self._verification_response(row)
                        if prefix == "capture"
                        else self._refund_verification_response(row)
                    )
                    add(
                        f"{prefix}:{row['sequence']:020d}",
                        source,
                        row["case_id"],
                        event_type,
                        merchant_id,
                        "system",
                        row["checked_at"],
                        model.model_dump(mode="json"),
                    )
            for row in connection.execute(
                """SELECT c.* FROM condition_checks c JOIN cases a ON a.id=c.case_id WHERE a.merchant_id=? AND a.capture_id=?""",
                parameters,
            ):
                actor = row["recorded_by_merchant_id"]
                add(
                    f"condition:{row['sequence']:020d}",
                    "condition_check",
                    row["case_id"],
                    "condition." + row["status"],
                    actor,
                    "merchant" if actor else "unknown",
                    row["recorded_at"],
                    {"status": row["status"], "evidence_note": row["evidence_note"]},
                )
            entries.sort(key=lambda item: (item.occurred_at, item.id))
            return CaseTimelinePage(
                items=entries[offset : offset + limit],
                total=len(entries),
                limit=limit,
                offset=offset,
            )

    def record_refund(
        self, case_id: UUID, payload: RefundRecord, merchant_id: UUID
    ) -> tuple[RefundRecord, bool]:
        with self.transaction(write=True) as connection:
            case = self._require_case(connection, case_id, merchant_id)
            self._guard_manual_refund_write(connection, case, payload.refund_id)
            row = connection.execute(
                "SELECT * FROM refunds WHERE refund_id = ? AND merchant_id = ?",
                (payload.refund_id, str(merchant_id)),
            ).fetchone()
            if row is not None:
                existing = self._refund_from_row(row)
                if (
                    existing.capture_id == case.payment.capture_id
                    and existing == payload
                ):
                    return existing, False
                raise StoreError(409, "Refund ID already exists with different details")
            try:
                validate_refund_record(
                    case.payment,
                    payload,
                    self._payment_refunds(
                        connection, case.payment.capture_id, merchant_id
                    ),
                )
            except ValueError as error:
                raise StoreError(409, str(error)) from error
            connection.execute(
                """INSERT INTO refunds
                   (merchant_id, refund_id, capture_id, amount_cents, currency, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(merchant_id),
                    payload.refund_id,
                    payload.capture_id,
                    to_cents(payload.amount),
                    payload.currency,
                    payload.status,
                ),
            )
            row = connection.execute(
                "SELECT * FROM refunds WHERE refund_id = ? AND merchant_id = ?",
                (payload.refund_id, str(merchant_id)),
            ).fetchone()
            invalidate_approvals(
                connection,
                merchant_id,
                case.payment.capture_id,
                "Refund history changed",
            )
            self._case_event(
                connection, case, "refund.recorded", payload.model_dump(mode="json")
            )
            return self._refund_from_row(row), True

    def list_refunds(self, case_id: UUID, merchant_id: UUID) -> list[RefundRecord]:
        with self.transaction() as connection:
            case = self._require_case(connection, case_id, merchant_id)
            return self._payment_refunds(
                connection, case.payment.capture_id, merchant_id
            )

    def update_refund_status(
        self,
        case_id: UUID,
        refund_id: str,
        payload: RefundStatusUpdate,
        merchant_id: UUID,
    ) -> RefundRecord:
        with self.transaction(write=True) as connection:
            case = self._require_case(connection, case_id, merchant_id)
            self._guard_manual_refund_write(connection, case, refund_id)
            row = connection.execute(
                "SELECT * FROM refunds WHERE refund_id = ? AND capture_id = ? AND merchant_id = ?",
                (refund_id, case.payment.capture_id, str(merchant_id)),
            ).fetchone()
            if row is None:
                raise StoreError(404, "Refund not found")
            existing = self._refund_from_row(row)
            if existing.status == payload.status:
                return existing
            if existing.status != "pending":
                raise StoreError(409, "Only pending refunds can change status")
            updated = RefundRecord.model_validate(
                {**existing.model_dump(), "status": payload.status}
            )
            others = [
                refund
                for refund in self._payment_refunds(
                    connection, case.payment.capture_id, merchant_id
                )
                if refund.refund_id != refund_id
            ]
            try:
                validate_refund_record(case.payment, updated, others)
            except ValueError as error:
                raise StoreError(409, str(error)) from error
            connection.execute(
                "UPDATE refunds SET status = ? WHERE refund_id = ? AND merchant_id = ?",
                (payload.status, refund_id, str(merchant_id)),
            )
            invalidate_approvals(
                connection,
                merchant_id,
                case.payment.capture_id,
                "Refund status changed",
            )
            self._case_event(
                connection,
                case,
                "refund.status_changed",
                {
                    "previous_status": existing.status,
                    "current": updated.model_dump(mode="json"),
                },
            )
            return updated

    def record_condition_check(
        self, case_id: UUID, payload: ConditionCheckCreate, merchant_id: UUID
    ) -> ConditionCheck:
        with self.transaction(write=True) as connection:
            case = self._require_case(connection, case_id, merchant_id)
            require_open(case)
            if case.commitment is None or case.commitment.condition is None:
                raise StoreError(409, "Case has no condition to check")
            check = ConditionCheck(
                **payload.model_dump(), recorded_by_merchant_id=merchant_id
            )
            connection.execute(
                """INSERT INTO condition_checks
                   (case_id, status, evidence_note, recorded_at, recorded_by_merchant_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    str(case_id),
                    check.status,
                    check.evidence_note,
                    check.recorded_at.isoformat(),
                    str(merchant_id),
                ),
            )
            invalidate_approvals(
                connection,
                merchant_id,
                case.payment.capture_id,
                "Condition evidence changed",
            )
            return check

    def list_condition_checks(
        self, case_id: UUID, merchant_id: UUID
    ) -> list[ConditionCheck]:
        with self.transaction() as connection:
            self._require_case(connection, case_id, merchant_id)
            return self._condition_history(connection, case_id)

    def reconcile(self, case_id: UUID, merchant_id: UUID) -> ReconciliationResponse:
        with self.transaction() as connection:
            case = self._require_case(connection, case_id, merchant_id)
            return self._reconcile(connection, case)

    @staticmethod
    def _verification_response(row) -> PayPalCaptureVerification:
        return PayPalCaptureVerification(
            id=row["id"],
            merchant_id=row["merchant_id"],
            case_id=row["case_id"],
            capture_id=row["capture_id"],
            paypal_merchant_id=row["paypal_merchant_id"],
            captured_amount=from_cents(row["captured_cents"]),
            currency=row["currency"],
            capture_status=row["capture_status"],
            checked_at=row["checked_at"],
        )

    def _latest_capture_verification(self, connection, capture_id, merchant_id):
        row = connection.execute(
            """SELECT * FROM paypal_capture_verifications WHERE merchant_id = ?
               AND capture_id = ? ORDER BY sequence DESC LIMIT 1""",
            (str(merchant_id), capture_id),
        ).fetchone()
        return self._verification_response(row) if row is not None else None

    def record_capture_verification(
        self, case_id: UUID, merchant_id: UUID, capture: PayPalCaptureDetails
    ) -> PayPalCaptureVerification:
        with self.transaction(write=True) as connection:
            case = self._require_case(connection, case_id, merchant_id)
            if (
                capture.id != case.payment.capture_id
                or capture.amount.value != case.payment.captured_amount
                or capture.amount.currency_code != case.payment.currency
            ):
                raise StoreError(409, "Case payment changed during PayPal verification")
            verification = PayPalCaptureVerification(
                id=uuid4(),
                case_id=case.id,
                merchant_id=merchant_id,
                capture_id=capture.id,
                paypal_merchant_id=capture.payee.merchant_id,
                captured_amount=capture.amount.value,
                currency=capture.amount.currency_code,
                capture_status=capture.status,
                checked_at=datetime.now(timezone.utc),
            )
            connection.execute(
                """INSERT INTO paypal_capture_verifications
                   (id, merchant_id, case_id, capture_id, paypal_merchant_id,
                    captured_cents, currency, capture_status, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(verification.id),
                    str(merchant_id),
                    str(case_id),
                    capture.id,
                    capture.payee.merchant_id,
                    to_cents(capture.amount.value),
                    capture.amount.currency_code,
                    capture.status,
                    verification.checked_at.isoformat(),
                ),
            )
            invalidate_approvals(
                connection, merchant_id, capture.id, "PayPal capture evidence refreshed"
            )
            return verification

    def list_capture_verifications(self, case_id: UUID, merchant_id: UUID):
        with self.transaction() as connection:
            case = self._require_case(connection, case_id, merchant_id)
            rows = connection.execute(
                """SELECT * FROM paypal_capture_verifications WHERE merchant_id = ?
                   AND capture_id = ? ORDER BY sequence""",
                (str(merchant_id), case.payment.capture_id),
            ).fetchall()
            return [self._verification_response(row) for row in rows]

    @staticmethod
    def _active_execution_id(connection, capture_id, merchant_id):
        row = connection.execute(
            """SELECT id FROM refund_executions WHERE merchant_id = ? AND capture_id = ?
               AND status IN ('reserved','submitting','unknown','pending')""",
            (str(merchant_id), capture_id),
        ).fetchone()
        return UUID(row["id"]) if row else None

    def _guard_manual_refund_write(self, connection, case, refund_id):
        require_open(case)
        if connection.execute(
            "SELECT 1 FROM paypal_refund_history WHERE merchant_id=? AND capture_id=?",
            (str(case.merchant_id), case.payment.capture_id),
        ).fetchone():
            raise StoreError(
                409, "This PayPal-managed ledger must be refreshed from PayPal"
            )
        if self._active_execution_id(
            connection, case.payment.capture_id, case.merchant_id
        ):
            raise StoreError(
                409, "A refund execution holds this payment; reconcile it first"
            )
        verified = connection.execute(
            "SELECT 1 FROM paypal_refund_verifications WHERE merchant_id = ? AND refund_id = ? LIMIT 1",
            (str(case.merchant_id), refund_id),
        ).fetchone()
        if verified:
            raise StoreError(
                409, "Provider-managed refunds must be refreshed from PayPal"
            )

    @staticmethod
    def _refund_verification_response(row):
        return PayPalRefundVerification(
            id=row["id"],
            merchant_id=row["merchant_id"],
            case_id=row["case_id"],
            capture_id=row["capture_id"],
            refund_id=row["refund_id"],
            amount=from_cents(row["amount_cents"]),
            currency=row["currency"],
            provider_status=row["provider_status"],
            checked_at=row["checked_at"],
            execution_id=row["execution_id"],
        )

    def _refund_verifications(
        self, connection, capture_id, merchant_id, *, latest=False
    ):
        query = """SELECT * FROM paypal_refund_verifications
                   WHERE merchant_id = ? AND capture_id = ?"""
        parameters = [str(merchant_id), capture_id]
        if latest:
            query += """ AND sequence IN (SELECT MAX(sequence) FROM paypal_refund_verifications
                         WHERE merchant_id = ? AND capture_id = ? GROUP BY refund_id)"""
            parameters += [str(merchant_id), capture_id]
        rows = connection.execute(query + " ORDER BY sequence", parameters).fetchall()
        return [self._refund_verification_response(row) for row in rows]

    def list_refund_verifications(self, case_id, merchant_id):
        with self.transaction() as connection:
            case = self._require_case(connection, case_id, merchant_id)
            return self._refund_verifications(
                connection, case.payment.capture_id, merchant_id
            )

    def _record_provider_refund(
        self, connection, case, refund: PayPalRefundDetails, execution_id=None
    ):
        status = {
            "PENDING": "pending",
            "COMPLETED": "completed",
            "FAILED": "failed",
            "CANCELLED": "failed",
        }[refund.status]
        record = RefundRecord(
            refund_id=refund.id,
            capture_id=case.payment.capture_id,
            amount=refund.amount.value,
            currency=refund.amount.currency_code,
            status=status,
        )
        existing = connection.execute(
            "SELECT * FROM refunds WHERE merchant_id = ? AND refund_id = ?",
            (str(case.merchant_id), refund.id),
        ).fetchone()
        if existing:
            previous = self._refund_from_row(existing)
            if (
                previous.capture_id != record.capture_id
                or previous.amount != record.amount
                or previous.currency != record.currency
            ):
                raise StoreError(
                    409, "Provider refund conflicts with the local refund identity"
                )
            verified_before = connection.execute(
                "SELECT 1 FROM paypal_refund_verifications WHERE merchant_id = ? AND refund_id = ? LIMIT 1",
                (str(case.merchant_id), refund.id),
            ).fetchone()
            if (
                verified_before
                and previous.status != "pending"
                and previous.status != record.status
            ):
                raise StoreError(
                    409, "Provider refund terminal status changed; review is required"
                )
        others = [
            item
            for item in self._payment_refunds(
                connection, record.capture_id, case.merchant_id
            )
            if item.refund_id != refund.id
        ]
        try:
            validate_refund_record(case.payment, record, others)
        except ValueError as error:
            raise StoreError(409, str(error)) from error
        connection.execute(
            """INSERT INTO refunds (merchant_id, refund_id, capture_id, amount_cents, currency, status)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(merchant_id, refund_id)
               DO UPDATE SET status = excluded.status""",
            (
                str(case.merchant_id),
                record.refund_id,
                record.capture_id,
                to_cents(record.amount),
                record.currency,
                record.status,
            ),
        )
        observation = PayPalRefundVerification(
            id=uuid4(),
            merchant_id=case.merchant_id,
            case_id=case.id,
            capture_id=record.capture_id,
            refund_id=record.refund_id,
            amount=record.amount,
            currency=record.currency,
            provider_status=refund.status,
            checked_at=datetime.now(timezone.utc),
            execution_id=execution_id,
        )
        connection.execute(
            """INSERT INTO paypal_refund_verifications
               (id,merchant_id,case_id,capture_id,refund_id,amount_cents,currency,provider_status,checked_at,execution_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                str(observation.id),
                str(case.merchant_id),
                str(case.id),
                record.capture_id,
                record.refund_id,
                to_cents(record.amount),
                record.currency,
                refund.status,
                observation.checked_at.isoformat(),
                str(execution_id) if execution_id else None,
            ),
        )
        invalidate_approvals(
            connection,
            case.merchant_id,
            record.capture_id,
            "PayPal refund evidence refreshed",
        )
        return observation


class SQLiteStore(_SQLiteTransactions, ResolveStore):
    """File-backed store for local development and the SQLite test suite."""


def configured_store(settings, *, sqlite_path=None) -> ResolveStore:
    if sqlite_path is not None:
        return SQLiteStore(sqlite_path)
    if settings.database_url is not None:
        from .postgres import PostgresStore

        return PostgresStore(settings.database_url)
    return SQLiteStore(settings.database_path)
