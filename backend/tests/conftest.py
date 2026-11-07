import sqlite3
import os
import ssl
from contextlib import contextmanager

import pytest
import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.paypal import PayPalSandboxClient
from app.settings import Settings


@pytest.fixture
def merchant_client():
    @contextmanager
    def connect(application, api_key=None):
        with TestClient(application) as test_client:
            if api_key is None:
                api_key = application.state.store.create_merchant(
                    "Test merchant"
                ).api_key
            test_client.headers["Authorization"] = f"Bearer {api_key}"
            yield test_client

    return connect


@pytest.fixture
def client(tmp_path, merchant_client):
    with merchant_client(create_app(tmp_path / "test.sqlite3")) as test_client:
        yield test_client


@pytest.fixture
def case_count(client):
    def count():
        with sqlite3.connect(client.app.state.store.path) as connection:
            return connection.execute("SELECT count(*) FROM cases").fetchone()[0]

    return count


@pytest.fixture
def sandbox_client_factory():
    def configure(client):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        certificate = os.environ.get("NODE_EXTRA_CA_CERTS")
        assert proxy and proxy.startswith("http://127.0.0.1:"), (
            "Use postman simulation --proxy --lift"
        )
        assert certificate, "The simulation must provide its local CA certificate"
        context = ssl.create_default_context(cafile=certificate)
        merchant_id = client.get("/auth/me").json()["id"]
        settings = Settings(
            _env_file=None,
            paypal_sandbox_enabled=True,
            paypal_sandbox_refunds_enabled=True,
            paypal_resolve_merchant_id=merchant_id,
            paypal_sandbox_client_id="simulation-client",
            paypal_sandbox_client_secret="simulation-secret",
            paypal_sandbox_merchant_id="SIMSELLER001",
        )
        client.app.state.paypal_client.close()
        client.app.state.paypal_client = PayPalSandboxClient(
            settings,
            httpx.Client(
                proxy=proxy,
                verify=context,
                timeout=httpx.Timeout(5.0, connect=10.0),
                follow_redirects=False,
                trust_env=False,
            ),
        )
        return client

    return configure


@pytest.fixture
def sandbox_client(client, sandbox_client_factory):
    return sandbox_client_factory(client)
