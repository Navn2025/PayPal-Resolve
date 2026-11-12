"""Existing payment-case HTTP contract; service-owned workflows."""

from uuid import UUID
from fastapi import APIRouter, Request
from app.schemas.payments import (
    PayPalCaptureVerification,
    PayPalRefundVerification,
    PayPalRefundVerificationCreate,
)
from app.dependencies.auth import CurrentMerchant, Store
from app.services.payments.executions import RefundExecutionService
from app.dependencies.providers import paypal_for

router = APIRouter()


@router.post(
    "/cases/{case_id}/paypal-capture-verifications",
    response_model=PayPalCaptureVerification,
    status_code=201,
)
def verify_paypal_capture(
    case_id: UUID, request: Request, store: Store, merchant: CurrentMerchant
):
    case = store.get_case(case_id, merchant.id)
    capture = paypal_for(request, merchant.id).read_capture(case)
    return store.record_capture_verification(case_id, merchant.id, capture)


@router.get(
    "/cases/{case_id}/paypal-capture-verifications",
    response_model=list[PayPalCaptureVerification],
)
def list_paypal_capture_verifications(
    case_id: UUID, store: Store, merchant: CurrentMerchant
):
    return store.list_capture_verifications(case_id, merchant.id)


@router.post(
    "/cases/{case_id}/paypal-refund-verifications",
    response_model=PayPalRefundVerification,
    status_code=201,
)
def verify_paypal_refund(
    case_id: UUID,
    payload: PayPalRefundVerificationCreate,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return RefundExecutionService(
        store, paypal_for(request, merchant.id)
    ).verify_refund(case_id, payload.refund_id, merchant.id)


@router.get(
    "/cases/{case_id}/paypal-refund-verifications",
    response_model=list[PayPalRefundVerification],
)
def list_paypal_refund_verifications(
    case_id: UUID, store: Store, merchant: CurrentMerchant
):
    return store.list_refund_verifications(case_id, merchant.id)
