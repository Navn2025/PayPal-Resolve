"""Isolated FastAPI test fixture; never loads a merchant's .env or database."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import ssl
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.main import create_app
from app.customer_email import mail_token
from app.models import CaseCreate
from app.paypal import PayPalSandboxClient, SANDBOX_BASE_URL
from app.resolution_models import PromiseTerms, ResolutionCreate
from app.resolution_workspace import ResolutionWorkspace
from app.settings import Settings


FIXTURE_TOKEN = "rslv_ui_test_fixture_key_not_a_real_secret"
MERCHANT_ID = UUID("55555555-1111-4444-8888-000000000001")
CAPTURE = "SIMHUIWORKSPACE"
STALE_CAPTURE = "SIMHUISTALE"
SIMULATED = os.environ.get("RESOLVE_UI_PAYPAL_SIMULATION") == "1"
PAYPAL_LOGIN_FIXTURE = os.environ.get("RESOLVE_UI_PAYPAL_LOGIN") == "1"
EMAIL_FIXTURE = os.environ.get("RESOLVE_UI_EMAIL_FIXTURE") == "1"
GOOGLE_FIXTURE = os.environ.get("RESOLVE_UI_GOOGLE_FIXTURE") == "1"
EMAIL_KEY = "synthetic-browser-signing-key-no-real-email"


def sandbox_http():
    proxy = os.environ.get("HTTPS_PROXY", "")
    address = urlsplit(proxy)
    certificate = os.environ.get("NODE_EXTRA_CA_CERTS")
    if address.scheme != "http" or address.hostname != "127.0.0.1" or not certificate:
        raise RuntimeError("Use the local Postman TLS proxy with --lift")
    return httpx.Client(
        proxy=proxy,
        verify=ssl.create_default_context(cafile=certificate),
        timeout=httpx.Timeout(5.0, connect=10.0),
        trust_env=False,
        follow_redirects=False,
    )


def main():
    with TemporaryDirectory() as folder:
        settings = Settings(
            _env_file=None,
            database_path=Path(folder) / "browser-test.sqlite3",
            paypal_sandbox_enabled=SIMULATED,
            paypal_sandbox_refunds_enabled=SIMULATED,
            paypal_sandbox_partial_refunds_enabled=SIMULATED,
            paypal_resolve_merchant_id=MERCHANT_ID,
            paypal_sandbox_client_id="simulation-client",
            paypal_sandbox_client_secret="simulation-secret",
            paypal_sandbox_merchant_id="SIMSELLER001",
            merchant_web_origin="http://127.0.0.1:3100" if PAYPAL_LOGIN_FIXTURE else None,
            paypal_login_enabled=PAYPAL_LOGIN_FIXTURE,
            paypal_login_client_id="simulation-login-client",
            paypal_login_client_secret="simulation-login-secret",
            customer_email_enabled=EMAIL_FIXTURE,
            customer_email_merchant_id=MERCHANT_ID,
            customer_public_origin="http://127.0.0.1:3100" if GOOGLE_FIXTURE else "https://resolve.example.com",
            customer_signing_key=EMAIL_KEY,
            resend_api_key="fake-browser-resend-key",
            resend_from="updates@example.com",
            customer_google_enabled=GOOGLE_FIXTURE,
            google_client_id="simulation-google-client",
            google_client_secret="simulation-google-secret",
        )
        app = create_app(settings=settings)
        store = app.state.store
        store.initialize()
        timestamp = datetime.now(timezone.utc).isoformat()
        with store.transaction(write=True) as connection:
            connection.execute("INSERT INTO merchants VALUES (?,?,?)",
                               (str(MERCHANT_ID), "Workspace Test Shop", timestamp))
            connection.execute(
                "INSERT INTO merchant_api_keys(id,merchant_id,token_hash,created_at) VALUES (?,?,?,?)",
                (str(uuid4()), str(MERCHANT_ID), sha256(FIXTURE_TOKEN.encode()).hexdigest(), timestamp),
            )
        workspace = ResolutionWorkspace(store)
        if EMAIL_FIXTURE:
            @app.get("/__ui_fixture_login_token", include_in_schema=False)
            def email_fixture():
                with store.transaction() as connection:
                    row = connection.execute(
                        """SELECT id FROM customer_mail_outbox WHERE kind='signin'
                           AND recipient='browser-buyer@example.com' ORDER BY created_at DESC LIMIT 1"""
                    ).fetchone()
                return {"token": mail_token(EMAIL_KEY.encode(), "signin", row["id"]) if row else None}
        cases = [("Connected refund fixture", CAPTURE)]
        if SIMULATED:
            cases.append(("Outside refund fixture", STALE_CAPTURE))
        for title, capture_id in cases:
            payment = store.create_case(
                CaseCreate(
                    order_id="SIMORDER" + capture_id, complaint=title,
                    payment={"capture_id": capture_id, "captured_amount": "100.00"},
                    commitment={"amount": "30.00", "status": "accepted", "source_message": "Agreed refund"},
                ),
                MERCHANT_ID,
            )
            case = workspace.create(MERCHANT_ID, ResolutionCreate(
                title=title, order_reference="UI-TEST-ORDER", refund_case_id=payment.id,
            ))
            milestone = workspace.add_promise(case.id, MERCHANT_ID, PromiseTerms(
                promise="Receive the return at the warehouse", source_note="Accepted return terms",
                target={"kind": "return", "milestone": "warehouse_received", "return_reference": "UI-TEST-RMA"},
            ))
            workspace.add_promise(case.id, MERCHANT_ID, PromiseTerms(
                promise="Refund $30 after warehouse receipt", source_note="Agreed refund",
                target={"kind": "refund", "amount": "30.00"}, requires=[milestone.id],
            ))
        if SIMULATED:
            with sandbox_http() as client:
                for _, capture_id in cases:
                    result = client.post(
                        SANDBOX_BASE_URL + "/__resolve_test/external/" + capture_id,
                        headers={"Authorization": "Bearer simulation-access-token"},
                        json={"cents": 1000, "status": "COMPLETED"},
                    )
                    result.raise_for_status()

            @app.post("/__ui_fixture_outside_refund", include_in_schema=False)
            def outside_refund():
                with sandbox_http() as client:
                    response = client.post(
                        SANDBOX_BASE_URL + "/__resolve_test/external/" + STALE_CAPTURE,
                        headers={"Authorization": "Bearer simulation-access-token"},
                        json={"cents": 2000, "status": "COMPLETED"},
                    )
                    response.raise_for_status()
                return {"recorded": True}

            @app.get("/__ui_fixture_outside_stats", include_in_schema=False)
            def outside_stats():
                with sandbox_http() as client:
                    response = client.get(
                        SANDBOX_BASE_URL + "/__resolve_test/state/" + STALE_CAPTURE,
                        headers={"Authorization": "Bearer simulation-access-token"},
                    )
                    response.raise_for_status()
                    return response.json()

            original = app.router.lifespan_context

            @asynccontextmanager
            async def test_lifespan(application):
                async with original(application):
                    application.state.paypal_client.close()
                    application.state.paypal_client = PayPalSandboxClient(settings, sandbox_http())
                    if PAYPAL_LOGIN_FIXTURE:
                        application.state.followup_http = application.state.paypal_client.http
                    yield

            app.router.lifespan_context = test_lifespan
        if GOOGLE_FIXTURE:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "tests"))
            from google_simulation_support import register_google_code

            @app.post("/__ui_fixture_google_consent", include_in_schema=False)
            def google_fixture(parameters: dict[str, str]):
                with sandbox_http() as http:
                    return {"code": register_google_code(http, parameters)}

            previous_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def google_lifespan(application):
                async with previous_lifespan(application):
                    with sandbox_http() as http:
                        application.state.followup_http = http
                        yield

            app.router.lifespan_context = google_lifespan
        uvicorn.run(app, host="127.0.0.1", port=8011, access_log=False)


if __name__ == "__main__":
    main()
