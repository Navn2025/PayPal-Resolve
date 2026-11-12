"""Merchant triage fields and derived workflow state; no payment mutations."""

from app.schemas.case_operations import (
    InboxItem as InboxItem,
    InboxPage as InboxPage,
    MarkRead as MarkRead,
    NextActor as NextActor,
    Operations as Operations,
    OperationsUpdate as OperationsUpdate,
    Workflow as Workflow,
)


from datetime import datetime, timezone
from decimal import Decimal
from itertools import batched
from typing import Literal


from app.core.exceptions import StoreError


InboxFilter = Literal[
    "all",
    "waiting",
    "needs_review",
    "pending",
    "fulfilled",
    "waiting_on_customer",
    "needs_approval",
    "pending_with_paypal",
    "unread",
]


def _row(db, case):
    return db.execute(
        "SELECT * FROM resolution_operations WHERE resolution_id=? AND merchant_id=?",
        (case["id"], case["merchant_id"]),
    ).fetchone()


def _ensure_row(db, case):
    db.execute(
        """INSERT INTO resolution_operations (resolution_id,merchant_id) VALUES (?,?)
           ON CONFLICT(resolution_id) DO NOTHING""",
        (case["id"], case["merchant_id"]),
    )


def _basis(db, store, case):
    if not case["refund_case_id"]:
        return None
    legacy = store._require_case(db, case["refund_case_id"], case["merchant_id"])
    return store._reconcile(db, legacy)


def derive(db, store, case, view, basis=None, *, triage=None):
    row = _row(db, case) if triage is None else triage["row"]
    now = datetime.now(timezone.utc)
    if basis is None:
        basis = _basis(db, store, case)
    deadline = datetime.fromisoformat(row["due_at"]) if row and row["due_at"] else None
    promise_deadline = min(
        (
            p.terms.due_at
            for p in view.promises
            if p.terms.due_at and p.outcome != "fulfilled"
        ),
        default=None,
    )
    effective_due = deadline or promise_deadline
    waiting = bool(row and row["waiting_on_customer"])
    shared_refund = any(p.refund_progress for p in view.promises)
    if view.outcome == "fulfilled":
        state, actor, action = (
            "resolved",
            "none",
            "The agreed remedy has been completed.",
        )
    elif (
        shared_refund
        and basis
        and (
            basis.status == "execution_pending"
            or (
                basis.status == "refund_pending"
                and any(
                    r.provider_status == "PENDING" for r in basis.refund_verifications
                )
            )
        )
    ):
        state, actor, action = (
            "pending_with_paypal",
            "paypal",
            "The refund outcome is awaiting PayPal confirmation.",
        )
    elif waiting:
        state, actor, action = (
            "waiting_on_customer",
            "customer",
            "The merchant is waiting for an update. Check the conversation.",
        )
    elif (
        shared_refund
        and basis
        and basis.status == "refund_required"
        and basis.paypal_history_current
        and basis.recommended_refund_amount > Decimal(0)
    ):
        approval = db.execute(
            """SELECT 1 FROM refund_approvals a WHERE a.case_id=? AND a.merchant_id=? AND a.status='approved'
               AND a.state_fingerprint=? AND a.expires_at>? AND NOT EXISTS(
                 SELECT 1 FROM refund_executions e WHERE e.approval_id=a.id) LIMIT 1""",
            (
                case["refund_case_id"],
                case["merchant_id"],
                basis.state_fingerprint,
                now.isoformat(timespec="microseconds"),
            ),
        ).fetchone()
        state, actor, action = (
            (
                "merchant_action",
                "merchant",
                "The merchant can submit the approved refund.",
            )
            if approval
            else (
                "needs_approval",
                "merchant",
                "The merchant needs to approve the remaining refund.",
            )
        )
    else:
        state, actor, action = (
            "merchant_action",
            "merchant",
            "The merchant is reviewing the case and will share the next update.",
        )
    threshold = row["read_through"] if row else 0
    counts = (
        triage["counts"]
        if triage is not None
        else db.execute(
            """SELECT COALESCE(max(sequence),0) AS watermark,
           COALESCE(sum(CASE WHEN sequence>? THEN 1 ELSE 0 END),0) AS unread
           FROM customer_portal_messages WHERE resolution_id=? AND merchant_id=? AND sender='customer'""",
            (threshold, case["id"], case["merchant_id"]),
        ).fetchone()
    )
    intake = (
        triage["intake"]
        if triage is not None
        else db.execute(
            "SELECT issue_type FROM customer_intake_invites WHERE resolution_id=?",
            (case["id"],),
        ).fetchone()
    )
    return Operations(
        revision=row["revision"] if row else 0,
        assignee=row["assignee"] if row else None,
        due_at=deadline,
        promise_due_at=promise_deadline,
        overdue=bool(effective_due and effective_due < now and state != "resolved"),
        waiting_on_customer=waiting,
        workflow=state,
        next_actor=actor,
        next_action=action,
        unread_count=counts["unread"],
        message_watermark=counts["watermark"],
        issue_type=intake["issue_type"] if intake else None,
    )


