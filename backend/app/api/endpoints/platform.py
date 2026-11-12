"""Merchant operations API and capability-scoped buyer actions."""

from app.repositories import merchant_queries
from app.services.merchant.keys import IntegrationKeys


import json
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.dependencies.auth import CurrentMerchant, Store
from app.services.commerce.aftercare import Aftercare
from app.schemas.aftercare import SupportKeyInput, SupportKeyReceipt, SupportRequestPage
from app.services.customer.portal import CustomerPortal
from app.schemas.customer_portal import PortalCredentials
from app.core.exceptions import StoreError
from app.api.security import PrivateAuthRoute
from app.schemas.platform_connections import ConnectionInput
from app.services.merchant.connections import Connections
from app.schemas.identity import (
    AccountInput,
    AcceptInvite,
    Invite,
    OwnerAccount,
    Signup,
    StaffUpdate,
)
from app.services.merchant.identity import Identities
from app.schemas.platform_imports import ImportMatch, TicketImport
from app.services.merchant.imports import Imports
import app.schemas.platform as contracts
from app.schemas.platform_operations import (
    BuyerReturn,
    OfferCreate,
    OfferDecision,
    PackageCreate,
    ReturnCreate,
    ReturnUpdate,
)
from app.services.merchant.operations import Operations

router = APIRouter(
    prefix="/platform", tags=["Merchant operations"], route_class=PrivateAuthRoute
)
hooks = APIRouter(tags=["Support webhooks"], route_class=PrivateAuthRoute)


def actor(request):
    return request.state.actor_id


@router.post(
    "/account/signup", status_code=201, response_model=contracts.AccountSession
)
def signup(payload: Signup, request: Request, store: Store):
    if not request.app.state.settings.merchant_signup_enabled:
        raise StoreError(403, "Self-service registration is disabled")
    return Identities(store).signup(
        payload, request.client.host if request.client else "unknown"
    )


@router.post("/account/login", response_model=contracts.AccountSession)
def login(payload: AccountInput, request: Request, store: Store):
    return Identities(store).login(
        payload, request.client.host if request.client else "unknown"
    )


@router.post("/account/claim", status_code=201, response_model=contracts.AccountSession)
def claim_owner(
    payload: OwnerAccount, request: Request, store: Store, merchant: CurrentMerchant
):
    if request.state.staff_role != "owner":
        raise StoreError(
            403, "Only the workspace administrator can create the owner account"
        )
    return Identities(store).claim(merchant.id, actor(request), payload)


@router.post(
    "/account/accept-invite", status_code=201, response_model=contracts.AccountSession
)
def accept_invite(payload: AcceptInvite, request: Request, store: Store):
    return Identities(store).accept(
        payload, request.client.host if request.client else "unknown"
    )


@router.get("/me", response_model=contracts.PlatformIdentity)
def me(merchant: CurrentMerchant, request: Request):
    return {
        "merchant": merchant,
        "actor_id": actor(request),
        "role": request.state.staff_role,
    }


@router.get("/team", response_model=contracts.StaffPage)
def team(store: Store, merchant: CurrentMerchant):
    return Identities(store).team(merchant.id)


@router.post("/team/invites", status_code=201, response_model=contracts.Invitation)
def invite(payload: Invite, store: Store, merchant: CurrentMerchant, request: Request):
    return Identities(store).invite(merchant.id, actor(request), payload)


