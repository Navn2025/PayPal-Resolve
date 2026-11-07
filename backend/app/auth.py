from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import MerchantIdentity
from .storage import SQLiteStore


def get_store(request: Request) -> SQLiteStore:
    return request.app.state.store


Store = Annotated[SQLiteStore, Depends(get_store)]
bearer = HTTPBearer(
    auto_error=False, scheme_name="MerchantBearer",
    description="Paste the local merchant token created by app.manage.",
)


def get_current_merchant(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    store: Store,
) -> MerchantIdentity:
    merchant = store.authenticate(credentials.credentials) if credentials else None
    if merchant is None:
        raise HTTPException(
            status_code=401, detail="Invalid or missing merchant credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return merchant


CurrentMerchant = Annotated[MerchantIdentity, Depends(get_current_merchant)]
