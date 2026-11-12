from app.api.middleware import install_middleware
from app.api.errors import handle_store_error
from contextlib import asynccontextmanager
import httpx
from pathlib import Path
from fastapi import FastAPI
from app.core.config import Settings
from app.repositories.base import ResolveStore
from app.repositories.sqlite import StoreError
from app.repositories.factory import configured_store
from app.integrations.paypal.client import PayPalSandboxClient
from app.api.router import router


def create_app(
    database_path: Path | None = None,
    *,
    settings: Settings | None = None,
    store: ResolveStore | None = None,
) -> FastAPI:
    import os

    configuration = (
        settings
        if settings is not None
        else Settings(_env_file=None)
        if os.environ.get("RESOLVE_ISOLATED_TEST") == "1"
        else Settings()
    )
    store = (
        store
        if store is not None
        else configured_store(configuration, sqlite_path=database_path)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        app.state.paypal_client = PayPalSandboxClient(configuration)
        followup_http = httpx.Client(
            trust_env=False, timeout=10, follow_redirects=False
        )
        app.state.followup_http = followup_http
        try:
            yield
        finally:
            app.state.paypal_client.close()
            followup_http.close()
            store.close()

    application = FastAPI(
        title="Resolve for PayPal API",
        description="Merchant-owned cases, payment evidence, approvals and sandbox refund execution.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.store = store
    application.state.settings = configuration

    install_middleware(application, store)
    application.add_exception_handler(StoreError, handle_store_error)
    application.include_router(router)
    return application
