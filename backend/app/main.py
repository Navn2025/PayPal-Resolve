from contextlib import asynccontextmanager
import httpx
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse

from .models import (
    CaseCreate,
    CaseResponse,
    ConditionCheck,
    ConditionCheckCreate,
    ReconciliationResponse,
    RefundRecord,
    RefundStatusUpdate,
    MerchantIdentity,
    RefundApproval,
    RefundApprovalCreate,
    RefundApprovalRevoke,
    RefundApprovalEvent,
    PayPalCaptureVerification,
    PayPalRefundVerification,
    PayPalRefundVerificationCreate,
    RefundExecution,
    RefundExecutionCreate,
    RefundExecutionEvent,
    CasePage,
    CommitmentUpdate,
    CaseTimelinePage,
)
from .auth import CurrentMerchant, Store
from .approvals import RefundApprovalService
from .promise_health_routes import router as promise_health_router
from .remedies_routes import router as remedies_router
from .settings import Settings
from .storage import ResolveStore, StoreError, configured_store
from .paypal import PayPalSandboxClient
from .executions import RefundExecutionService
from .workspace_routes import router as workspace_router
from .resolution_routes import router as resolution_router
from .commerce_routes import router as commerce_router
from .investigation_routes import router as investigation_router
from .customer_routes import router as customer_router
from .merchant_auth_routes import router as merchant_auth_router
from .ai_routes import router as ai_router
from .platform_routes import router as platform_router, hooks as support_hooks
from .aftercare_routes import router as aftercare_router
from .assurance_routes import router as assurance_router
from .platform_connections import paypal_for


router = APIRouter()


@router.post("/health", status_code=200)
@router.get("/health", status_code=200)
def health():
    return {
        "status": "ok",
        "service": "case-management-api",
        "mode": "development",
    }


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
    return RefundExecutionService(store, paypal_for(request, merchant.id)).verify_refund(
        case_id, payload.refund_id, merchant.id
    )


@router.get(
    "/cases/{case_id}/paypal-refund-verifications",
    response_model=list[PayPalRefundVerification],
)
def list_paypal_refund_verifications(
    case_id: UUID, store: Store, merchant: CurrentMerchant
):
    return store.list_refund_verifications(case_id, merchant.id)


def create_app(
    database_path: Path | None = None,
    *,
    settings: Settings | None = None,
    store: ResolveStore | None = None,
) -> FastAPI:
    import os
    configuration = settings if settings is not None else Settings(_env_file=None) if os.environ.get("RESOLVE_ISOLATED_TEST") == "1" else Settings()
    store = (
        store
        if store is not None
        else configured_store(configuration, sqlite_path=database_path)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        app.state.paypal_client = PayPalSandboxClient(configuration)
        followup_http = httpx.Client(
            trust_env=False, timeout=10, follow_redirects=False
        )
        app.state.followup_http = followup_http
        try:
            yield
        finally:
            app.state.paypal_client.close()
            followup_http.close()
            store.close()

    application = FastAPI(
        title="Resolve for PayPal API",
        description="Merchant-owned cases, payment evidence, approvals and sandbox refund execution.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.store = store
    application.state.settings = configuration

    @application.middleware("http")
    async def operation_audit(request, call_next):
        response = await call_next(request)
        intent = getattr(request.state, "audit_intent", None)
        if intent:
            from .platform_identity import audit
            with store.transaction(write=True) as db:
                audit(db, request.state.audit_merchant, request.state.actor_id,
                      "request_finished", intent, status=response.status_code)
        if request.url.path.startswith(("/platform", "/webhooks/zendesk")):
            response.headers.update({"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})
        return response

    @application.exception_handler(StoreError)
    async def handle_store_error(request: Request, error: StoreError):
        return JSONResponse(
            status_code=error.status_code, content={"detail": error.detail}
        )

    application.include_router(router)
    application.include_router(workspace_router)
    application.include_router(customer_router)
    application.include_router(merchant_auth_router)
    application.include_router(promise_health_router)  # before /resolution-cases/{case_id}
    application.include_router(remedies_router)
    application.include_router(resolution_router)
    application.include_router(commerce_router)
    application.include_router(investigation_router)
    application.include_router(ai_router)
    application.include_router(platform_router)
    application.include_router(aftercare_router)
    application.include_router(assurance_router)
    application.include_router(support_hooks)
    return application


app = create_app()