@router.put("/team/{staff_id}", response_model=contracts.StaffPage)
def update_staff(
    staff_id: UUID,
    payload: StaffUpdate,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Identities(store).update(merchant.id, actor(request), staff_id, payload)


@router.get("/audit")
def audit_history(store: Store, merchant: CurrentMerchant):
    return merchant_queries.audit_history(store, merchant.id)


@router.get("/sdk-keys")
def sdk_keys(store: Store, merchant: CurrentMerchant):
    return merchant_queries.sdk_keys(store, merchant.id)


@router.post("/sdk-keys", status_code=201)
def issue_sdk_key(store: Store, merchant: CurrentMerchant, request: Request):
    return IntegrationKeys(store).issue(merchant, actor(request))


@router.post("/support-keys", status_code=201, response_model=SupportKeyReceipt)
def issue_support_key(
    payload: SupportKeyInput, store: Store, merchant: CurrentMerchant, request: Request
):
    return IntegrationKeys(store).issue_support(merchant, actor(request), payload)


@router.delete("/sdk-keys/{key_id}")
def revoke_sdk_key(
    key_id: UUID, store: Store, merchant: CurrentMerchant, request: Request
):
    return IntegrationKeys(store).revoke(merchant, actor(request), key_id)


@router.get("/connections", response_model=contracts.ConnectionPage)
def connections(store: Store, merchant: CurrentMerchant, request: Request):
    return Connections(store, request.app.state.settings).list(merchant.id)


@router.put("/connections/{provider}", response_model=contracts.ConnectionView)
def save_connection(
    provider: str,
    payload: ConnectionInput,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Connections(store, request.app.state.settings).save(
        merchant.id, actor(request), provider, payload
    )


@router.post("/connections/{provider}/check", response_model=contracts.ConnectionView)
def check_connection(
    provider: str, store: Store, merchant: CurrentMerchant, request: Request
):
    return Connections(store, request.app.state.settings).check(
        merchant.id, actor(request), provider, request.app.state.followup_http
    )


@router.get("/imports", response_model=contracts.TicketPage)
def imports(store: Store, merchant: CurrentMerchant, request: Request):
    return Imports(store, request.app.state.settings).list(merchant.id)


@router.post("/imports/zendesk", response_model=contracts.TicketDetail)
def import_ticket(
    payload: TicketImport, store: Store, merchant: CurrentMerchant, request: Request
):
    return Imports(store, request.app.state.settings).fetch(
        merchant.id, actor(request), payload.ticket_id, request.app.state.followup_http
    )


@router.get("/imports/{import_id}", response_model=contracts.TicketDetail)
def imported_ticket(
    import_id: UUID, store: Store, merchant: CurrentMerchant, request: Request
):
    return Imports(store, request.app.state.settings).get(merchant.id, import_id)


@router.put("/imports/{import_id}/match", response_model=contracts.TicketDetail)
def match_ticket(
    import_id: UUID,
    payload: ImportMatch,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Imports(store, request.app.state.settings).match(
        merchant.id, actor(request), import_id, payload.case_id
    )


@router.get("/dashboard", response_model=contracts.Dashboard)
def dashboard(store: Store, merchant: CurrentMerchant):
    return Operations(store).dashboard(merchant.id)


@router.get("/watchdog", response_model=contracts.AlertPage)
def watchdog(store: Store, merchant: CurrentMerchant):
    return Operations(store).alerts(merchant.id)


@router.post("/watchdog/scan", response_model=contracts.AlertPage)
def scan(store: Store, merchant: CurrentMerchant, request: Request):
    return Operations(store).scan(merchant.id, actor(request))


@router.get("/cases/{case_id}/offers", response_model=contracts.OfferPage)
def offers(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return Operations(store).offers(merchant.id, case_id)


@router.get("/cases/{case_id}/support-requests", response_model=SupportRequestPage)
def case_support_requests(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return Aftercare(store).requests(merchant.id, case_id)


@router.post(
    "/cases/{case_id}/offers", status_code=201, response_model=contracts.OfferView
)
def publish_offer(
    case_id: UUID,
    payload: OfferCreate,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Operations(store).publish(merchant.id, actor(request), case_id, payload)


@router.get("/cases/{case_id}/returns", response_model=contracts.ReturnCatalog)
def returns(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return Operations(store).return_catalog(merchant.id, case_id)


@router.post(
    "/cases/{case_id}/returns", status_code=201, response_model=contracts.ReturnView
)
def request_return(
    case_id: UUID,
    payload: ReturnCreate,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Operations(store).request_return(
        merchant.id, actor(request), case_id, payload
    )


@router.put("/cases/{case_id}/returns/{return_id}", response_model=contracts.ReturnView)
def progress_return(
    case_id: UUID,
    return_id: UUID,
    payload: ReturnUpdate,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Operations(store).update_return(
        merchant.id, actor(request), case_id, return_id, payload
    )


@router.get("/cases/{case_id}/dispute-packages", response_model=contracts.PackagePage)
def packages(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return Operations(store).packages(merchant.id, case_id)


@router.post(
    "/cases/{case_id}/dispute-packages",
    status_code=201,
    response_model=contracts.PackageReceipt,
)
def build_package(
    case_id: UUID,
    payload: PackageCreate,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Operations(store).build_package(
        merchant.id, actor(request), case_id, payload
    )


@router.get(
    "/cases/{case_id}/dispute-packages/{package_id}",
    response_model=contracts.PackageDetail,
)
def read_package(
    case_id: UUID, package_id: UUID, store: Store, merchant: CurrentMerchant
):
    return Operations(store).package(merchant.id, case_id, package_id)


@router.post(
    "/cases/{case_id}/dispute-packages/{package_id}/review",
    response_model=contracts.PackageDetail,
)
def review_package(
    case_id: UUID,
    package_id: UUID,
    store: Store,
    merchant: CurrentMerchant,
    request: Request,
):
    return Operations(store).package(
        merchant.id, case_id, package_id, review=True, actor=actor(request)
    )


@router.get("/cases/{case_id}/dispute-packages/{package_id}/export")
def export_package(
    case_id: UUID, package_id: UUID, store: Store, merchant: CurrentMerchant
):
    package = Operations(store).package(merchant.id, case_id, package_id)
    if not package["reviewed"] or package["stale"]:
        raise StoreError(
            409, "Prepare and review a current immutable package before exporting"
        )
    return Response(
        json.dumps(package, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="resolve-dispute-{package_id}.json"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/buyer/offers", response_model=contracts.BuyerOfferPage)
def buyer_offers(payload: PortalCredentials, store: Store):
    return Operations(store).buyer_offers(payload.token)


@router.post("/buyer/decision", response_model=contracts.DecisionReceipt)
def buyer_decision(payload: OfferDecision, store: Store):
    return Operations(store).decide(payload)


@router.post("/buyer/returns", response_model=contracts.ReturnCatalog)
def buyer_returns(payload: PortalCredentials, store: Store):
    with store.transaction() as db:
        link = CustomerPortal._authorized_link(db, payload.token)
    result = Operations(store).return_catalog(
        link["merchant_id"], link["resolution_id"]
    )
    # Return only the customer's order items and fulfillment progress.
    return result


@router.post(
    "/buyer/returns/request", status_code=201, response_model=contracts.ReturnView
)
def buyer_request_return(payload: BuyerReturn, store: Store):
    with store.transaction() as db:
        link = CustomerPortal._authorized_link(db, payload.token)
    return Operations(store).request_return(
        link["merchant_id"], "buyer-link", link["resolution_id"], payload
    )


@hooks.post("/webhooks/zendesk/{merchant_id}", status_code=202)
async def zendesk_hook(merchant_id: UUID, request: Request, store: Store):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise StoreError(413, "Webhook payload is too large")
    return Imports(store, request.app.state.settings).webhook(
        merchant_id, bytes(body), request.headers
    )
