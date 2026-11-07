from uuid import uuid4

import httpx
import pytest

from app.paypal import PayPalSandboxClient
from app.settings import Settings


@pytest.fixture
def paypal_case(client):
    response = client.post("/cases", json={
        "order_id": "ORDER-SANDBOX", "complaint": "Check my payment",
        "payment": {"capture_id": "SIMCAPTUREOK", "captured_amount": "100.00"},
    })
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.parametrize("mode", ["disabled", "incomplete", "other_merchant", "bad_capture"])
def test_config_and_identity_gates_make_no_network_request(client, paypal_case, mode):
    merchant_id = client.get("/auth/me").json()["id"]
    options = dict(
        paypal_sandbox_enabled=True, paypal_resolve_merchant_id=merchant_id,
        paypal_sandbox_client_id="simulation-client", paypal_sandbox_client_secret="simulation-secret",
        paypal_sandbox_merchant_id="SIMSELLER001",
    )
    expected = 503
    if mode == "disabled":
        options["paypal_sandbox_enabled"] = False
    elif mode == "incomplete":
        options["paypal_sandbox_client_secret"] = None
    elif mode == "other_merchant":
        options["paypal_resolve_merchant_id"] = uuid4()
        expected = 403
    else:
        response = client.post("/cases", json={
            "order_id": "BAD-ID", "complaint": "Invalid capture syntax",
            "payment": {"capture_id": "../other?url=https://example.invalid", "captured_amount": "100.00"},
        })
        paypal_case = response.json()["id"]
        expected = 422
    calls = []
    def unexpected_request(request):
        calls.append(request)
        raise AssertionError("Configuration must be checked before network access")
    client.app.state.paypal_client.close()
    client.app.state.paypal_client = PayPalSandboxClient(
        Settings(_env_file=None, **options),
        httpx.Client(transport=httpx.MockTransport(unexpected_request)),
    )
    response = client.post(f"/cases/{paypal_case}/paypal-capture-verifications")
    assert response.status_code == expected
    assert calls == []
    assert client.get(f"/cases/{paypal_case}/paypal-capture-verifications").json() == []


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_paypal_verification_routes_require_merchant_ownership(client, paypal_case, method):
    url = f"/cases/{paypal_case}/paypal-capture-verifications"
    assert client.request(method, url, headers={"Authorization": ""}).status_code == 401
    other = client.app.state.store.create_merchant("Other merchant")
    assert client.request(method, url, headers={
        "Authorization": f"Bearer {other.api_key}"
    }).status_code == 404


def test_paypal_settings_do_not_expose_client_secret_in_repr():
    settings = Settings(_env_file=None, paypal_sandbox_client_secret="fixture-secret-not-real")
    assert "fixture-secret-not-real" not in repr(settings)
    assert settings.paypal_sandbox_enabled is False
