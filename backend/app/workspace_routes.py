from .platform_connections import paypal_for
"""HTTP contracts for case workspace and PayPal reconciliation."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from .auth import CurrentMerchant, Store
from .case_workspace import ATTACHMENT_TYPES, MAX_ATTACHMENT, CaseWorkspace
from .errors import StoreError
from .models import (
    CaseAction,
    CaseAttachment,
    CaseResponse,
    PayPalRefundHistory,
    ReviewException,
    ReviewPage,
)
from .paypal_history import PayPalHistoryService, WEBHOOK_MAX_BYTES

router = APIRouter()


async def bounded_body(request, limit):
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal() or len(length) > 12:
            raise StoreError(400, "Invalid Content-Length")
        if int(length) > limit:
            raise StoreError(413, "Request body exceeds the allowed size")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise StoreError(413, "Request body exceeds the allowed size")
        body.extend(chunk)
    return bytes(body)


@router.post(
    "/webhooks/paypal/sandbox",
    status_code=204,
    response_class=Response,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
        "parameters": [
            {
                "name": name,
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            }
            for name in (
                "PayPal-Auth-Algo",
                "PayPal-Cert-Url",
                "PayPal-Transmission-Id",
                "PayPal-Transmission-Sig",
                "PayPal-Transmission-Time",
            )
        ],
    },
    responses={
        400: {"description": "Malformed event or signature headers"},
        401: {"description": "PayPal rejected the event signature"},
        409: {"description": "Existing verified event ID has different content"},
        413: {"description": "Event exceeds 256 KiB"},
        415: {"description": "Event must be JSON"},
        503: {"description": "Signature verification or persistence unavailable"},
    },
)
async def receive_paypal_webhook(request: Request, store: Store):
    """Verify the PayPal signature and persist the delivery before acknowledging it."""
    if (
        request.headers.get("content-type", "").split(";")[0].strip().lower()
        != "application/json"
    ):
        raise StoreError(415, "Use application/json for PayPal events")
    raw = await bounded_body(request, WEBHOOK_MAX_BYTES)
    # This public webhook has no merchant session. Its configured PayPal app,
    # webhook ID and Resolve merchant binding establish the verification scope;
    # never choose a workspace from unverified event fields.
    service = PayPalHistoryService(store, request.app.state.paypal_client)
    await run_in_threadpool(service.receive, request.headers, raw)
    return Response(status_code=204)


@router.post(
    "/cases/{case_id}/paypal-refund-history/refresh", response_model=PayPalRefundHistory
)
def refresh_paypal_history(
    case_id: UUID, request: Request, store: Store, merchant: CurrentMerchant
):
    """Read order, capture and refund details. This endpoint never submits a refund."""
    snapshot, _ = PayPalHistoryService(store, paypal_for(request, merchant.id)).refresh(
        case_id, merchant.id
    )
    return snapshot


@router.post("/cases/{case_id}/close", response_model=CaseResponse)
def close_case(
    case_id: UUID, payload: CaseAction, store: Store, merchant: CurrentMerchant
):
    return CaseWorkspace(store).change_status(
        case_id, merchant.id, closing=True, reason=payload.reason
    )


@router.post("/cases/{case_id}/reopen", response_model=CaseResponse)
def reopen_case(
    case_id: UUID, payload: CaseAction, store: Store, merchant: CurrentMerchant
):
    return CaseWorkspace(store).change_status(
        case_id, merchant.id, closing=False, reason=payload.reason
    )


@router.post(
    "/cases/{case_id}/attachments",
    status_code=201,
    response_model=CaseAttachment,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                key: {"schema": {"type": "string", "format": "binary"}}
                for key in ATTACHMENT_TYPES
            },
        }
    },
)
async def upload_attachment(
    case_id: UUID,
    request: Request,
    store: Store,
    merchant: CurrentMerchant,
    filename: str = Query(min_length=1, max_length=120),
):
    """Attach raw evidence bytes. The filename is supplied as a query parameter."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in ATTACHMENT_TYPES:
        raise StoreError(415, "Use a PDF, PNG or JPEG evidence file")
    content = await bounded_body(request, MAX_ATTACHMENT)
    return await run_in_threadpool(
        CaseWorkspace(store).attach, case_id, merchant.id, filename, media_type, content
    )


@router.get("/cases/{case_id}/attachments", response_model=list[CaseAttachment])
def list_attachments(case_id: UUID, store: Store, merchant: CurrentMerchant):
    return CaseWorkspace(store).attachments(case_id, merchant.id)


@router.get(
    "/cases/{case_id}/attachments/{attachment_id}",
    response_class=Response,
    responses={
        200: {
            "content": {
                key: {"schema": {"type": "string", "format": "binary"}}
                for key in ATTACHMENT_TYPES
            }
        }
    },
)
def download_attachment(
    case_id: UUID, attachment_id: UUID, store: Store, merchant: CurrentMerchant
):
    filename, media_type, content = CaseWorkspace(store).download(
        case_id, merchant.id, attachment_id
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/review-queue", response_model=ReviewPage)
def get_review_queue(
    store: Store,
    merchant: CurrentMerchant,
    status: Literal["open", "resolved"] = "open",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
):
    return CaseWorkspace(store).review(merchant.id, status, limit, offset)


@router.post("/review-queue/{exception_id}/resolve", response_model=ReviewException)
def resolve_exception(
    exception_id: UUID, payload: CaseAction, store: Store, merchant: CurrentMerchant
):
    return CaseWorkspace(store).resolve_review(
        merchant.id, exception_id, payload.reason
    )
