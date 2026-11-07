from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import MerchantIdentity
from .merchant_auth import MerchantAuth
from .storage import ResolveStore


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
    token = credentials.credentials if credentials else ""
    merchant = (
        MerchantAuth(store, request.app.state.settings).merchant(token)
        if token.startswith("rweb_")
        else store.authenticate(token)
        if token
        else None
    )
    if merchant is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing merchant credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return merchant


CurrentMerchant = Annotated[MerchantIdentity, Depends(get_current_merchant)]
