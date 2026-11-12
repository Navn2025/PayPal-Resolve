"""Existing payment-case HTTP contract; service-owned workflows."""

from uuid import UUID
from fastapi import APIRouter, Request
from app.schemas.payments import (
    PayPalRefundVerificationCreate,
    RefundExecution,
    RefundExecutionEvent,
)
from app.dependencies.auth import CurrentMerchant, Store
from app.services.payments.executions import RefundExecutionService
from app.dependencies.providers import paypal_for

router = APIRouter()


@router.get("/cases/{case_id}/refund-executions", response_model=list[RefundExecution])
def list_refund_executions(
    case_id: UUID, request: Request, store: Store, merchant: CurrentMerchant
):
    return RefundExecutionService(store, paypal_for(request, merchant.id)).list(
        case_id, merchant.id
    )


@router.get(
    "/cases/{case_id}/refund-executions/{execution_id}", response_model=RefundExecution
)
def get_refund_execution(
    case_id: UUID,
    execution_id: UUID,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return RefundExecutionService(store, paypal_for(request, merchant.id)).get(
        case_id, execution_id, merchant.id
    )


@router.post(
    "/cases/{case_id}/refund-executions/{execution_id}/retry",
    response_model=RefundExecution,
)
def retry_refund_execution(
    case_id: UUID,
    execution_id: UUID,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return RefundExecutionService(store, paypal_for(request, merchant.id)).retry(
        case_id, execution_id, merchant.id
    )


@router.post(
    "/cases/{case_id}/refund-executions/{execution_id}/refresh",
    response_model=RefundExecution,
)
def refresh_refund_execution(
    case_id: UUID,
    execution_id: UUID,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
    payload: PayPalRefundVerificationCreate | None = None,
):
    return RefundExecutionService(store, paypal_for(request, merchant.id)).refresh(
        case_id, execution_id, merchant.id, payload.refund_id if payload else None
    )


@router.get(
    "/cases/{case_id}/refund-executions/{execution_id}/events",
    response_model=list[RefundExecutionEvent],
)
def get_execution_events(
    case_id: UUID,
    execution_id: UUID,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return RefundExecutionService(store, paypal_for(request, merchant.id)).events(
        case_id, execution_id, merchant.id
    )
