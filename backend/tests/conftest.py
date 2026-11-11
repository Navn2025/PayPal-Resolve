import sqlite3
import os
import ssl
from contextlib import contextmanager
from uuid import uuid4

import pytest
import httpx
import json
import time
import re
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from app.main import create_app
from app.paypal import PayPalSandboxClient
from app.postgres import PostgresStore
from app.settings import Settings


def pytest_addoption(parser):
    parser.addoption("--audit-output", default=None, help="Sanitized local endpoint/test evidence JSON")


def pytest_configure(config):
    if not config.getoption("--audit-output"):
        return
    from starlette.testclient import TestClient as StarletteClient
    config._resolve_audit = {"requests": [], "tests": {}, "nodeid": None}
    original = StarletteClient.request
    config._resolve_original_request = original
    contract = json.loads((Path(__file__).resolve().parents[2] / "postman/contracts/resolve.openapi.json").read_text(encoding="utf-8"))
    patterns = []
    for target, operations in sorted(contract["paths"].items(), key=lambda pair: (pair[0].count("{"), pair[0])):
        expression = re.sub(r"\\\{[^{}]+\\\}", "[^/]+", re.escape(target))
        patterns.append((target, re.compile(expression), set(operations)))

    def observed(client, method, url, *args, **kwargs):
        path = urlsplit(str(url)).path
        template = None
        # FastAPI can retain included routers as nested route objects. Match the
        # exported contract instead of silently missing those actual requests.
        # Use the freshly exported contract once, not expensive schema generation
        # for every disposable app. test_openapi_contract verifies export parity.
        for target, pattern, methods in patterns:
            if method.lower() in methods and pattern.fullmatch(path):
                template = target
                break
        started = time.perf_counter()
        try:
            result = original(client, method, url, *args, **kwargs)
            if template:
                config._resolve_audit["requests"].append({"test": config._resolve_audit["nodeid"], "method": method.upper(), "path": template, "status": result.status_code, "milliseconds": round((time.perf_counter()-started)*1000, 3)})
            return result
        except Exception as failure:
            if template:
                config._resolve_audit["requests"].append({"test": config._resolve_audit["nodeid"], "method": method.upper(), "path": template, "exception": type(failure).__name__})
            raise

    StarletteClient.request = observed


def pytest_runtest_setup(item):
    if hasattr(item.config, "_resolve_audit"):
        item.config._resolve_audit["nodeid"] = item.nodeid


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not hasattr(config, "_resolve_audit"):
        return
    terminal = config.pluginmanager.get_plugin("terminalreporter")
    for outcome, reports in terminal.stats.items():
        for report in reports:
            if hasattr(report, "nodeid"):
                config._resolve_audit["tests"][report.nodeid] = outcome
    config._resolve_audit.pop("nodeid", None)
    config._resolve_audit["exit_status"] = int(exitstatus)
    target = Path(config.getoption("--audit-output")).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config._resolve_audit, indent=2) + "\n", encoding="utf-8")
    from starlette.testclient import TestClient as StarletteClient
    StarletteClient.request = config._resolve_original_request


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
def postgres_store():
    url = os.environ.get("RESOLVE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set RESOLVE_TEST_DATABASE_URL to a disposable PostgreSQL database")
    schema = "resolve_test_" + uuid4().hex
    store = PostgresStore(SecretStr(url), schema=schema)
    store.initialize()
    try:
        yield store
    finally:
        with store.transaction(write=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        store.close()


@pytest.fixture
def client(tmp_path, merchant_client, request):
    if os.environ.get("RESOLVE_TEST_STORAGE") == "postgres":
        application = create_app(
            settings=Settings(_env_file=None),
            store=request.getfixturevalue("postgres_store"),
        )
    else:
        application = create_app(tmp_path / "test.sqlite3")
    with merchant_client(application) as test_client:
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
