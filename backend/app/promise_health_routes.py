"""Merchant API for the broken-promise detector (read-only)."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from .auth import CurrentMerchant, Store
from .next_action import NextAction, collect
from .promise_health import CasePromiseHealth, PromiseHealthCheck, PromiseHealthPage

router = APIRouter(prefix="/resolution-cases", tags=["Promise health"])


def _check(request: Request, store) -> PromiseHealthCheck:
    return PromiseHealthCheck(store, request.app.state.settings.promise_overdue_days)


# Registered before the resolution router so this path is not read as a case ID.
@router.get("/promise-health", response_model=PromiseHealthPage)
def promises_needing_attention(
    request: Request, store: Store, merchant: CurrentMerchant, limit: int = Query(50, ge=1, le=200),
):
    """At-risk and broken refund promises across the merchant's cases, largest amount at risk first."""
    return _check(request, store).attention(merchant.id, limit)


@router.get("/{case_id}/promise-health", response_model=CasePromiseHealth)
def case_promise_health(case_id: UUID, request: Request, store: Store, merchant: CurrentMerchant):
    """Kept, partially kept, at-risk or broken status for each accepted refund promise on one case."""
    return _check(request, store).for_case(case_id, merchant.id)


@router.get("/{case_id}/next-action", response_model=NextAction)
def case_next_action(case_id: UUID, store: Store, merchant: CurrentMerchant):
    """What is missing before a refund, the facts behind it, and a code-written next step. No AI."""
    return collect(case_id, merchant.id, store)
