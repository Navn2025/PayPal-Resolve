"""A bounded app-to-Resolve aftercare contract, separate from merchant administration."""

from fastapi import APIRouter, Request

from .aftercare import (
    Aftercare,
    IssueInput,
    IssueReceipt,
    OrderLocator,
    OrderResolution,
)
from .auth import CurrentCommerceMerchant, Store
from .commerce_routes import PrivateCommerceRoute
from .customer_portal import IssuedLink

router = APIRouter(
    prefix="/aftercare", tags=["Embedded aftercare"], route_class=PrivateCommerceRoute
)


def credential(request):
    return request.headers.get("authorization", "").split(" ", 1)[-1]


@router.post("/issues", response_model=IssueReceipt, status_code=201)
def open_aftercare_issue(
    payload: IssueInput,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Aftercare(store).open_issue(
        merchant.id, request.state.actor_id, credential(request), payload
    )


@router.post("/status", response_model=OrderResolution)
def aftercare_status(
    payload: OrderLocator,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Aftercare(store).status(merchant.id, credential(request), payload)


@router.post("/portal", response_model=IssuedLink, status_code=201)
def aftercare_portal(
    payload: OrderLocator,
    request: Request,
    store: Store,
    merchant: CurrentCommerceMerchant,
):
    return Aftercare(store).portal(
        merchant.id,
        request.state.actor_id,
        credential(request),
        payload,
        request.app.state.settings,
    )
