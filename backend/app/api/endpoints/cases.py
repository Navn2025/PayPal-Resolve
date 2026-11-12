"""Existing payment-case HTTP contract; service-owned workflows."""

from uuid import UUID
from fastapi import APIRouter, Query, Request, Response
from app.schemas.payments import (
    CaseCreate,
    CaseResponse,
    ConditionCheck,
    ConditionCheckCreate,
    ReconciliationResponse,
    RefundRecord,
    RefundStatusUpdate,
    MerchantIdentity,
    RefundExecution,
    RefundExecutionCreate,
    CasePage,
    CommitmentUpdate,
    CaseTimelinePage,
)
from app.dependencies.auth import CurrentMerchant, Store
from app.services.payments.executions import RefundExecutionService
from app.dependencies.providers import paypal_for

router = APIRouter()


@router.post("/cases", response_model=CaseResponse, status_code=201)
def create_case(payload: CaseCreate, store: Store, merchant: CurrentMerchant):
    return store.create_case(payload, merchant.id)


@router.get("/cases", response_model=CasePage)
def list_cases(
    store: Store,
    merchant: CurrentMerchant,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    capture_id: str | None = Query(
        default=None, min_length=1, max_length=100, pattern=r"\S"
    ),
):
    return store.list_cases(
        merchant.id, limit=limit, offset=offset, capture_id=capture_id
    )


@router.get("/cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return store.get_case(case_id, merchant.id)


@router.put("/cases/{case_id}/commitment", response_model=CaseResponse)
def update_commitment(
    case_id: UUID, payload: CommitmentUpdate, store: Store, merchant: CurrentMerchant
):
    return store.update_commitment(case_id, payload, merchant.id)


@router.get("/cases/{case_id}/timeline", response_model=CaseTimelinePage)
def get_timeline(
    case_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
):
    return store.timeline(case_id, merchant.id, limit=limit, offset=offset)


@router.post("/cases/{case_id}/refunds", response_model=RefundRecord, status_code=201)
def record_refund(
    case_id: UUID,
    payload: RefundRecord,
    response: Response,
    store: Store,
    merchant: CurrentMerchant,
):
    """Record development refund data. This endpoint does not execute a refund."""
    record, created = store.record_refund(case_id, payload, merchant.id)
    if not created:
        response.status_code = 200
    return record


@router.get("/cases/{case_id}/refunds", response_model=list[RefundRecord])
def list_refunds(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return store.list_refunds(case_id, merchant.id)


@router.patch("/cases/{case_id}/refunds/{refund_id}", response_model=RefundRecord)
def update_refund_status(
    case_id: UUID,
    refund_id: str,
    payload: RefundStatusUpdate,
    store: Store,
    merchant: CurrentMerchant,
):
    return store.update_refund_status(case_id, refund_id, payload, merchant.id)


@router.post(
    "/cases/{case_id}/condition-checks", response_model=ConditionCheck, status_code=201
)
def record_condition_check(
    case_id: UUID,
    payload: ConditionCheckCreate,
    store: Store,
    merchant: CurrentMerchant,
):
    """Record a manual development check, retaining its note and timestamp."""
    return store.record_condition_check(case_id, payload, merchant.id)


@router.get("/cases/{case_id}/condition-checks", response_model=list[ConditionCheck])
def list_condition_checks(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return store.list_condition_checks(case_id, merchant.id)


@router.get("/cases/{case_id}/reconciliation", response_model=ReconciliationResponse)
def get_reconciliation(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return store.reconcile(case_id, merchant.id)


@router.get("/auth/me", response_model=MerchantIdentity)
def get_identity(merchant: CurrentMerchant):
    return merchant


@router.post(
    "/cases/{case_id}/refund-executions",
    response_model=RefundExecution,
    status_code=201,
)
def execute_refund(
    case_id: UUID,
    payload: RefundExecutionCreate,
    response: Response,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    execution, created = RefundExecutionService(
        store, paypal_for(request, merchant.id)
    ).create(case_id, payload, merchant.id)
    if not created:
        response.status_code = 200
    return execution
