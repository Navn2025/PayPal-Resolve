from .platform_connections import paypal_for

"""Bounded merchant commerce evidence API. Request validation never echoes data."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .auth import CurrentCommerceMerchant, CurrentMerchant, Store
from .commerce_models import (
    CommerceContact,
    CommerceOrderDetail,
    CommerceOrderReceipt,
    CommerceOrdersPage,
    CommerceRegisterInput,
    CommerceReport,
    CommerceSyncInput,
    CommerceSyncResult,
)
from .commerce_workspace import CommerceWorkspace
from .errors import StoreError
from .workspace_routes import bounded_body


class PrivateCommerceRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def private(request: Request):
            try:
                if request.url.path.startswith(
                    ("/aftercare/", "/platform/buyer/")
                ) or self.name in (
                    "sync_commerce_order",
                    "register_commerce_order",
                    "open_aftercare_issue",
                    "aftercare_status",
                    "aftercare_portal",
                    "upload_label",
                    "inspect_return",
                    "save_return_guide",
                    "policy_save",
                    "trace_record",
                    "dispute_record",
                    "dispute_document",
                ):
                    body = await bounded_body(
                        request,
                        3 * 1024 * 1024 if self.name == "upload_label" else 32 * 1024,
                    )

                    async def receive():
                        return {
                            "type": "http.request",
                            "body": body,
                            "more_body": False,
                        }

                    request = Request(request.scope, receive)
                response = await handle(request)
            except RequestValidationError:
                response = JSONResponse(
                    {
                        "detail": "Invalid commerce snapshot or case reference. See the commerce API schema."
                    },
                    status_code=422,
                )
            except StoreError as error:
                response = JSONResponse(
                    {"detail": error.detail}, status_code=error.status_code
                )
            response.headers["Cache-Control"] = "private, no-store"
            return response

        return private


router = APIRouter(tags=["Commerce evidence"], route_class=PrivateCommerceRoute)


@router.post(
    "/commerce/orders/sync",
    response_model=CommerceSyncResult,
    responses={
        409: {"description": "Stale/conflicting revision, case, or PayPal reference"},
        413: {"description": "Snapshot exceeds 32 KiB"},
        422: {"description": "Invalid request; details never echo submitted data"},
    },
)
def sync_commerce_order(
    payload: CommerceSyncInput, store: Store, merchant: CurrentCommerceMerchant
):
    """Create or reuse a case and atomically save the latest app order snapshot."""
    return CommerceWorkspace(store).sync(merchant.id, payload)


@router.post(
    "/commerce/orders/register",
    response_model=CommerceOrderReceipt,
    responses={
        409: {"description": "Stale or conflicting order revision or PayPal reference"},
        413: {"description": "Snapshot exceeds 32 KiB"},
        422: {"description": "Invalid request; details never echo submitted data"},
    },
)
def register_commerce_order(
    payload: CommerceRegisterInput, store: Store, merchant: CurrentCommerceMerchant
):
    """Save or update an order for the dashboard without opening a new case."""
    return CommerceWorkspace(store).register(merchant.id, payload)


@router.get("/commerce/orders", response_model=CommerceOrdersPage)
def list_commerce_orders(
    store: Store,
    merchant: CurrentMerchant,
    q: str = Query("", max_length=160),
    source: str = Query(
        "", max_length=64, pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63})?$"
    ),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=2**53 - 1),
):
    """Browse app orders for the authenticated merchant without calling PayPal."""
    return CommerceWorkspace(store).list_orders(
        merchant.id, source=source, q=q, limit=limit, offset=offset
    )


@router.get("/commerce/orders/{order_id}", response_model=CommerceOrderDetail)
def get_registered_order(order_id: UUID, store: Store, merchant: CurrentMerchant):
    """Read the private order snapshot without any shared contact details."""
    return CommerceWorkspace(store).detail(order_id, merchant.id)


@router.post("/commerce/orders/{order_id}/case", response_model=CommerceOrderReceipt)
def open_commerce_case(order_id: UUID, store: Store, merchant: CurrentMerchant):
    """Open or reuse a resolution case and attach the registered order evidence."""
    return CommerceWorkspace(store).open_case(order_id, merchant.id)


@router.get("/resolution-cases/{case_id}/commerce", response_model=CommerceReport)
def get_commerce_order(case_id: UUID, store: Store, merchant: CurrentCommerceMerchant):
    """Compare the app order with the most recent applicable PayPal check."""
    return CommerceWorkspace(store).report(case_id, merchant.id)


@router.post(
    "/resolution-cases/{case_id}/commerce/refresh", response_model=CommerceReport
)
def refresh_commerce_order(
    case_id: UUID, request: Request, store: Store, merchant: CurrentCommerceMerchant
):
    """Read linked PayPal Sandbox evidence and compare. Never mutate payments."""
    return CommerceWorkspace(store).refresh(
        case_id, merchant.id, paypal_for(request, merchant.id)
    )


@router.get(
    "/resolution-cases/{case_id}/commerce/contact", response_model=CommerceContact
)
def get_commerce_contact(case_id: UUID, store: Store, merchant: CurrentMerchant):
    """Read explicitly shared app contact information with full merchant access."""
    return CommerceWorkspace(store).contact(case_id, merchant.id)
