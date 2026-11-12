"""Contracts and validation types for promise health."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel

HealthStatus = Literal["kept", "partially_kept", "at_risk", "broken"]


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
