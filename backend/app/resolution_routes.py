from .platform_connections import paypal_for
"""Merchant API for shared resolution cases and promise evidence."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from .auth import CurrentMerchant, Store
from .evidence_models import (
    EvidenceBundle,
    EvidenceCaseUpsert,
    EvidenceCaseView,
    EvidenceInput,
    EvidenceReceipt,
    EvidenceRecordInput,
    EvidenceRefreshResult,
    LinkedEvidenceRecord,
)
from .evidence_workspace import EvidenceWorkspace
from .errors import StoreError
from .resolution_models import (
    MerchantEvidence,
    PromiseRevision,
    PromiseTerms,
    PromiseView,
    RefreshEvidence,
    ResolutionCreate,
    ResolutionPage,
    ResolutionPaymentLink,
    ResolutionTimeline,
    ResolutionView,
)
from .resolution_workspace import ResolutionWorkspace


router = APIRouter(prefix="/resolution-cases", tags=["Resolution workspace"])


@router.post("", status_code=201, response_model=ResolutionView)
def create_resolution(
    payload: ResolutionCreate, store: Store, merchant: CurrentMerchant
):
    """Create a case with or without a linked PayPal refund case."""
    return ResolutionWorkspace(store).create(merchant.id, payload)


@router.get("", response_model=ResolutionPage)
def list_resolutions(
    store: Store,
    merchant: CurrentMerchant,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    return ResolutionWorkspace(store).list(merchant.id, limit, offset)


@router.post(
    "/upsert",
    response_model=EvidenceCaseView,
    responses={409: {"description": "External reference has different case data"}},
)
def upsert_evidence_case(
    payload: EvidenceCaseUpsert, store: Store, merchant: CurrentMerchant
):
    """Create or reuse a resolution case by an exact merchant-scoped external reference."""
    return EvidenceWorkspace(store).upsert(merchant.id, payload)


@router.get("/{case_id}", response_model=EvidenceCaseView)
def get_resolution(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return EvidenceWorkspace(store).get(case_id, merchant.id)


@router.post(
    "/{case_id}/evidence/records",
    response_model=LinkedEvidenceRecord,
    responses={409: {"description": "Conflicting record association"}},
)
def link_evidence_record(
    case_id: UUID, payload: EvidenceRecordInput, store: Store, merchant: CurrentMerchant
):
    """Associate a record reference without contacting its provider."""
    return EvidenceWorkspace(store).link(case_id, merchant.id, payload)


@router.post(
    "/{case_id}/evidence/events",
    response_model=EvidenceReceipt,
    responses={409: {"description": "Source event ID has different evidence"}},
)
def submit_merchant_evidence(
    case_id: UUID, payload: EvidenceInput, store: Store, merchant: CurrentMerchant
):
    """Record merchant evidence once. This cannot approve or execute money movement."""
    return EvidenceWorkspace(store).add(case_id, merchant.id, payload)


@router.post(
    "/{case_id}/evidence/refresh",
    response_model=EvidenceRefreshResult,
    responses={409: {"description": "Linked records changed during the check"}},
)
def refresh_case_evidence(
    case_id: UUID, request: Request, store: Store, merchant: CurrentMerchant
):
    """Check linked PayPal Sandbox records; report incomplete checks without removing prior facts."""
    return EvidenceWorkspace(store).refresh(
        case_id, merchant.id, paypal_for(request, merchant.id)
    )


@router.put("/{case_id}/payment-link", response_model=ResolutionView)
def link_resolution_payment(
    case_id: UUID,
    payload: ResolutionPaymentLink,
    store: Store,
    merchant: CurrentMerchant,
):
    """Attach a merchant-owned payment record once, without calling PayPal."""
    return ResolutionWorkspace(store).link_payment(
        case_id, merchant.id, payload.refund_case_id
    )


@router.post("/{case_id}/promises", status_code=201, response_model=PromiseView)
def record_promise(
    case_id: UUID, payload: PromiseTerms, store: Store, merchant: CurrentMerchant
):
    """Record an agreed remedy and optional prerequisites in this case."""
    return ResolutionWorkspace(store).add_promise(case_id, merchant.id, payload)


@router.put("/{case_id}/promises/{promise_id}", response_model=PromiseView)
def revise_promise(
    case_id: UUID,
    promise_id: UUID,
    payload: PromiseRevision,
    store: Store,
    merchant: CurrentMerchant,
):
    """Revise the exact current version; previous evidence remains in the timeline."""
    terms = PromiseTerms.model_validate(
        payload.model_dump(exclude={"expected_revision"})
    )
    return ResolutionWorkspace(store).revise(
        case_id, promise_id, merchant.id, terms, payload.expected_revision
    )


@router.post(
    "/{case_id}/promises/{promise_id}/evidence",
    status_code=201,
    response_model=PromiseView,
)
def record_promise_evidence(
    case_id: UUID,
    promise_id: UUID,
    payload: MerchantEvidence,
    store: Store,
    merchant: CurrentMerchant,
):
    """Save a note or an explicit internal return finding; never provider proof."""
    return ResolutionWorkspace(store).add_evidence(
        case_id, promise_id, merchant.id, payload
    )


@router.post(
    "/{case_id}/promises/{promise_id}/refresh",
    response_model=PromiseView,
    responses={
        403: {"description": "Provider connector is not configured for this merchant"},
        409: {"description": "Stale revision or conflicting provider evidence"},
        503: {"description": "Provider connector is disabled or unavailable"},
    },
)
def refresh_promise(
    case_id: UUID,
    promise_id: UUID,
    payload: RefreshEvidence,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    """Fetch external evidence. No provider mutation or payment submission."""
    return ResolutionWorkspace(store).refresh(
        case_id,
        promise_id,
        merchant.id,
        paypal_for(request, merchant.id),
        payload.expected_revision,
    )


@router.get("/{case_id}/timeline", response_model=ResolutionTimeline)
def resolution_timeline(
    case_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    before_sequence: int | None = Query(None, ge=1, le=2**53 - 1),
):
    """Read case events newest first; use before_sequence for paging through new activity."""
    if before_sequence is not None and offset:
        raise StoreError(422, "Use either offset or before_sequence")
    return ResolutionWorkspace(store).timeline(
        case_id, merchant.id, limit, offset, before_sequence
    )


@router.get("/{case_id}/evidence-bundle", response_model=EvidenceBundle)
def evidence_bundle(
    case_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    """Export evidence privately for review; does not submit a PayPal dispute."""
    return EvidenceWorkspace(store).bundle(case_id, merchant.id, limit, offset)
