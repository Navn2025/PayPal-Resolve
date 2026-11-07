"""Durable first full-capture sandbox refunds; network calls never hold a DB lock."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from psycopg import Error as PostgresDriverError
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from .approvals import RefundApprovalService, invalidate_approvals
from .errors import StoreError
from .models import (
    ExecutionCaptureCheck,
    RefundExecution,
    RefundExecutionCreate,
    RefundExecutionEvent,
)
from .paypal import PayPalSandboxClient, PayPalWriteError
from .storage import ResolveStore, from_cents, to_cents
from .case_workspace import add_exception, auto_resolve, require_open
from .paypal_history import PayPalHistoryService
from .resolution_state import refund_promise_gate


SUBMISSION_LEASE = timedelta(seconds=60)
RECOVERY_WINDOW = timedelta(hours=24)


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    return value.isoformat(timespec="microseconds")


class RefundExecutionService:
    def __init__(self, store: ResolveStore, paypal: PayPalSandboxClient):
        self.store = store
        self.paypal = paypal

    @staticmethod
    def _response(row):
        return RefundExecution(
            id=row["id"],
            merchant_id=row["merchant_id"],
            case_id=row["case_id"],
            capture_id=row["capture_id"],
            approval_id=row["approval_id"],
            request_id=row["request_id"],
            provider_request_id=row["provider_request_id"],
            amount=from_cents(row["amount_cents"]),
            currency=row["currency"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            lease_expires_at=row["lease_expires_at"],
            error_code=row["error_code"],
            approval_snapshot=json.loads(row["approval_json"]),
            final_capture_check=json.loads(row["capture_check_json"]),
            provider_refund=json.loads(row["provider_refund_json"])
            if row["provider_refund_json"]
            else None,
            full_refund_only="custom_id"
            not in json.loads(row["provider_request_json"]),
        )

    def _require_row(self, connection, case_id, execution_id, merchant_id):
        self.store._require_case(connection, case_id, merchant_id)
        row = connection.execute(
            "SELECT * FROM refund_executions WHERE id=? AND case_id=? AND merchant_id=?",
            (str(execution_id), str(case_id), str(merchant_id)),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Refund execution not found")
        return row

    @staticmethod
    def _event(connection, execution_id, status, note, now, snapshot=None):
        connection.execute(
            """INSERT INTO refund_execution_events
               (execution_id,status,note,recorded_at,snapshot_json) VALUES (?,?,?,?,?)""",
            (
                str(execution_id),
                status,
                note,
                timestamp(now),
                json.dumps(snapshot) if snapshot is not None else None,
            ),
        )

    def _transition(
        self, connection, row, status, note, now, *, snapshot=None, **fields
    ):
        allowed = {
            "lease_expires_at",
            "attempt_count",
            "error_code",
            "provider_refund_id",
            "provider_refund_json",
        }
        if set(fields) - allowed:
            raise RuntimeError("Invalid execution update")
        fields = {"status": status, "updated_at": timestamp(now), **fields}
        connection.execute(
            "UPDATE refund_executions SET "
            + ",".join(name + "=?" for name in fields)
            + " WHERE id=?",
            [*fields.values(), row["id"]],
        )
        self._event(connection, row["id"], status, note, now, snapshot)
        source = "execution:" + row["id"]
        if status in ("unknown", "failed"):
            case = self.store._require_case(
                connection, row["case_id"], row["merchant_id"]
            )
            add_exception(
                connection,
                case.merchant_id,
                source,
                "refund_execution_" + status,
                case=case,
            )
            if status == "failed":
                invalidate_approvals(
                    connection,
                    case.merchant_id,
                    case.payment.capture_id,
                    "Refund execution failed",
                )
        elif status in ("pending", "completed"):
            auto_resolve(
                connection,
                row["merchant_id"],
                source,
                "Provider identified the execution outcome",
            )

    def _writes_enabled(self):
        if (
            not self.paypal.settings.paypal_sandbox_enabled
            or not self.paypal.settings.paypal_sandbox_refunds_enabled
        ):
            raise StoreError(503, "PayPal Sandbox refund execution is disabled")

    def _provider_identity(self):
        settings = self.paypal.settings
        if (
            settings.paypal_sandbox_client_id is None
            or not settings.paypal_sandbox_merchant_id
        ):
            raise StoreError(503, "PayPal Sandbox configuration is incomplete")
        identity = [
            "paypal_sandbox_refund",
            settings.paypal_sandbox_client_id.get_secret_value(),
            settings.paypal_sandbox_merchant_id,
        ]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def _existing_request(self, connection, case_id, payload, merchant_id):
        row = connection.execute(
            "SELECT * FROM refund_executions WHERE merchant_id=? AND request_id=?",
            (str(merchant_id), str(payload.request_id)),
        ).fetchone()
        if row is not None and (
            row["case_id"] != str(case_id)
            or row["approval_id"] != str(payload.approval_id)
        ):
            raise StoreError(409, "Execution request ID already has different details")
        return row

    def _eligible(self, connection, case, payload):
        require_open(case)
        row = RefundApprovalService._require_row(
            connection, case.id, payload.approval_id, case.merchant_id
        )
        approval = RefundApprovalService._response(row)
        if approval.status != "approved" or approval.expires_at <= utc_now():
            raise StoreError(409, "A current active merchant approval is required")
        if connection.execute(
            "SELECT 1 FROM refund_executions WHERE approval_id=?", (str(approval.id),)
        ).fetchone():
            raise StoreError(
                409, "This approval has already been used for an execution"
            )
        basis = self.store._reconcile(connection, case)
        partial = self.paypal.settings.paypal_sandbox_partial_refunds_enabled
        if partial:
            if self.store._active_execution_id(
                connection, case.payment.capture_id, case.merchant_id
            ):
                raise StoreError(409, "An execution already holds this capture")
            if not basis.paypal_history_current or basis.paypal_refund_history is None:
                raise StoreError(409, "Refresh PayPal refund history before execution")
            if (
                basis.status != "refund_required"
                or basis.state_fingerprint != approval.state_fingerprint
                or approval.amount > basis.recommended_refund_amount
                or approval.amount > basis.paypal_refund_history.remaining_amount
                or approval.capture_id != case.payment.capture_id
                or approval.currency != case.payment.currency
            ):
                raise StoreError(
                    409, "Approval no longer matches the verified refund balance"
                )
            return approval
        other = connection.execute(
            "SELECT 1 FROM refund_executions WHERE merchant_id=? AND capture_id=?",
            (str(case.merchant_id), case.payment.capture_id),
        ).fetchone()
        if other:
            raise StoreError(409, "This capture already has a full-refund execution")
        refunds = self.store._payment_refunds(
            connection, case.payment.capture_id, case.merchant_id
        )
        if refunds:
            raise StoreError(
                409,
                "First full-refund execution requires an empty recorded refund ledger",
            )
        capture = self.store._latest_capture_verification(
            connection, case.payment.capture_id, case.merchant_id
        )
        if capture is None or capture.capture_status != "COMPLETED":
            raise StoreError(
                409, "Save completed PayPal capture verification before execution"
            )
        if (
            basis.status != "refund_required"
            or basis.state_fingerprint != approval.state_fingerprint
            or basis.recommended_refund_amount != case.payment.captured_amount
            or approval.amount != case.payment.captured_amount
            or approval.capture_id != case.payment.capture_id
            or approval.currency != case.payment.currency
        ):
            raise StoreError(
                409,
                "Execution requires exact-state approval of the first full capture amount",
            )
        return approval

    def create(self, case_id, payload: RefundExecutionCreate, merchant_id):
        with self.store.transaction() as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            existing = self._existing_request(connection, case_id, payload, merchant_id)
            if existing is not None:
                return self._response(existing), False
            self._eligible(connection, case, payload)
        self._writes_enabled()
        partial = self.paypal.settings.paypal_sandbox_partial_refunds_enabled
        if partial:
            history, capture = PayPalHistoryService(self.store, self.paypal).refresh(
                case_id, merchant_id
            )
        else:
            capture = self.paypal.read_capture(case)
        if not partial and capture.status != "COMPLETED":
            raise StoreError(
                409, "PayPal capture is not a completed, unrefunded capture"
            )
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            existing = self._existing_request(connection, case_id, payload, merchant_id)
            if existing is not None:
                return self._response(existing), False
            approval = self._eligible(connection, case, payload)
            if (
                partial
                and approval.basis.paypal_refund_history.digest != history.digest
            ):
                raise StoreError(409, "PayPal refund history changed after approval")
            if (
                capture.id != case.payment.capture_id
                or capture.amount.value != case.payment.captured_amount
                or capture.amount.currency_code != case.payment.currency
            ):
                raise StoreError(
                    409, "Case payment changed during final provider validation"
                )
            now = utc_now()
            capture_check = ExecutionCaptureCheck(
                capture_id=capture.id,
                captured_amount=capture.amount.value,
                currency=capture.amount.currency_code,
                paypal_merchant_id=capture.payee.merchant_id,
                capture_status=capture.status,
                checked_at=now,
            )
            execution_id, provider_request_id = uuid4(), uuid4()
            body = {
                "amount": {
                    "value": format(approval.amount, ".2f"),
                    "currency_code": approval.currency,
                }
            }
            if partial:
                body["custom_id"] = "resolve-" + str(provider_request_id)
            connection.execute(
                """INSERT INTO refund_executions
                   (id,merchant_id,case_id,capture_id,approval_id,request_id,provider_request_id,
                    amount_cents,currency,status,approval_json,capture_check_json,provider_request_json,created_at,updated_at,provider_identity_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,'reserved',?,?,?,?,?,?)""",
                (
                    str(execution_id),
                    str(merchant_id),
                    str(case_id),
                    case.payment.capture_id,
                    str(approval.id),
                    str(payload.request_id),
                    str(provider_request_id),
                    to_cents(approval.amount),
                    approval.currency,
                    approval.model_dump_json(),
                    capture_check.model_dump_json(),
                    json.dumps(body),
                    timestamp(now),
                    timestamp(now),
                    self._provider_identity(),
                ),
            )
            self._event(
                connection,
                execution_id,
                "reserved",
                "Exact merchant approval reserved for sandbox execution",
                now,
            )
        return self._submit(case_id, execution_id, merchant_id), True

    def get(self, case_id, execution_id, merchant_id):
        with self.store.transaction() as connection:
            return self._response(
                self._require_row(connection, case_id, execution_id, merchant_id)
            )

    def list(self, case_id, merchant_id):
        with self.store.transaction() as connection:
            self.store._require_case(connection, case_id, merchant_id)
            rows = connection.execute(
                "SELECT * FROM refund_executions WHERE case_id=? AND merchant_id=? ORDER BY created_at,id",
                (str(case_id), str(merchant_id)),
            ).fetchall()
            return [self._response(row) for row in rows]

    def _claim(self, case_id, execution_id, merchant_id):
        self._writes_enabled()
        with self.store.transaction(write=True) as connection:
            row = self._require_row(connection, case_id, execution_id, merchant_id)
            now = utc_now()
            if (
                not row["provider_identity_hash"]
                or row["provider_identity_hash"] != self._provider_identity()
            ):
                raise StoreError(
                    409,
                    "Execution credential identity changed; reconcile by provider refund lookup",
                )
            if now - datetime.fromisoformat(row["created_at"]) > RECOVERY_WINDOW:
                raise StoreError(
                    409,
                    "Recovery POST window elapsed; reconcile using a known provider refund ID",
                )
            if row["status"] not in ("reserved", "unknown", "submitting"):
                raise StoreError(
                    409, "Only reserved or unconfirmed executions can be submitted"
                )
            if (
                row["status"] == "submitting"
                and row["lease_expires_at"]
                and datetime.fromisoformat(row["lease_expires_at"]) > now
            ):
                raise StoreError(
                    409, "Another worker holds the execution submission lease"
                )
            case = self.store._require_case(connection, case_id, merchant_id)
            require_open(case)
            amount = from_cents(row["amount_cents"])
            body = json.loads(row["provider_request_json"])
            expected = {
                "amount": {
                    "value": format(amount, ".2f"),
                    "currency_code": case.payment.currency,
                }
            }
            if "custom_id" in body:
                if not self.paypal.settings.paypal_sandbox_partial_refunds_enabled:
                    raise StoreError(503, "History-gated Sandbox execution is disabled")
                expected["custom_id"] = "resolve-" + row["provider_request_id"]
            if (
                body != expected
                or amount > case.payment.captured_amount
                or ("custom_id" not in body and amount != case.payment.captured_amount)
            ):
                raise StoreError(
                    409, "Saved execution request no longer matches the case payment"
                )
            if row["attempt_count"] == 0:
                approval_row = RefundApprovalService._require_row(
                    connection, case_id, row["approval_id"], merchant_id
                )
                approval = RefundApprovalService._response(approval_row)
                basis = self.store._reconcile(connection, case, ignore_active=True)
                if (
                    approval.status != "approved"
                    or approval.expires_at <= now
                    or basis.state_fingerprint != approval.state_fingerprint
                    or ("custom_id" in body and not basis.paypal_history_current)
                ):
                    self._transition(
                        connection,
                        row,
                        "failed",
                        "Evidence or approval changed before submission",
                        now,
                        error_code="approval_changed_before_submission",
                    )
                    return None
            else:
                gate = refund_promise_gate(connection, case)
                approved_gate = json.loads(row["approval_json"])["basis"].get(
                    "resolution_promise_fingerprint"
                )
                if (gate.fingerprint if gate else None) != approved_gate or (
                    gate and gate.outcome != "fulfilled"
                ):
                    raise StoreError(
                        409,
                        "Resolution promise changed; recover the original refund by provider ID",
                    )
            if row["attempt_count"] and "custom_id" in body:
                basis = self.store._reconcile(connection, case, ignore_active=True)
                original = json.loads(row["approval_json"])["basis"][
                    "paypal_refund_history"
                ]
                if (
                    not basis.paypal_history_current
                    or basis.paypal_refund_history.digest != original["digest"]
                ):
                    raise StoreError(
                        409,
                        "PayPal history changed; recover the original refund by its provider ID",
                    )
            self._transition(
                connection,
                row,
                "submitting",
                "Submitting with the original PayPal request identity",
                now,
                lease_expires_at=timestamp(now + SUBMISSION_LEASE),
                attempt_count=row["attempt_count"] + 1,
                error_code=None,
            )
            return (
                case,
                UUID(row["provider_request_id"]),
                row["attempt_count"] + 1,
                row["attempt_count"] > 0,
                body,
            )

    def _failure(self, case_id, execution_id, merchant_id, *, unknown, code, attempt):
        try:
            with self.store.transaction(write=True) as connection:
                row = self._require_row(connection, case_id, execution_id, merchant_id)
                if (
                    row["status"] in ("reserved", "submitting", "unknown")
                    and row["attempt_count"] == attempt
                ):
                    self._transition(
                        connection,
                        row,
                        "unknown" if unknown else "failed",
                        code,
                        utc_now(),
                        lease_expires_at=None,
                        error_code=code,
                    )
        except (sqlite3.Error, PostgresDriverError):
            # A still-submitting record retains the hold and durable request ID.
            pass
        return self.get(case_id, execution_id, merchant_id)

    def _submit(self, case_id, execution_id, merchant_id):
        claim = self._claim(case_id, execution_id, merchant_id)
        if claim is None:
            return self.get(case_id, execution_id, merchant_id)
        case, provider_request_id, attempt, previous_outcome_uncertain, body = claim
        try:
            refund = (
                self.paypal.refund_capture(
                    case,
                    provider_request_id,
                    Decimal(body["amount"]["value"]),
                    custom_id=body["custom_id"],
                )
                if "custom_id" in body
                else self.paypal.refund_capture(case, provider_request_id)
            )
        except PayPalWriteError as error:
            return self._failure(
                case_id,
                execution_id,
                merchant_id,
                unknown=error.outcome_unknown or previous_outcome_uncertain,
                code="provider_outcome_unknown"
                if error.outcome_unknown or previous_outcome_uncertain
                else "provider_request_rejected",
                attempt=attempt,
            )
        except StoreError:
            return self._failure(
                case_id,
                execution_id,
                merchant_id,
                unknown=previous_outcome_uncertain,
                code="provider_outcome_unknown"
                if previous_outcome_uncertain
                else "provider_request_not_submitted",
                attempt=attempt,
            )
        except Exception:
            return self._failure(
                case_id,
                execution_id,
                merchant_id,
                unknown=True,
                code="provider_outcome_unknown",
                attempt=attempt,
            )
        try:
            return self._finalize(case_id, execution_id, merchant_id, refund)
        except Exception:
            return self._failure(
                case_id,
                execution_id,
                merchant_id,
                unknown=True,
                code="provider_result_needs_local_recovery",
                attempt=attempt,
            )

    def retry(self, case_id, execution_id, merchant_id):
        # Ownership is checked before settings or provider calls.
        execution = self.get(case_id, execution_id, merchant_id)
        if not execution.full_refund_only and execution.attempt_count:
            service = PayPalHistoryService(self.store, self.paypal)
            history, _ = service.refresh(case_id, merchant_id)
            case = self.store.get_case(case_id, merchant_id)
            custom_id = "resolve-" + str(execution.provider_request_id)
            matches = []
            for refund_id in history.refund_ids:
                refund = self.paypal.read_refund(case, refund_id)
                if refund.custom_id == custom_id:
                    matches.append(refund)
            if len(matches) > 1:
                raise StoreError(
                    409, "More than one PayPal refund identifies this execution"
                )
            if matches:
                return self._finalize(case_id, execution_id, merchant_id, matches[0])
            with self.store.transaction() as connection:
                basis = self.store._reconcile(connection, case, ignore_active=True)
                original = execution.approval_snapshot.basis.paypal_refund_history
                if (
                    history.digest != original.digest
                    or not basis.paypal_history_current
                ):
                    raise StoreError(
                        409,
                        "PayPal history changed; recover the original refund by its provider ID",
                    )
        return self._submit(case_id, execution_id, merchant_id)

    def _finalize(self, case_id, execution_id, merchant_id, refund):
        with self.store.transaction(write=True) as connection:
            row = self._require_row(connection, case_id, execution_id, merchant_id)
            custom_id = json.loads(row["provider_request_json"]).get("custom_id")
            if custom_id and custom_id != refund.custom_id:
                raise StoreError(409, "PayPal refund does not identify this execution")
            if connection.execute(
                "SELECT 1 FROM refund_executions WHERE merchant_id=? AND provider_refund_id=? AND id!=?",
                (str(merchant_id), refund.id, str(execution_id)),
            ).fetchone():
                raise StoreError(
                    409, "PayPal refund already belongs to another execution"
                )
            expected = from_cents(row["amount_cents"])
            if (
                refund.amount.value != expected
                or refund.amount.currency_code != row["currency"]
            ):
                raise StoreError(
                    409, "Provider refund does not match the execution amount"
                )
            if row["provider_refund_id"] and row["provider_refund_id"] != refund.id:
                raise StoreError(
                    409, "Execution already identifies a different provider refund"
                )
            status = {
                "COMPLETED": "completed",
                "PENDING": "pending",
                "FAILED": "failed",
                "CANCELLED": "failed",
            }[refund.status]
            if row["status"] in ("completed", "failed"):
                if row["status"] != status or not row["provider_refund_id"]:
                    raise StoreError(409, "Execution terminal outcome requires review")
                return self._response(row)
            case = self.store._require_case(connection, case_id, merchant_id)
            observation = self.store._record_provider_refund(
                connection, case, refund, execution_id
            )
            self._transition(
                connection,
                row,
                status,
                "Provider refund observed and projected into the ledger",
                utc_now(),
                snapshot=observation.model_dump(mode="json"),
                lease_expires_at=None,
                provider_refund_id=refund.id,
                provider_refund_json=observation.model_dump_json(),
                error_code=None,
            )
            return self._response(
                self._require_row(connection, case_id, execution_id, merchant_id)
            )

    def refresh(self, case_id, execution_id, merchant_id, refund_id=None):
        execution = self.get(case_id, execution_id, merchant_id)
        known_id = (
            execution.provider_refund.refund_id if execution.provider_refund else None
        )
        if known_id and refund_id and refund_id != known_id:
            raise StoreError(
                409, "Execution already identifies a different provider refund"
            )
        refund_id = refund_id or known_id
        if refund_id is None:
            raise StoreError(
                409, "No known provider refund ID; use bounded retry recovery"
            )
        case = self.store.get_case(case_id, merchant_id)
        refund = self.paypal.read_refund(case, refund_id)
        return self._finalize(case_id, execution_id, merchant_id, refund)

    def verify_refund(self, case_id, refund_id, merchant_id):
        case = self.store.get_case(case_id, merchant_id)
        refund = self.paypal.read_refund(case, refund_id)
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            execution = connection.execute(
                "SELECT * FROM refund_executions WHERE merchant_id=? AND capture_id=? AND provider_refund_id=?",
                (str(merchant_id), case.payment.capture_id, refund.id),
            ).fetchone()
            observation = self.store._record_provider_refund(
                connection, case, refund, UUID(execution["id"]) if execution else None
            )
            if execution:
                status = {
                    "COMPLETED": "completed",
                    "PENDING": "pending",
                    "FAILED": "failed",
                    "CANCELLED": "failed",
                }[refund.status]
                self._transition(
                    connection,
                    execution,
                    status,
                    "Known provider refund refreshed",
                    utc_now(),
                    snapshot=observation.model_dump(mode="json"),
                    lease_expires_at=None,
                    provider_refund_json=observation.model_dump_json(),
                    error_code=None,
                )
            return observation

    def events(self, case_id, execution_id, merchant_id):
        with self.store.transaction() as connection:
            self._require_row(connection, case_id, execution_id, merchant_id)
            rows = connection.execute(
                "SELECT * FROM refund_execution_events WHERE execution_id=? ORDER BY sequence",
                (str(execution_id),),
            ).fetchall()
            return [
                RefundExecutionEvent(
                    sequence=row["sequence"],
                    execution_id=row["execution_id"],
                    status=row["status"],
                    note=row["note"],
                    recorded_at=row["recorded_at"],
                    snapshot=json.loads(row["snapshot_json"])
                    if row["snapshot_json"]
                    else None,
                )
                for row in rows
            ]
