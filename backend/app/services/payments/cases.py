"""Case lifecycle, immutable attachments, and a merchant-owned exception queue."""

from datetime import datetime, timezone
from hashlib import sha256
import re
from uuid import uuid4

from app.services.payments.approvals import invalidate_approvals
from app.core.exceptions import StoreError
from app.schemas.payments import CaseAttachment, ReviewException, ReviewPage

MAX_ATTACHMENT = 2 * 1024 * 1024
ATTACHMENT_TYPES = {
    "application/pdf": ((".pdf",), b"%PDF-"),
    "image/png": ((".png",), b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": ((".jpg", ".jpeg"), b"\xff\xd8\xff"),
}


def now_text():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def require_open(case):
    if case.status != "open":
        raise StoreError(409, "Reopen the case before changing its workflow")


def provider_hold(connection, merchant_id, capture_id, *, exclude_event=None):
    from app.services.assurance.dispute_guard import held

    if held(connection, merchant_id, capture_id):
        return True
    return (
        connection.execute(
            """SELECT 1 FROM review_exceptions WHERE merchant_id=? AND capture_id=?
           AND status='open' AND blocking=1
           UNION ALL
           SELECT 1 FROM paypal_webhook_events WHERE merchant_id=? AND capture_id=?
           AND status='queued' AND event_id != ? LIMIT 1""",
            (
                str(merchant_id),
                capture_id,
                str(merchant_id),
                capture_id,
                exclude_event or "",
            ),
        ).fetchone()
        is not None
    )


def add_exception(
    connection,
    merchant_id,
    source,
    reason,
    *,
    case=None,
    capture_id=None,
    blocking=False,
):
    now = now_text()
    capture_id = case.payment.capture_id if case else capture_id
    connection.execute(
        """INSERT INTO review_exceptions
           (id,merchant_id,case_id,capture_id,source_key,reason,status,blocking,created_at,updated_at)
           VALUES (?,?,?,?,?,?,'open',?,?,?)
           ON CONFLICT(merchant_id, source_key) DO UPDATE SET
               case_id=COALESCE(excluded.case_id,review_exceptions.case_id),
               capture_id=COALESCE(excluded.capture_id,review_exceptions.capture_id),
               reason=excluded.reason,status='open',blocking=excluded.blocking,
               updated_at=excluded.updated_at,resolution_note=NULL""",
        (
            str(uuid4()),
            str(merchant_id),
            str(case.id) if case else None,
            capture_id,
            source,
            reason,
            int(blocking),
            now,
            now,
        ),
    )
    if blocking and capture_id:
        invalidate_approvals(
            connection, merchant_id, capture_id, "Unresolved PayPal evidence"
        )


def auto_resolve(connection, merchant_id, source, note):
    connection.execute(
        """UPDATE review_exceptions SET status='resolved',resolution_note=?,updated_at=?
           WHERE merchant_id=? AND source_key=? AND status='open'""",
        (note, now_text(), str(merchant_id), source),
    )


class CaseWorkspace:
    def __init__(self, store):
        self.store = store

    def change_status(self, case_id, merchant_id, *, closing, reason):
        status = "closed" if closing else "open"
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            if case.status == status:
                return case
            if closing and self.store._active_execution_id(
                connection, case.payment.capture_id, merchant_id
            ):
                raise StoreError(
                    409,
                    "An unconfirmed refund execution must be reconciled before closing",
                )
            connection.execute(
                """UPDATE cases SET closed_at=?,lifecycle_revision=lifecycle_revision+1
                   WHERE id=? AND merchant_id=?""",
                (now_text() if closing else None, str(case_id), str(merchant_id)),
            )
            # Only this case's approvals are invalidated; shared-capture cases stay independent.
            from app.services.payments.approvals import _transition, utc_now

            for row in connection.execute(
                "SELECT id FROM refund_approvals WHERE merchant_id=? AND case_id=? AND status='approved'",
                (str(merchant_id), str(case_id)),
            ).fetchall():
                _transition(
                    connection,
                    row["id"],
                    "invalidated",
                    "Case lifecycle changed",
                    None,
                    utc_now(),
                )
            self.store._case_event(
                connection,
                case,
                "case_closed" if closing else "case_reopened",
                {"reason": reason},
            )
            return self.store._require_case(connection, case_id, merchant_id)

    def attach(self, case_id, merchant_id, filename, content_type, content):
        file_type = ATTACHMENT_TYPES.get(content_type)
        if not file_type:
            raise StoreError(415, "Use a PDF, PNG or JPEG evidence file")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,119}", filename)
            or not filename.lower().endswith(file_type[0])
            or not content.startswith(file_type[1])
        ):
            raise StoreError(
                422, "Filename or file signature does not match the evidence type"
            )
        if len(content) > MAX_ATTACHMENT:
            raise StoreError(413, "Evidence file exceeds 2 MiB")
        created_at = now_text()
        attachment = CaseAttachment(
            id=uuid4(),
            case_id=case_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
            created_at=created_at,
        )
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, case_id, merchant_id)
            require_open(case)
            if (
                connection.execute(
                    "SELECT count(*) FROM case_attachments WHERE merchant_id=? AND case_id=?",
                    (str(merchant_id), str(case_id)),
                ).fetchone()[0]
                >= 20
            ):
                raise StoreError(409, "A case can hold at most 20 evidence attachments")
            connection.execute(
                """INSERT INTO case_attachments
                   (id,merchant_id,case_id,capture_id,filename,content_type,size_bytes,sha256,content,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(attachment.id),
                    str(merchant_id),
                    str(case_id),
                    case.payment.capture_id,
                    filename,
                    content_type,
                    len(content),
                    attachment.sha256,
                    content,
                    created_at,
                ),
            )
            self.store._case_event(
                connection,
                case,
                "evidence_attached",
                attachment.model_dump(mode="json"),
            )
        return attachment

    def attachments(self, case_id, merchant_id):
        with self.store.transaction() as connection:
            self.store._require_case(connection, case_id, merchant_id)
            return [
                CaseAttachment.model_validate(dict(row))
                for row in connection.execute(
                    """SELECT id,case_id,filename,content_type,size_bytes,sha256,created_at
                   FROM case_attachments WHERE merchant_id=? AND case_id=? ORDER BY created_at,id""",
                    (str(merchant_id), str(case_id)),
                )
            ]

    def download(self, case_id, merchant_id, attachment_id):
        with self.store.transaction() as connection:
            self.store._require_case(connection, case_id, merchant_id)
            row = connection.execute(
                "SELECT * FROM case_attachments WHERE merchant_id=? AND case_id=? AND id=?",
                (str(merchant_id), str(case_id), str(attachment_id)),
            ).fetchone()
            if row is None:
                raise StoreError(404, "Attachment not found")
            return row["filename"], row["content_type"], row["content"]

    def review(self, merchant_id, status, limit, offset):
        with self.store.transaction() as connection:
            self.store._require_merchant(connection, merchant_id)
            parameters = (str(merchant_id), status)
            total = connection.execute(
                "SELECT count(*) FROM review_exceptions WHERE merchant_id=? AND status=?",
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT * FROM review_exceptions WHERE merchant_id=? AND status=?
                   ORDER BY updated_at DESC,id LIMIT ? OFFSET ?""",
                (*parameters, limit, offset),
            ).fetchall()
            return ReviewPage(
                items=[ReviewException.model_validate(dict(row)) for row in rows],
                total=total,
                limit=limit,
                offset=offset,
            )

    def resolve_review(self, merchant_id, exception_id, reason):
        with self.store.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM review_exceptions WHERE merchant_id=? AND id=?",
                (str(merchant_id), str(exception_id)),
            ).fetchone()
            if row is None:
                raise StoreError(404, "Review exception not found")
            if row["status"] == "resolved":
                return ReviewException.model_validate(dict(row))
            if row["blocking"]:
                raise StoreError(
                    409, "This exception requires verified provider evidence to clear"
                )
            if row["reason"] == "refund_execution_unknown":
                raise StoreError(
                    409,
                    "Reconcile the unknown refund outcome before resolving the exception",
                )
            auto_resolve(connection, merchant_id, row["source_key"], reason)
            if row["case_id"]:
                case = self.store._require_case(connection, row["case_id"], merchant_id)
                self.store._case_event(
                    connection,
                    case,
                    "review_resolved",
                    {"id": str(exception_id), "reason": reason},
                )
            return ReviewException.model_validate(
                dict(
                    connection.execute(
                        "SELECT * FROM review_exceptions WHERE id=?",
                        (str(exception_id),),
                    ).fetchone()
                )
            )
