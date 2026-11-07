"""Curated customer milestones; internal notes and raw provider data stay private."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from .case_operations import NextActor, _basis, derive


class CustomerMilestone(BaseModel):
    label: str
    occurred_at: datetime
    source: Literal[
        "merchant_recorded", "provider_confirmed", "customer_submitted", "resolve"
    ]


class CustomerNextStep(BaseModel):
    actor: NextActor
    action: str
    due_at: datetime | None
    overdue: bool


def customer_progress(db, store, case, view):
    basis = _basis(db, store, case)
    ops = derive(db, store, case, view, basis)
    intake = db.execute(
        "SELECT submitted_at FROM customer_intake_invites WHERE resolution_id=?",
        (case["id"],),
    ).fetchone()
    milestones = [
        CustomerMilestone(
            label="Request received" if intake else "Case opened",
            occurred_at=intake["submitted_at"] if intake else view.created_at,
            source="customer_submitted" if intake else "resolve",
        )
    ]
    labels = {
        "return": "Return confirmed",
        "replacement": "Replacement milestone confirmed",
        "order_cancellation": "Cancellation confirmed",
        "subscription": "Subscription update confirmed",
        "store_credit_or_exchange": "Credit or exchange confirmed",
        "billing_correction": "Billing correction confirmed",
        "dispute_handoff": "Dispute outcome confirmed",
    }
    for promise in view.promises:
        kind = promise.terms.target.kind
        if kind in labels and promise.outcome == "fulfilled" and promise.checked_at:
            source = (
                "provider_confirmed"
                if promise.evidence_source == "provider_confirmed"
                else "merchant_recorded"
            )
            milestones.append(
                CustomerMilestone(
                    label=labels[kind], occurred_at=promise.checked_at, source=source
                )
            )
    if basis and any(p.refund_progress for p in view.promises):
        approval = db.execute(
            """SELECT a.approved_at FROM refund_approvals a WHERE a.case_id=? AND a.merchant_id=?
               AND ((a.status='approved' AND a.state_fingerprint=? AND a.expires_at>?)
               OR EXISTS(SELECT 1 FROM refund_executions e WHERE e.approval_id=a.id
                  AND e.status IN ('submitting','pending','completed','unknown')))
               ORDER BY a.approved_at DESC LIMIT 1""",
            (
                case["refund_case_id"],
                case["merchant_id"],
                basis.state_fingerprint,
                datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            ),
        ).fetchone()
        if approval:
            milestones.append(
                CustomerMilestone(
                    label="Refund approved",
                    occurred_at=approval["approved_at"],
                    source="merchant_recorded",
                )
            )
        completed = [
            r for r in basis.refund_verifications if r.provider_status == "COMPLETED"
        ]
        if completed:
            milestones.append(
                CustomerMilestone(
                    label="PayPal confirmed a refund",
                    occurred_at=max(item.checked_at for item in completed),
                    source="provider_confirmed",
                )
            )
    return sorted(milestones, key=lambda item: item.occurred_at), CustomerNextStep(
        actor=ops.next_actor,
        action=ops.next_action,
        due_at=(ops.due_at or ops.promise_due_at) if ops.next_actor != "none" else None,
        overdue=ops.overdue,
    )
