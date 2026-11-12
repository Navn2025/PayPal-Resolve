"""Assurance APIs share existing ownership, role, body and buyer capability boundaries."""

from app.services.assurance.buyer import buyer_order as resolve_buyer_order


from app.schemas.assurance_api import (
    BuyerLabelLocator as BuyerLabelLocator,
    BuyerReturnLocator as BuyerReturnLocator,
    ContextRequest as ContextRequest,
    EligibilityInput as EligibilityInput,
    LabelInput as LabelInput,
    LabelLocator as LabelLocator,
    ReturnLocator as ReturnLocator,
    SupportReturn as SupportReturn,
)


import base64
import binascii
from uuid import UUID

from fastapi import APIRouter, Request

from app.services.commerce.aftercare import Aftercare
from app.schemas.aftercare import IssueReceipt, OrderLocator
from app.api.endpoints.aftercare import credential
from app.dependencies.auth import CurrentCommerceMerchant, CurrentMerchant, Store
from app.api.endpoints.commerce import PrivateCommerceRoute
from app.services.customer.portal import CustomerPortal
from app.schemas.customer_portal import PortalCredentials
from app.schemas.dispute_guard import DisputeEvent
from app.services.assurance.dispute_guard import Disputes
from app.schemas.dispute_evidence import DisputeDocument
from app.services.assurance.dispute_evidence import record_document
from app.core.exceptions import StoreError
from app.services.merchant.operations import Operations
from app.schemas.platform_operations import ReturnCreate
from app.schemas.platform import ReturnView, ReturnCatalog
from app.services.assurance.resolution import Assurance
from app.schemas.resolution_assurance import (
    ContextView,
    LookupIssue,
    RefundJourney,
    TraceInput,
)
from app.services.assurance.returns import Returns
from app.schemas.return_assurance import (
    PolicyUpdate,
    PolicyView,
    PublicReturnPolicy,
    GuideInput,
    InspectionInput,
    EligibilityView,
    ReturnGuideView,
    ReturnLabelFile,
)
from app.schemas.sdk_events import EventPull, EventPage
from app.services.commerce.events import Events

router = APIRouter(tags=["Resolution assurance"], route_class=PrivateCommerceRoute)


def owned_case(store, merchant, token, locator):
    with store.transaction() as db:
        row = Aftercare(store)._order(db, merchant, token, locator)
        if not row["resolution_id"]:
            raise StoreError(409, "Open an issue for this order first")
        return row["resolution_id"]


def buyer_order(store, token):
    return resolve_buyer_order(store, token)


@router.get("/platform/return-policy", response_model=PolicyView)
def policy(store: Store, merchant: CurrentMerchant):
    return Returns(store).policy(merchant.id)


@router.put("/platform/return-policy", response_model=PolicyView)
def policy_save(
    payload: PolicyUpdate, request: Request, store: Store, merchant: CurrentMerchant
):
    return Returns(store).save_policy(merchant.id, request.state.actor_id, payload)


