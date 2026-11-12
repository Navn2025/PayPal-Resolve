"""Full merchant authentication only; advisory review has no payment side effects."""

from hashlib import sha256
from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.dependencies.auth import CurrentMerchant, Store
from app.services.ai.investigations import Investigations
from app.schemas.investigations import (
    InvestigationPage,
    InvestigationReview,
    ReviewReceipt,
)


router = APIRouter(prefix="/resolution-cases", tags=["Private investigations"])


@router.get("/{case_id}/investigations", response_model=InvestigationPage)
def investigations(
    case_id: UUID, response: Response, store: Store, merchant: CurrentMerchant
):
    response.headers["Cache-Control"] = "private, no-store"
    return Investigations(store).list(case_id, merchant.id)


@router.post(
    "/{case_id}/investigations/{investigation_id}/review", response_model=ReviewReceipt
)
def review_investigation(
    case_id: UUID,
    investigation_id: UUID,
    payload: InvestigationReview,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    # Stable pseudonymous key/session identity; never persist credentials.
    identity = (
        "credential_sha256:"
        + sha256(request.headers.get("authorization", "").encode()).hexdigest()
    )
    return Investigations(store).review(
        case_id, investigation_id, merchant.id, payload, identity
    )
