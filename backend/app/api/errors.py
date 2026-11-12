"""Shared HTTP translation for domain/storage failures."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.exceptions import StoreError


async def handle_store_error(request: Request, error: StoreError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