@router.post("/cases/{case_id}/disputes")
def dispute_record(
    case_id: UUID,
    payload: DisputeEvent,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return Disputes(store).record(merchant.id, request.state.actor_id, case_id, payload)


@router.get("/cases/{case_id}/disputes")
def dispute_list(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return Disputes(store).list(merchant.id, case_id)


@router.get("/platform/cases/{case_id}/disputes")
def resolution_disputes(case_id: UUID, store: Store, merchant: CurrentMerchant):
    with store.transaction() as db:
        case = Aftercare(store).workspace._case(db, case_id, merchant.id)
        payment = case["refund_case_id"]
    if not payment:
        return {"capture_held": False, "items": []}
    return Disputes(store).list(merchant.id, payment)


@router.post("/platform/cases/{case_id}/disputes")
def resolution_dispute_record(
    case_id: UUID,
    payload: DisputeEvent,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    with store.transaction() as db:
        case = Aftercare(store).workspace._case(db, case_id, merchant.id)
        payment = case["refund_case_id"]
    if not payment:
        raise StoreError(409, "Link the payment before recording a dispute")
    return Disputes(store).record(merchant.id, request.state.actor_id, payment, payload)


@router.post("/platform/cases/{case_id}/refund-traces")
def trace_record(
    case_id: UUID,
    payload: TraceInput,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return Assurance(store).record_trace(
        merchant.id, request.state.actor_id, case_id, payload
    )


@router.post("/platform/cases/{case_id}/dispute-documents")
def dispute_document(
    case_id: UUID,
    payload: DisputeDocument,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return record_document(store, merchant.id, request.state.actor_id, case_id, payload)


@router.get(
    "/platform/cases/{case_id}/returns/{return_id}/guide",
    response_model=ReturnGuideView,
)
def return_guide(
    case_id: UUID, return_id: UUID, store: Store, merchant: CurrentMerchant
):
    return Returns(store).guide(merchant.id, case_id, return_id)


@router.put(
    "/platform/cases/{case_id}/returns/{return_id}/guide",
    response_model=ReturnGuideView,
)
def save_return_guide(
    case_id: UUID,
    return_id: UUID,
    payload: GuideInput,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return Returns(store).save_guide(
        merchant.id, request.state.actor_id, case_id, return_id, payload
    )


@router.post("/platform/cases/{case_id}/returns/{return_id}/inspection")
def inspect_return(
    case_id: UUID,
    return_id: UUID,
    payload: InspectionInput,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return Returns(store).inspect(
        merchant.id,
        request.state.actor_id,
        request.state.staff_role,
        case_id,
        return_id,
        payload,
    )


@router.post("/platform/cases/{case_id}/returns/{return_id}/labels")
def upload_label(
    case_id: UUID,
    return_id: UUID,
    payload: LabelInput,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise StoreError(422, "Send a valid base64 PDF label") from None
    return Returns(store).upload_label(
        merchant.id, request.state.actor_id, case_id, return_id, payload.filename, raw
    )


@router.post("/aftercare/journey", response_model=RefundJourney)
def refund_journey(
    payload: OrderLocator,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Assurance(store).journey(merchant.id, credential(request), payload)


@router.post("/aftercare/context", response_model=ContextView)
def support_context(
    payload: ContextRequest,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Assurance(store).context(
        merchant.id, credential(request), payload, payload.before_sequence
    )


@router.post("/aftercare/received", response_model=RefundJourney)
def received_refund(
    payload: OrderLocator,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Assurance(store).acknowledge(
        merchant.id, request.state.actor_id, credential(request), payload
    )


@router.post("/aftercare/issues/lookup", response_model=IssueReceipt)
def issue_lookup(
    payload: LookupIssue,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Assurance(store).lookup(merchant.id, credential(request), payload)


@router.post("/aftercare/events", response_model=EventPage)
def event_pull(
    payload: EventPull,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Events(store).pull(merchant.id, credential(request), payload)


@router.post("/aftercare/returns/eligibility", response_model=EligibilityView)
def check_eligibility(
    payload: EligibilityInput,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    with store.transaction() as db:
        order = Aftercare(store)._order(db, merchant.id, credential(request), payload)
        # Exact quantity and duplicate reservation checks still run on final request.
        return Returns.eligible_in(
            db, merchant.id, order, payload.items, payload.delivered_at
        )


@router.post("/aftercare/returns", response_model=ReturnCatalog)
def support_returns(
    payload: OrderLocator,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    case_id = owned_case(store, merchant.id, credential(request), payload)
    return Operations(store).return_catalog(merchant.id, case_id)


@router.post("/aftercare/returns/request", response_model=ReturnView, status_code=201)
def support_return_request(
    payload: SupportReturn,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    case_id = owned_case(store, merchant.id, credential(request), payload)
    with store.transaction() as db:
        order = Aftercare(store)._order(db, merchant.id, credential(request), payload)
        order_id = order["id"]
    body = ReturnCreate(
        order_id=order_id,
        request_id=payload.request_id,
        reason=payload.reason,
        items=payload.items,
        delivered_at=payload.delivered_at,
    )
    return Operations(store).request_return(
        merchant.id, request.state.actor_id, case_id, body
    )


@router.post("/aftercare/returns/guide", response_model=ReturnGuideView)
def support_return_guide(
    payload: ReturnLocator,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    case_id = owned_case(store, merchant.id, credential(request), payload)
    return Returns(store).guide(merchant.id, case_id, payload.return_id)


@router.post("/aftercare/returns/label", response_model=ReturnLabelFile)
def support_label(
    payload: LabelLocator,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    case_id = owned_case(store, merchant.id, credential(request), payload)
    name, raw = Returns(store).label(
        merchant.id, case_id, payload.return_id, payload.label_id
    )
    return {
        "filename": name,
        "content_type": "application/pdf",
        "content_base64": base64.b64encode(raw).decode(),
    }


@router.post("/platform/buyer/assurance")
def buyer_assurance(payload: PortalCredentials, store: Store):
    link, locator = buyer_order(store, payload.token)
    # Token was validated against the current link; only this case's owned order is read.
    return {
        "journey": Assurance(store)
        .journey(link["merchant_id"], "rweb_buyer", locator)
        .model_dump(mode="json"),
        "context": Assurance(store)
        .context(link["merchant_id"], "rweb_buyer", locator)
        .model_dump(mode="json"),
    }


@router.post("/platform/buyer/returns/guide", response_model=ReturnGuideView)
def buyer_guide(payload: BuyerReturnLocator, store: Store):
    with store.transaction() as db:
        link = CustomerPortal._authorized_link(db, payload.token)
    return Returns(store).guide(
        link["merchant_id"], link["resolution_id"], payload.return_id
    )


@router.post("/platform/buyer/returns/label", response_model=ReturnLabelFile)
def buyer_label(payload: BuyerLabelLocator, store: Store):
    with store.transaction() as db:
        link = CustomerPortal._authorized_link(db, payload.token)
    name, raw = Returns(store).label(
        link["merchant_id"], link["resolution_id"], payload.return_id, payload.label_id
    )
    return {
        "filename": name,
        "content_type": "application/pdf",
        "content_base64": base64.b64encode(raw).decode(),
    }


@router.post("/platform/buyer/return-policy", response_model=PublicReturnPolicy)
def buyer_return_policy(payload: PortalCredentials, store: Store):
    with store.transaction() as db:
        link = CustomerPortal._authorized_link(db, payload.token)
    return Returns(store).public_policy(link["merchant_id"])
