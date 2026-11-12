"""Public API composition; keep static routes before case-ID routes."""

from fastapi import APIRouter
from app.api.endpoints.health import router as health_router
from app.api.endpoints.cases import router as cases_router
from app.api.endpoints.payment_evidence import router as payment_evidence_router
from app.api.endpoints.refund_approvals import router as refund_approvals_router
from app.api.endpoints.refund_executions import router as refund_executions_router
from app.api.endpoints.payment_workspace import router as payment_workspace_router
from app.api.endpoints.customer import router as customer_router
from app.api.endpoints.merchant_auth import router as merchant_auth_router
from app.api.endpoints.promise_health import router as promise_health_router
from app.api.endpoints.remedies import router as remedies_router
from app.api.endpoints.resolutions import router as resolutions_router
from app.api.endpoints.commerce import router as commerce_router
from app.api.endpoints.investigations import router as investigations_router
from app.api.endpoints.ai import router as ai_router
from app.api.endpoints.platform import router as platform_router
from app.api.endpoints.aftercare import router as aftercare_router
from app.api.endpoints.assurance import router as assurance_router
from app.api.endpoints.platform import hooks

router = APIRouter()
router.include_router(health_router)
router.include_router(cases_router)
router.include_router(payment_evidence_router)
router.include_router(refund_approvals_router)
router.include_router(refund_executions_router)
router.include_router(payment_workspace_router)
router.include_router(customer_router)
router.include_router(merchant_auth_router)
router.include_router(promise_health_router)
router.include_router(remedies_router)
router.include_router(resolutions_router)
router.include_router(commerce_router)
router.include_router(investigations_router)
router.include_router(ai_router)
router.include_router(platform_router)
router.include_router(aftercare_router)
router.include_router(assurance_router)
router.include_router(hooks)
