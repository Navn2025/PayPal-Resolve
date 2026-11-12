"""Private responses for the merchant browser login and PayPal callback."""

from app.api.security import PrivateAuthRoute as PrivateAuthRoute


from app.schemas.merchant_auth_routes import (
    Capabilities as Capabilities,
)


from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials

from app.dependencies.auth import Store, bearer
from app.core.exceptions import StoreError
from app.schemas.merchant_auth import (
    CommerceKeys,
    IssuedCommerceKey,
    IssuedMerchantSession,
    MerchantKeyInput,
    MerchantSession,
    PayPalFinish,
    PayPalRedirect,
    PayPalResult,
    PayPalStart,
)
from app.services.merchant.auth import MerchantAuth


router = APIRouter(
    prefix="/merchant-auth",
    tags=["Merchant browser authentication"],
    route_class=PrivateAuthRoute,
)
Credential = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def service(request, store):
    return MerchantAuth(store, request.app.state.settings)


def value(credential):
    return credential.credentials if credential else None


@router.get("/capabilities", response_model=Capabilities)
def capabilities(request: Request, store: Store):
    paypal = service(request, store).paypal
    return Capabilities(
        paypal_enabled=bool(paypal),
        paypal_environment=paypal.environment if paypal else None,
    )


@router.post("/session/key", response_model=IssuedMerchantSession, status_code=201)
def key_login(payload: MerchantKeyInput, request: Request, store: Store):
    return service(request, store).sign_in_key(payload.key)


@router.get("/session", response_model=MerchantSession)
def merchant_session(request: Request, store: Store, credential: Credential):
    session = service(request, store).session(value(credential))
    if not session:
        raise StoreError(401, "Sign in to your merchant workspace")
    return session


@router.delete("/session")
def logout(request: Request, store: Store, credential: Credential):
    service(request, store).sign_out(value(credential))
    return {"signed_out": True}


@router.post("/paypal/start", response_model=PayPalRedirect)
def start_paypal(
    payload: PayPalStart, request: Request, store: Store, credential: Credential
):
    return service(request, store).start(payload.intent, value(credential))


@router.post("/paypal/finish", response_model=PayPalResult)
def finish_paypal(
    payload: PayPalFinish, request: Request, store: Store, credential: Credential
):
    return service(request, store).finish(
        payload, value(credential), request.app.state.followup_http
    )


@router.delete("/paypal/link")
def unlink_paypal(request: Request, store: Store, credential: Credential):
    service(request, store).unlink(value(credential))
    return {"paypal_linked": False}


@router.get("/commerce-keys", response_model=CommerceKeys)
def list_commerce_keys(request: Request, store: Store, credential: Credential):
    """List active SDK key IDs and creation times for the browser session."""
    return service(request, store).commerce_keys(value(credential))


@router.post(
    "/commerce-keys",
    status_code=201,
    response_model=IssuedCommerceKey,
    responses={403: {"description": "Recent full access-key browser sign-in required"}},
)
def issue_commerce_key(request: Request, store: Store, credential: Credential):
    """Create a commerce-only SDK key and return its secret once."""
    return service(request, store).issue_commerce_key(value(credential))


@router.delete(
    "/commerce-keys/{key_id}",
    responses={403: {"description": "Recent full access-key browser sign-in required"}},
)
def revoke_commerce_key(
    key_id: UUID, request: Request, store: Store, credential: Credential
):
    """Revoke one of this merchant's commerce-only keys."""
    service(request, store).revoke_commerce_key(value(credential), key_id)
    return {"revoked": True}
