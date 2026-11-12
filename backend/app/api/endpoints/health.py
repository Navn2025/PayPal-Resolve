"""Existing payment-case HTTP contract; service-owned workflows."""

from app.repositories.health import database_ready


from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.dependencies.auth import Store

router = APIRouter()


@router.post("/health", status_code=200)
@router.get("/health", status_code=200)
def health():
    return {
        "status": "ok",
        "service": "case-management-api",
        "mode": "sandbox",
    }


@router.get(
    "/ready", status_code=200, responses={503: {"description": "Database unavailable"}}
)
def readiness(store: Store):
    """Read-only database readiness; never expose storage or exception details."""
    if not database_ready(store):
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}
