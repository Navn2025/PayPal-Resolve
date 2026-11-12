"""Monitoring workflow, preserving existing transaction boundaries."""

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from app.services.merchant.identity import audit, now
from app.services.merchant.operation_values import _money


class MerchantMonitoring:
    def __init__(self, store, workspace):
        self.store = store
        self.workspace = workspace

    def scan(self, merchant, actor="worker", *, moment=None):
        moment = moment or datetime.now(timezone.utc)
        with self.store.transaction(write=True) as db:
            rows = db.execute(
                "SELECT * FROM resolution_cases WHERE merchant_id=? ORDER BY created_at,id",
                (str(merchant),),
            ).fetchall()
            active = set()
            created = 0
            for case in rows:
                view = self.workspace._view(db, case)
                assignment = db.execute(
                    "SELECT assignee FROM resolution_operations WHERE resolution_id=?",
                    (case["id"],),
                ).fetchone()
                for promise in view.promises:
                    if (
                        not promise.terms.due_at
                        or promise.terms.due_at >= moment
                        or promise.outcome == "fulfilled"
                    ):
                        continue
                    active.add((str(promise.id), promise.revision))
                    if not assignment or not assignment["assignee"]:
                        owner = db.execute(
                            "SELECT name FROM platform_staff WHERE merchant_id=? AND role='owner' AND active=1 ORDER BY created_at,id LIMIT 1",
                            (str(merchant),),
                        ).fetchone()
                        label = owner["name"][:80] if owner else "Workspace owner"
                        db.execute(
                            "INSERT INTO resolution_operations (resolution_id,merchant_id,assignee) VALUES (?,?,?) ON CONFLICT(resolution_id) DO UPDATE SET assignee=excluded.assignee,revision=resolution_operations.revision+1",
                            (case["id"], str(merchant), label),
                        )
                        assignment = {"assignee": label}
                        audit(
                            db,
                            merchant,
                            actor,
                            "overdue_case_escalated",
                            case["id"],
                            assignee=label,
                        )
                    progress = promise.refund_progress
                    pending = bool(
                        progress
                        and progress.history_current
                        and progress.provider_pending_amount > 0
                    )
                    reason = (
                        "Refund pending with provider" if pending else promise.reason
                    )
                    draft = (
                        "We are reviewing your overdue "
                        + promise.terms.target.kind.replace("_", " ")
                        + " commitment. "
                    )
                    draft += (
                        "The provider still reports a pending refund."
                        if pending
                        else "We will update you after checking the remaining evidence."
                    )
                    db.execute(
                        "UPDATE platform_alerts SET state='superseded',resolved_at=? WHERE merchant_id=? AND promise_id=? AND state='open' AND day<>?",
                        (
                            now(),
                            str(merchant),
                            str(promise.id),
                            moment.date().isoformat(),
                        ),
                    )
                    result = db.execute(
                        "INSERT INTO platform_alerts VALUES (?,?,?,?,?,?, 'open',?,?,?, ?,NULL) ON CONFLICT(merchant_id,promise_id,promise_revision,day) DO UPDATE SET reason=excluded.reason,customer_draft=excluded.customer_draft,assignee=excluded.assignee",
                        (
                            str(uuid4()),
                            str(merchant),
                            case["id"],
                            str(promise.id),
                            promise.revision,
                            moment.date().isoformat(),
                            assignment["assignee"]
                            if assignment and assignment["assignee"]
                            else "Workspace owner",
                            reason,
                            draft,
                            now(),
                        ),
                    )
                    created += result.rowcount
            for alert in db.execute(
                "SELECT id,promise_id,promise_revision FROM platform_alerts WHERE merchant_id=? AND state='open'",
                (str(merchant),),
            ).fetchall():
                if (alert["promise_id"], alert["promise_revision"]) not in active:
                    db.execute(
                        "UPDATE platform_alerts SET state='resolved',resolved_at=? WHERE id=?",
                        (now(), alert["id"]),
                    )
            audit(db, merchant, actor, "watchdog_scanned", created=created)
        return self.alerts(merchant)

    def alerts(self, merchant):
        with self.store.transaction() as db:
            return {
                "items": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM platform_alerts WHERE merchant_id=? AND state='open' ORDER BY created_at DESC LIMIT 500",
                        (str(merchant),),
                    )
                ]
            }

    def dashboard(self, merchant):
        with self.store.transaction() as db:
            cases = db.execute(
                "SELECT * FROM resolution_cases WHERE merchant_id=?", (str(merchant),)
            ).fetchall()
            outcomes, remedies, reasons = Counter(), Counter(), Counter()
            reasons.update(
                {
                    row["issue_type"]: row["count"]
                    for row in db.execute(
                        """SELECT i.issue_type,count(*) AS count FROM customer_intake_invites i
                   JOIN resolution_cases c ON c.id=i.resolution_id AND c.merchant_id=i.merchant_id
                   WHERE c.merchant_id=? AND i.issue_type IS NOT NULL GROUP BY i.issue_type""",
                        (str(merchant),),
                    )
                    if row["issue_type"]
                }
            )
            overdue = awaiting = 0
            for case in cases:
                view = self.workspace._view(db, case)
                outcomes[view.outcome] += 1
                for p in view.promises:
                    remedies[p.terms.target.kind] += 1
                    overdue += int(p.overdue and p.outcome != "fulfilled")
                    awaiting += int(
                        p.evidence_source != "provider_confirmed"
                        and p.outcome != "fulfilled"
                    )
            # Shared captures are one balance. Use maximum cumulative commitment per
            # capture rather than summing overlapping promises on multiple cases.
            balances = {}
            closure = []
            for row in db.execute(
                "SELECT c.id,c.closed_at,(SELECT min(e.recorded_at) FROM case_events e WHERE e.case_id=c.id AND e.event_type='case.created') AS created_at FROM cases c WHERE c.merchant_id=?",
                (str(merchant),),
            ):
                case = self.store._require_case(db, row["id"], merchant)
                if case.commitment:
                    key = case.payment.capture_id
                    entry = balances.setdefault(
                        key,
                        {
                            "promised": Decimal(0),
                            "completed": Decimal(0),
                            "pending": Decimal(0),
                        },
                    )
                    entry["promised"] = max(
                        entry["promised"],
                        case.commitment.amount
                        if case.commitment.status == "accepted"
                        else Decimal(0),
                    )
                    # Do not confuse manual ledger observations with independent provider proof.
                    completed = db.execute(
                        "SELECT COALESCE(sum(amount_cents),0) FROM refunds WHERE merchant_id=? AND capture_id=? AND status='completed'",
                        (str(merchant), key),
                    ).fetchone()[0]
                    pending = db.execute(
                        "SELECT COALESCE(sum(amount_cents),0) FROM refunds WHERE merchant_id=? AND capture_id=? AND status='pending'",
                        (str(merchant), key),
                    ).fetchone()[0]
                    entry["completed"], entry["pending"] = (
                        Decimal(completed) / 100,
                        Decimal(pending) / 100,
                    )
                if row["closed_at"] and row["created_at"]:
                    closure.append(
                        (
                            datetime.fromisoformat(row["closed_at"])
                            - datetime.fromisoformat(row["created_at"])
                        ).total_seconds()
                    )

            def total(key):
                return _money(sum((v[key] for v in balances.values()), Decimal(0)))

            remaining = sum(
                (
                    max(Decimal(0), v["promised"] - v["completed"] - v["pending"])
                    for v in balances.values()
                ),
                Decimal(0),
            )
            return {
                "case_count": len(cases),
                "outcomes": dict(outcomes),
                "remedies": dict(remedies),
                "complaint_reasons": dict(reasons),
                "overdue_promises": overdue,
                "awaiting_evidence": awaiting,
                "financial": {
                    "currency": "USD",
                    "source": "recorded_ledger_not_independent_provider_verification",
                    "shared_capture_count": len(balances),
                    "promised": total("promised"),
                    "completed": total("completed"),
                    "pending": total("pending"),
                    "outstanding_excluding_pending": _money(remaining),
                },
                "resolution_time": {
                    "sample_count": len(closure),
                    "average_hours": round(sum(closure) / len(closure) / 3600, 2)
                    if closure
                    else None,
                },
            }
