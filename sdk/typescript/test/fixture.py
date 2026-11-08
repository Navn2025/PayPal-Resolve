"""Run the real FastAPI app with synthetic credentials and disposable SQLite."""

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys

import httpx
import uvicorn
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from app.main import create_app
from app.paypal import PayPalSandboxClient, SANDBOX_BASE_URL
from app.settings import Settings


def main():
    simulated = "--paypal-simulation" in sys.argv
    app = create_app(
        Path(sys.argv[1]),
        settings=Settings(
            _env_file=None,
            database_url=None,
            merchant_web_origin="https://resolve.example.test",
            paypal_sandbox_enabled=simulated,
            paypal_sandbox_client_id="simulation-client" if simulated else None,
            paypal_sandbox_client_secret="simulation-secret" if simulated else None,
            paypal_sandbox_merchant_id="SIMSELLER001" if simulated else None,
        ),
    )
    store = app.state.store
    store.initialize()
    primary = store.create_merchant("SDK test workspace")
    other = store.create_merchant("Isolated workspace")
    commerce = store.issue_key(primary.merchant.id, scope="commerce")
    if "--investigations" in sys.argv:
        from app.investigation_worker import run_once
        from app.resolution_workspace import ResolutionWorkspace
        from app.resolution_models import ResolutionCreate
        ResolutionWorkspace(store).create(primary.merchant.id, ResolutionCreate(title="Automatic synthetic investigation"))
        run_once(store)
    if simulated:
        settings = app.state.settings
        settings.paypal_resolve_merchant_id = primary.merchant.id
        proxy = os.environ.get("HTTPS_PROXY", "")
        certificate = os.environ.get("NODE_EXTRA_CA_CERTS")
        if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+/?", proxy) or not certificate:
            raise RuntimeError(
                "Use the local PayPal Postman simulation with --proxy --lift"
            )
        previous = app.router.lifespan_context

        @asynccontextmanager
        async def fixture_lifespan(application):
            async with previous(application):
                application.state.paypal_client.close()
                application.state.paypal_client = PayPalSandboxClient(
                    settings,
                    httpx.Client(
                        proxy=proxy,
                        verify=ssl.create_default_context(cafile=certificate),
                        trust_env=False,
                        follow_redirects=False,
                        timeout=5,
                    ),
                )
                yield

        app.router.lifespan_context = fixture_lifespan

        @app.post("/__fixture/paypal/{action}/{capture_id}", include_in_schema=False)
        def simulate(action: str, capture_id: str, payload: dict):
            if not re.fullmatch(r"SIMHSDK[A-Za-z0-9]+", capture_id) or action not in (
                "external",
                "evidence-outage",
                "state",
            ):
                raise HTTPException(404)
            response = app.state.paypal_client.http.request(
                "GET" if action == "state" else "POST",
                SANDBOX_BASE_URL + "/__resolve_test/" + action + "/" + capture_id,
                headers={"Authorization": "Bearer simulation-access-token"},
                **({} if action == "state" else {"json": payload}),
            )
            response.raise_for_status()
            return response.json()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        # Pipe fixture keys to the test harness, never to the test report.
        descriptor = {
                    "port": port,
                    "key": primary.api_key,
                    "otherKey": other.api_key,
                    "commerceKey": commerce.api_key,
                }
        if "--descriptor" in sys.argv:
            Path(sys.argv[sys.argv.index("--descriptor") + 1]).write_text(json.dumps(descriptor))
        else:
            print(json.dumps(descriptor), flush=True)
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False)).run(
            sockets=[listener]
        )


if __name__ == "__main__":
    main()
