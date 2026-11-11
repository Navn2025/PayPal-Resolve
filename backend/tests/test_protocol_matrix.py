"""Every exported operation gets real ASGI negative-request probes.

This is not positive business-workflow coverage; the evidence report counts those
separately. No provider credential or owner's database is loaded.
"""
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.settings import Settings

schema = json.loads((Path(__file__).resolve().parents[2] / "postman/contracts/resolve.openapi.json").read_text(encoding="utf-8"))
operations = [(method.upper(), path, bool(operation.get("security"))) for path, methods in schema["paths"].items() for method, operation in methods.items() if method in {"get", "post", "put", "patch", "delete"}]


@pytest.fixture(scope="module")
def protocol_client(tmp_path_factory):
    path = tmp_path_factory.mktemp("protocol-matrix") / "resolve.sqlite3"
    with TestClient(create_app(path, settings=Settings(_env_file=None))) as client:
        yield client


@pytest.mark.parametrize("method,path,secured", operations, ids=[method+" "+path for method,path,_ in operations])
@pytest.mark.parametrize("vector", ["no-credentials", "empty-json", "malformed-json"])
def test_operation_rejects_invalid_requests_without_crashing(protocol_client, method, path, secured, vector):
    resource = re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000999", path)
    options = {"follow_redirects": False}
    if vector == "empty-json":
        options["json"] = {}
    if vector == "malformed-json":
        options.update(content=b'{"unfinished":', headers={"Content-Type": "application/json"})
    response = protocol_client.request(method, resource, **options)
    disabled = (method, path) in {
        ("POST", "/customer-account/google/start"), ("POST", "/merchant-auth/paypal/start"),
        ("DELETE", "/merchant-auth/paypal/link"), ("POST", "/webhooks/zendesk/{merchant_id}"),
    }
    if disabled and response.status_code == 503:
        assert isinstance(response.json().get("detail"), str)
    else:
        assert response.status_code < 500, (method, path, vector, response.status_code)
    if secured and not disabled and (method, path) != ("DELETE", "/merchant-auth/session"):
        assert response.status_code in {401, 403, 422}, (method, path, vector, response.status_code)
    if (method, path) == ("DELETE", "/merchant-auth/session"):
        # Logout is intentionally idempotent when no session exists.
        assert response.status_code == 200
    assert "traceback" not in response.text.lower()
    assert "cache-control" in response.headers
