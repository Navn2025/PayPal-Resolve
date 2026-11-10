from .platform_connections import settings_for
"""Customer-link management and capability-scoped customer access."""

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, SecretStr
from starlette.concurrency import run_in_threadpool

from .auth import CurrentMerchant, Store
from .customer_account import (
    AccountCase,
    AccountToken,
    CustomerAccounts,
    EmailSignIn,
    RedeemSignIn,
)
from .customer_email import email_available
from .customer_google import (
    GoogleCustomerSignIn,
    GoogleFinish,
    GoogleStart,
    google_config,
)
from .customer_portal import (
    CustomerCase,
    CustomerMessageCreate,
    CustomerPortal,
    IssuedLink,
    LinkCreate,
    LinkStatus,
    MessageCreate,
    PortalCredentials,
    PortalMessage,
)
from .errors import StoreError
from .helpdesk import Helpdesk, HelpdeskState, TicketInput
from .merchant_auth import web_origin
from .case_operations import (
    CaseOperations,
    InboxFilter,
    InboxPage,
    MarkRead,
    Operations,
    OperationsUpdate,
)
from .case_workspace import ATTACHMENT_TYPES, MAX_ATTACHMENT
from .customer_evidence import CustomerEvidence, EvidenceFiles
from .customer_intake import (
    Intake,
    IntakeSubmit,
    IntakeView,
    InviteCreate,
    InviteIssued,
)
from .workspace_routes import bounded_body


PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


class PrivatePortalRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def private(request: Request):
            try:
                response = await handle(request)
            except RequestValidationError:
                # Validation errors can include the original input, including a link token.
                response = JSONResponse(
                    {"detail": "Enter a valid customer portal request."},
                    status_code=422,
                )
            except StoreError as error:
                response = JSONResponse(
                    {"detail": error.detail}, status_code=error.status_code
                )
            response.headers.update(PRIVATE_HEADERS)
            return response

        return private


router = APIRouter(tags=["Customer portal"], route_class=PrivatePortalRoute)


@router.get("/resolution-cases/inbox", response_model=InboxPage)
def merchant_inbox(
    store: Store,
    merchant: CurrentMerchant,
    filter_by: InboxFilter = "all",
    q: str = Query("", max_length=160),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
):
    """Filter the merchant's cases before pagination using saved local evidence."""
    return CaseOperations(store).inbox(merchant.id, filter_by, q, limit, offset)


@router.get("/resolution-cases/{case_id}/customer-link", response_model=LinkStatus)
def customer_link_status(case_id: UUID, store: Store, merchant: CurrentMerchant):
    """Read link status without returning the secret token."""
    return CustomerPortal(store).status(case_id, merchant.id)


@router.get("/resolution-cases/{case_id}/helpdesk", response_model=HelpdeskState)
def read_helpdesk(
    case_id: UUID, request: Request, store: Store, merchant: CurrentMerchant
):
    return Helpdesk(store, settings_for(request, merchant.id)).state(case_id, merchant.id)