class CaseOperations:
    def __init__(self, store):
        from app.services.resolution.workspace import ResolutionWorkspace

        self.store = store
        self.workspace = ResolutionWorkspace(store)

    def get(self, case_id, merchant_id):
        with self.store.transaction() as db:
            case = self.workspace._case(db, case_id, merchant_id)
            return derive(db, self.store, case, self.workspace._view(db, case))

    @staticmethod
    def _triage_batch(db, merchant, cases):
        """Bounded, transaction-local reads; never cache financial/tenant state."""
        ids = [case["id"] for case in cases]
        placeholders = ",".join("?" for _ in ids)
        parameters = (merchant, *ids)
        settings = {
            row["resolution_id"]: row
            for row in db.execute(
                f"SELECT * FROM resolution_operations WHERE merchant_id=? AND resolution_id IN ({placeholders})",
                parameters,
            )
        }
        counts = {
            row["resolution_id"]: row
            for row in db.execute(
                f"""SELECT m.resolution_id,max(m.sequence) AS watermark,
                sum(CASE WHEN m.sequence>COALESCE(o.read_through,0) THEN 1 ELSE 0 END) AS unread
                FROM customer_portal_messages m LEFT JOIN resolution_operations o
                ON o.resolution_id=m.resolution_id AND o.merchant_id=m.merchant_id
                WHERE m.merchant_id=? AND m.resolution_id IN ({placeholders}) AND m.sender='customer'
                GROUP BY m.resolution_id,o.read_through""",
                parameters,
            )
        }
        intake = {
            row["resolution_id"]: row
            for row in db.execute(
                f"SELECT resolution_id,issue_type FROM customer_intake_invites WHERE merchant_id=? AND resolution_id IN ({placeholders})",
                parameters,
            )
        }
        return {
            identifier: {
                "row": settings.get(identifier),
                "counts": counts.get(identifier, {"watermark": 0, "unread": 0}),
                "intake": intake.get(identifier),
            }
            for identifier in ids
        }

    def inbox(self, merchant_id, filter_by, query, limit, offset):
        merchant = str(merchant_id)
        base = "SELECT * FROM resolution_cases WHERE merchant_id=?"
        order = " ORDER BY created_at DESC,id"
        needle = query.strip().casefold()
        with self.store.transaction() as db:
            if filter_by == "all" and not needle:
                total = db.execute(
                    "SELECT count(*) FROM resolution_cases WHERE merchant_id=?",
                    (merchant,),
                ).fetchone()[0]
                rows = db.execute(
                    base + order + " LIMIT ? OFFSET ?", (merchant, limit, offset)
                )
            else:
                total = 0
                rows = db.execute(base + order, (merchant,))
            items = []
            for batch in batched(rows, 100):
                triage = self._triage_batch(db, merchant, batch)
                for case in batch:
                    item = self._inbox_item(
                        db, case, triage[case["id"]], needle, filter_by
                    )
                    if item is None:
                        continue
                    if filter_by != "all" or needle:
                        total += 1
                        if total <= offset or len(items) == limit:
                            continue
                    items.append(item)
            return InboxPage(items=items, total=total, limit=limit, offset=offset)

    def _inbox_item(self, db, case, triage, needle, filter_by):
        settings = triage["row"]
        if needle and not any(
            needle in value.casefold()
            for value in (
                case["title"],
                case["order_reference"] or "",
                case["id"],
                (settings["assignee"] or "") if settings else "",
            )
        ):
            return None
        view = self.workspace._view(db, case)
        ops = derive(db, self.store, case, view, triage=triage)
        if filter_by not in ("all", view.outcome, ops.workflow) and not (
            filter_by == "unread" and ops.unread_count
        ):
            return None
        return InboxItem(**view.model_dump(), operations=ops)

    def update(self, case_id, merchant_id, payload):
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant_id)
            _ensure_row(db, case)
            updated = db.execute(
                """UPDATE resolution_operations SET assignee=?,due_at=?,waiting_on_customer=?,revision=revision+1
                   WHERE resolution_id=? AND merchant_id=? AND revision=?""",
                (
                    payload.assignee,
                    payload.due_at.isoformat() if payload.due_at else None,
                    int(payload.waiting_on_customer),
                    case["id"],
                    case["merchant_id"],
                    payload.expected_revision,
                ),
            )
            if not updated.rowcount:
                raise StoreError(
                    409, "Case assignment or due date changed; refresh and try again."
                )
            return derive(db, self.store, case, self.workspace._view(db, case))

    def mark_read(self, case_id, merchant_id, through):
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant_id)
            _ensure_row(db, case)
            if (
                through
                and not db.execute(
                    """SELECT 1 FROM customer_portal_messages WHERE sequence=? AND resolution_id=? AND merchant_id=?
                   AND sender='customer'""",
                    (through, case["id"], case["merchant_id"]),
                ).fetchone()
            ):
                raise StoreError(
                    422, "The read marker is not a customer message in this case."
                )
            db.execute(
                """UPDATE resolution_operations
                   SET read_through=CASE WHEN read_through<? THEN ? ELSE read_through END
                   WHERE resolution_id=? AND merchant_id=?""",
                (through, through, case["id"], case["merchant_id"]),
            )
            return derive(db, self.store, case, self.workspace._view(db, case))
