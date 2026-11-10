"""Broken-promise detector: compares accepted refund promises with refunds already on the payment.

Deterministic and code-only (no model calls). Amounts come from the existing reconciliation
(`ResolveStore._reconcile`) and the refund progress the workspace already computes from it.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .resolution_workspace import ResolutionWorkspace

ZERO = Decimal("0.00")
HealthStatus = Literal["kept", "partially_kept", "at_risk", "broken"]
ATTENTION: tuple[HealthStatus, ...] = ("at_risk", "broken")


class PromiseHealth(BaseModel):
    case_id: UUID
    case_title: str
    order_reference: str | None
    refund_case_id: UUID
    promise_id: UUID
    promise_revision: int
    promise: str
    status: HealthStatus
    currency: str
    promised_amount: Decimal
    refunded_amount: Decimal
    pending_amount: Decimal
    remaining_amount: Decimal
    captured_amount: Decimal
    suggested_refund_amount: Decimal
    promised_at: datetime
    deadline: datetime
    days_since_promise: int
    overdue: bool
    ledger_ahead_of_provider: bool


class CasePromiseHealth(BaseModel):
    case_id: UUID
    overdue_after_days: int
    items: list[PromiseHealth]


class PromiseHealthPage(BaseModel):
    overdue_after_days: int
    items: list[PromiseHealth]
    total: int
    limit: int
    cases_checked: int


def classify(promised: Decimal, refunded: Decimal, overdue: bool) -> HealthStatus:
    """Kept when nothing is owed. Otherwise the deadline and any refund so far decide.

    Before the deadline: partially_kept if some refund was confirmed, at_risk if none yet.
    After the deadline: at_risk if part was refunded, broken if nothing was.
    """
    if refunded >= promised:
        return "kept"
    if not overdue:
        return "partially_kept" if refunded > ZERO else "at_risk"
    return "at_risk" if refunded > ZERO else "broken"


def suggested_refund(promised, confirmed, recorded, pending, captured) -> Decimal:
    """Largest refund that neither exceeds the promise nor the captured amount.

    Uses the larger of PayPal-confirmed and locally recorded completed refunds, and subtracts
    pending refunds, so a suggestion can never pay the same money twice. The approval route
    still enforces its own cap (`recommended_refund_amount`) when the merchant confirms.
    """
    paid = max(confirmed, recorded)
    owed = promised - paid - pending
    refundable = captured - recorded - pending
    return max(min(owed, refundable), ZERO)


class PromiseHealthCheck:
    def __init__(self, store, overdue_days: int, now: datetime | None = None):
        self.store = store
        self.workspace = ResolutionWorkspace(store)
        self.overdue_days = overdue_days
        self.now = now or datetime.now(UTC)

    def _assess(self, connection, case) -> list[PromiseHealth]:
        legacy = self.workspace._legacy(connection, case)
        # Only promises the buyer and merchant accepted on the linked payment case.
        if legacy is None or legacy.commitment is None or legacy.commitment.status != "accepted":
            return []
        basis = self.store._reconcile(connection, legacy)
        view = self.workspace._view(connection, case)
        items = []
        for promise in view.promises:
            progress = promise.refund_progress
            if promise.terms.target.kind != "refund" or progress is None:
                continue
            promised = progress.promised_amount
            confirmed = progress.provider_completed_amount
            deadline = promise.terms.due_at or promise.created_at + timedelta(days=self.overdue_days)
            overdue = self.now > deadline
            items.append(PromiseHealth(
                case_id=view.id, case_title=view.title, order_reference=view.order_reference,
                refund_case_id=legacy.id, promise_id=promise.id, promise_revision=promise.revision,
                promise=promise.terms.promise, status=classify(promised, confirmed, overdue),
                currency=basis.currency, promised_amount=promised, refunded_amount=confirmed,
                pending_amount=progress.provider_pending_amount,
                remaining_amount=progress.outstanding_amount, captured_amount=progress.captured_amount,
                suggested_refund_amount=suggested_refund(
                    promised, confirmed, basis.completed_refund_amount,
                    basis.pending_refund_amount, basis.captured_amount,
                ),
                promised_at=promise.created_at, deadline=deadline,
                days_since_promise=max((self.now - promise.created_at).days, 0), overdue=overdue,
                ledger_ahead_of_provider=basis.completed_refund_amount > confirmed,
            ))
        return items

    def for_case(self, case_id, merchant_id) -> CasePromiseHealth:
        with self.store.transaction() as connection:
            case = self.workspace._case(connection, case_id, merchant_id)
            return CasePromiseHealth(case_id=case_id, overdue_after_days=self.overdue_days,
                                     items=self._assess(connection, case))

    def attention(self, merchant_id, limit) -> PromiseHealthPage:
        with self.store.transaction() as connection:
            cases = connection.execute(
                "SELECT * FROM resolution_cases WHERE merchant_id=? AND refund_case_id IS NOT NULL",
                (str(merchant_id),),
            ).fetchall()
            flagged = [item for case in cases for item in self._assess(connection, case)
                       if item.status in ATTENTION]
        flagged.sort(key=lambda item: (-item.remaining_amount, -item.days_since_promise, str(item.promise_id)))
        return PromiseHealthPage(overdue_after_days=self.overdue_days, items=flagged[:limit],
                                 total=len(flagged), limit=limit, cases_checked=len(cases))
