"""Merchant API for suggested remedies. Suggestions are code-built; creating promises needs the
merchant's request and re-checks the balance; publishing uses /platform/cases/{id}/offers."""

from uuid import UUID

from fastapi import APIRouter, Request

from .auth import CurrentMerchant, Store
from .remedies import CreatedRemedy, CreateRemedy, RemedySuggestions, create, suggest

router = APIRouter(prefix="/resolution-cases", tags=["Suggested remedies"])


def partial_percent(request: Request) -> int:
    return request.app.state.settings.remedy_partial_refund_percent


@router.get("/{case_id}/remedies", response_model=RemedySuggestions)
def suggested_remedies(case_id: UUID, request: Request, store: Store, merchant: CurrentMerchant):
    """Remedy options that are valid now, with amounts from the reconciliation (captured minus
    completed and pending refunds) and the return policy. No model call; nothing is recorded."""
    return suggest(case_id, merchant.id, store, partial_percent(request))


@router.post("/{case_id}/remedies/promises", status_code=201, response_model=CreatedRemedy,
             responses={409: {"description": "The option is no longer valid or the balance changed"}})
def create_remedy_promises(
    case_id: UUID,
    payload: CreateRemedy,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    """Record the promises for the suggested remedy the merchant chose, after recomputing it; its
    `expected_amount` must still match. A capture holds one refund promise, so one option is
    recorded per case. Returns the choice for /platform/cases/{id}/offers but does not publish
    an offer or refund anything."""
    return create(case_id, merchant.id, store, partial_percent(request), payload)
