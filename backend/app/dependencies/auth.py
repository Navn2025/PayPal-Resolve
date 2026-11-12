from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.schemas.payments import MerchantIdentity
from app.services.merchant.auth import MerchantAuth
from app.repositories.base import ResolveStore


def get_store(request: Request) -> ResolveStore:
    return request.app.state.store


Store = Annotated[ResolveStore, Depends(get_store)]
bearer = HTTPBearer(
    auto_error=False,
    scheme_name="MerchantBearer",
    description="Resolve merchant access key or an authenticated merchant browser session.",
)


def get_current_merchant(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    store: Store,
) -> MerchantIdentity:
    return _merchant(request, credentials, store)


def get_commerce_merchant(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    store: Store,
) -> MerchantIdentity:
    return _merchant(request, credentials, store, allow_commerce=True)


def _merchant(request, credentials, store, *, allow_commerce=False):
    token = credentials.credentials if credentials else ""
    if token.startswith("rweb_"):
        info = MerchantAuth(store, request.app.state.settings).session(token)
        request.state.merchant_session = info
        merchant = info.merchant if info else None
    else:
        merchant = (
            store.authenticate(token, allow_commerce=allow_commerce) if token else None
        )
    if merchant is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing merchant credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from app.services.merchant.identity import enforce_role

    enforce_role(request, merchant, token)
    return merchant


CurrentMerchant = Annotated[MerchantIdentity, Depends(get_current_merchant)]
CurrentCommerceMerchant = Annotated[MerchantIdentity, Depends(get_commerce_merchant)]
