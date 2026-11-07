"""Private responses for the merchant browser login and PayPal callback."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from .auth import Store, bearer
from .errors import StoreError
from .merchant_auth import (
    IssuedMerchantSession,
    MerchantAuth,
    MerchantKeyInput,
    MerchantSession,
    PayPalFinish,
    PayPalRedirect,
    PayPalResult,
    PayPalStart,
)


class PrivateAuthRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "Enter a valid sign-in request"}, status_code=422
                )
            except StoreError as error:
                response = JSONResponse(
                    {"detail": error.detail}, status_code=error.status_code
                )
            response.headers.update(
                {
                    "Cache-Control": "private, no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Robots-Tag": "noindex, nofollow",
                }
            )
            return response

        return private


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


class Capabilities(BaseModel):
    paypal_enabled: bool
    paypal_environment: str | None


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