@router.put("/resolution-cases/{case_id}/helpdesk", response_model=HelpdeskState)
def link_helpdesk(
    case_id: UUID,
    payload: TicketInput,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    return Helpdesk(store, settings_for(request, merchant.id)).link(
        case_id, merchant.id, payload.ticket_id, request.app.state.followup_http
    )


@router.post(
    "/resolution-cases/{case_id}/customer-link",
    response_model=IssuedLink,
    status_code=201,
)
def issue_customer_link(
    case_id: UUID,
    payload: LinkCreate,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
):
    """Replace any previous link and return the new token once."""
    issued = CustomerPortal(store).issue(case_id, merchant.id, payload)
    settings = request.app.state.settings
    origin = web_origin(settings.customer_public_origin or settings.merchant_web_origin)
    return (
        issued.model_copy(update={"public_url": origin + "/customer#" + issued.token})
        if origin
        else issued
    )


@router.delete("/resolution-cases/{case_id}/customer-link", response_model=LinkStatus)
def revoke_customer_link(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return CustomerPortal(store).revoke(case_id, merchant.id)


@router.get(
    "/resolution-cases/{case_id}/customer-messages", response_model=list[PortalMessage]
)
def merchant_read_messages(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return CustomerPortal(store).merchant_messages(case_id, merchant.id)


@router.post(
    "/resolution-cases/{case_id}/customer-messages",
    response_model=PortalMessage,
    status_code=201,
)
def merchant_send_message(
    case_id: UUID, payload: MessageCreate, store: Store, merchant: CurrentMerchant
):
    """Save a buyer-visible reply and queue a notice if the case has an email contact."""
    return CustomerPortal(store).merchant_send(case_id, merchant.id, payload)


@router.post(
    "/customer-portal/view",
    response_model=CustomerCase,
    responses={404: {"description": "Link is invalid, expired, or revoked."}},
)
def customer_view(payload: PortalCredentials, store: Store):
    """Read the case referenced by a valid link. No merchant credential is required."""
    return CustomerPortal(store).read(payload.token)


@router.post(
    "/customer-portal/messages",
    response_model=PortalMessage,
    status_code=201,
    responses={
        404: {"description": "Link is invalid, expired, or revoked."},
        429: {"description": "Send rate limit reached."},
    },
)
def customer_send_message(payload: CustomerMessageCreate, store: Store):
    """Record one message for the linked case; retry with the same request ID."""
    return CustomerPortal(store).customer_send(payload)


@router.post(
    "/resolution-cases/intake-invites", status_code=201, response_model=InviteIssued
)
def create_intake_invite(
    payload: InviteCreate, request: Request, store: Store, merchant: CurrentMerchant
):
    return Intake(store).invite(
        merchant.id,
        payload.order_reference,
        payload.customer_email,
        request.app.state.settings,
        send_email=payload.send_email,
    )


class CustomerAccountCapabilities(BaseModel):
    email_enabled: bool
    google_enabled: bool


@router.get(
    "/customer-account/capabilities", response_model=CustomerAccountCapabilities
)
def customer_account_capabilities(request: Request):
    settings = request.app.state.settings
    return CustomerAccountCapabilities(
        email_enabled=email_available(settings),
        google_enabled=google_config(settings) is not None,
    )


@router.post("/customer-account/google/start", response_model=GoogleStart)
def start_google_sign_in(request: Request, store: Store):
    return GoogleCustomerSignIn(store, request.app.state.settings).start()


@router.post("/customer-account/google/finish", response_model=AccountToken)
def finish_google_sign_in(payload: GoogleFinish, request: Request, store: Store):
    return GoogleCustomerSignIn(store, request.app.state.settings).finish(
        payload, request.app.state.followup_http
    )


@router.post("/customer-account/request-sign-in", status_code=202)
def request_customer_sign_in(payload: EmailSignIn, request: Request, store: Store):
    CustomerAccounts(store).request(payload.email, request.app.state.settings)
    return {"accepted": True}


@router.post("/customer-account/redeem", response_model=AccountToken)
def redeem_customer_sign_in(payload: RedeemSignIn, store: Store):
    return CustomerAccounts(store).redeem(payload.token)


@router.get("/customer-account/cases", response_model=list[AccountCase])
def list_customer_account_cases(store: Store, authorization: str | None = Header(None)):
    return CustomerAccounts(store).cases(authorization)


@router.post("/customer-account/cases/{case_id}/open", response_model=AccountToken)
def open_customer_account_case(
    case_id: UUID, store: Store, authorization: str | None = Header(None)
):
    return CustomerAccounts(store).open_case(authorization, case_id)


@router.post("/customer-account/sign-out")
def customer_sign_out(store: Store, authorization: str | None = Header(None)):
    CustomerAccounts(store).sign_out(authorization)
    return {"signed_out": True}


@router.post("/customer-portal/intake-view", response_model=IntakeView)
def intake_view(payload: PortalCredentials, store: Store):
    return Intake(store).view(payload.token)


@router.post("/customer-portal/intake", response_model=CustomerCase)
def submit_intake(payload: IntakeSubmit, store: Store):
    return Intake(store).submit(payload)


@router.post(
    "/customer-portal/evidence",
    status_code=201,
    response_model=CustomerEvidence,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in ATTACHMENT_TYPES
            },
        }
    },
)
async def customer_upload_evidence(
    request: Request,
    store: Store,
    x_customer_link: SecretStr = Header(),
    x_file_name: str = Header(),
):
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in ATTACHMENT_TYPES:
        raise StoreError(415, "Use a PDF, PNG or JPEG evidence file.")
    content = await bounded_body(request, MAX_ATTACHMENT)
    return await run_in_threadpool(
        EvidenceFiles(store).upload, x_customer_link, x_file_name, content_type, content
    )


def _download_response(file):
    filename, media_type, content = file
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/customer-portal/evidence/{file_id}", response_class=Response)
def buyer_download_evidence(file_id: UUID, payload: PortalCredentials, store: Store):
    return _download_response(
        EvidenceFiles(store).buyer_download(payload.token, file_id)
    )


@router.get(
    "/resolution-cases/{case_id}/customer-evidence",
    response_model=list[CustomerEvidence],
)
def merchant_customer_evidence(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return EvidenceFiles(store).merchant_list(case_id, merchant.id)


@router.get(
    "/resolution-cases/{case_id}/customer-evidence/{file_id}", response_class=Response
)
def merchant_download_evidence(
    case_id: UUID, file_id: UUID, store: Store, merchant: CurrentMerchant
):
    return _download_response(
        EvidenceFiles(store).merchant_download(case_id, merchant.id, file_id)
    )


@router.get("/resolution-cases/{case_id}/operations", response_model=Operations)
def case_operations(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return CaseOperations(store).get(case_id, merchant.id)


@router.put("/resolution-cases/{case_id}/operations", response_model=Operations)
def update_case_operations(
    case_id: UUID, payload: OperationsUpdate, store: Store, merchant: CurrentMerchant
):
    return CaseOperations(store).update(case_id, merchant.id, payload)


@router.post("/resolution-cases/{case_id}/operations/read", response_model=Operations)
def mark_customer_messages_read(
    case_id: UUID, payload: MarkRead, store: Store, merchant: CurrentMerchant
):
    return CaseOperations(store).mark_read(case_id, merchant.id, payload.through)
