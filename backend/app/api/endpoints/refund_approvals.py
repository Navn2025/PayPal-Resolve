"""Existing payment-case HTTP contract; service-owned workflows."""

from uuid import UUID
from fastapi import APIRouter, Response
from app.schemas.payments import (
    RefundApproval,
    RefundApprovalCreate,
    RefundApprovalRevoke,
    RefundApprovalEvent,
)
from app.dependencies.auth import CurrentMerchant, Store
from app.services.payments.approvals import RefundApprovalService

router = APIRouter()


@router.post(
    "/cases/{case_id}/refund-approvals", response_model=RefundApproval, status_code=201
)
def create_refund_approval(
    case_id: UUID,
    payload: RefundApprovalCreate,
    response: Response,
    store: Store,
    merchant: CurrentMerchant,
):
    approval, created = RefundApprovalService(store).create(
        case_id, payload, merchant.id
    )
    if not created:
        response.status_code = 200
    return approval


@router.get("/cases/{case_id}/refund-approvals", response_model=list[RefundApproval])
def list_refund_approvals(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return RefundApprovalService(store).list(case_id, merchant.id)


@router.get(
    "/cases/{case_id}/refund-approvals/{approval_id}", response_model=RefundApproval
)
def get_refund_approval(
    case_id: UUID,
    approval_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
):
    return RefundApprovalService(store).get(case_id, approval_id, merchant.id)


@router.post(
    "/cases/{case_id}/refund-approvals/{approval_id}/revoke",
    response_model=RefundApproval,
)
def revoke_refund_approval(
    case_id: UUID,
    approval_id: UUID,
    payload: RefundApprovalRevoke,
    store: Store,
    merchant: CurrentMerchant,
):
    return RefundApprovalService(store).revoke(
        case_id, approval_id, payload, merchant.id
    )


@router.get(
    "/cases/{case_id}/refund-approvals/{approval_id}/events",
    response_model=list[RefundApprovalEvent],
)
def get_refund_approval_events(
    case_id: UUID,
    approval_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
):
    return RefundApprovalService(store).events(case_id, approval_id, merchant.id)
