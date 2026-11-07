"""Run only behind the checked-in local Postman simulation; never real credentials."""

import os
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.main import create_app


pytestmark = pytest.mark.skipif(
    os.environ.get("RESOLVE_RUN_PAYPAL_SIMULATION") != "1",
    reason="Requires the local Postman PayPal simulation and fake credentials",
)


def make_case(client, capture_id="SIMCAPTUREOK"):
    response = client.post(
        "/cases",
        json={
            "order_id": "SANDBOX-ORDER",
            "complaint": "Check the payment",
            "payment": {"capture_id": capture_id, "captured_amount": "100.00"},
            "commitment": {
                "amount": "100.00",
                "status": "accepted",
                "source_message": "Full refund agreed.",
            },
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_sandbox_capture_read_persists_only_scoped_fields(
    sandbox_client, merchant_client
):
    client = sandbox_client
    case_id = make_case(client)
    url = f"/cases/{case_id}/paypal-capture-verifications"
    response = client.post(url)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["capture_id"] == "SIMCAPTUREOK"
    assert saved["captured_amount"] == "100.00"
    assert saved["paypal_merchant_id"] == "SIMSELLER001"
    assert saved["capture_status"] == "COMPLETED"
    assert saved["capture_details_verified"] is True
    assert saved["refund_history_verified"] is False
    assert saved["refund_eligibility_verified"] is False
    assert client.get(url).json() == [saved]
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    assert basis["capture_verification"] == saved
    assert basis["verified_with_paypal"] is False
    database = client.app.state.store.path
    assert b"simulation-secret" not in database.read_bytes()
    assert b"simulation-access-token" not in database.read_bytes()
    api_key = client.headers["Authorization"].split(" ", 1)[1]
    with merchant_client(create_app(database), api_key) as restarted:
        assert restarted.get(url).json() == [saved]
        assert restarted.get(f"/cases/{case_id}/reconciliation").json() == basis


@pytest.mark.parametrize(
    ("capture_id", "expected"),
    [
        ("SIMCAPTURE404", 404),
        ("SIMCAPTURE403", 502),
        ("SIMCAPTURE429", 503),
        ("SIMCAPTURE503", 503),
        ("SIMCAPTUREJSON", 502),
        ("SIMCAPTUREREDIRECT", 502),
        ("SIMCAPTUREAMOUNT", 409),
        ("SIMCAPTUREPAYEE", 409),
        ("SIMCAPTURENOPAYEE", 502),
        ("SIMCAPTUREID", 502),
        ("SIMCAPTUREFLOAT", 502),
        ("SIMCAPTURENAN", 502),
        ("SIMCAPTUREEUR", 502),
        ("SIMCAPTURESTATUS", 502),
    ],
)
def test_provider_failure_or_mismatch_never_creates_successful_verification(
    sandbox_client, capture_id, expected
):
    client = sandbox_client
    case_id = make_case(client, capture_id)
    url = f"/cases/{case_id}/paypal-capture-verifications"
    response = client.post(url)
    assert response.status_code == expected, response.text
    assert "DO-NOT-LEAK-UPSTREAM-BODY" not in response.text
    assert "simulation-secret" not in response.text
    assert "simulation-access-token" not in response.text
    assert client.get(url).json() == []
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["capture_verification"]
        is None
    )


def test_actual_http_timeout_does_not_save_verified_state(sandbox_client):
    client = sandbox_client
    client.app.state.paypal_client.http.timeout = httpx.Timeout(0.15, connect=2.0)
    case_id = make_case(client, "SIMCAPTURETIMEOUT")
    url = f"/cases/{case_id}/paypal-capture-verifications"
    response = client.post(url)
    assert response.status_code == 504, response.text
    assert client.get(url).json() == []


@pytest.mark.parametrize(
    ("client_id", "expected"), [("bad-client", 503), ("malformed-token", 502)]
)
def test_token_errors_are_sanitized_and_not_persisted(
    sandbox_client, client_id, expected
):
    client = sandbox_client
    client.app.state.paypal_client.settings.paypal_sandbox_client_id = SecretStr(
        client_id
    )
    case_id = make_case(client)
    url = f"/cases/{case_id}/paypal-capture-verifications"
    response = client.post(url)
    assert response.status_code == expected, response.text
    assert "DO-NOT-LEAK-UPSTREAM-BODY" not in response.text
    assert client.get(url).json() == []


@pytest.mark.parametrize("status", ["PENDING", "REFUNDED"])
def test_observed_status_does_not_claim_refund_eligibility(sandbox_client, status):
    client = sandbox_client
    case_id = make_case(client, "SIMCAPTURE" + status)
    response = client.post(f"/cases/{case_id}/paypal-capture-verifications")
    assert response.status_code == 201, response.text
    assert response.json()["capture_status"] == status
    assert response.json()["refund_eligibility_verified"] is False


def test_new_provider_evidence_changes_fingerprint_and_invalidates_old_approval(
    sandbox_client,
):
    client = sandbox_client
    case_id = make_case(client)
    before = client.get(f"/cases/{case_id}/reconciliation").json()
    decision = client.post(
        f"/cases/{case_id}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": "SIMCAPTUREOK",
            "amount": "100.00",
            "currency": "USD",
            "state_fingerprint": before["state_fingerprint"],
            "decision_note": "Local decision before reading provider evidence.",
        },
    )
    assert decision.status_code == 201
    approval_id = decision.json()["id"]
    assert (
        client.post(f"/cases/{case_id}/paypal-capture-verifications").status_code == 201
    )
    after = client.get(f"/cases/{case_id}/reconciliation").json()
    assert before["state_fingerprint"] != after["state_fingerprint"]
    assert after["recommended_refund_amount"] == "100.00"
    assert after["verified_with_paypal"] is False
    assert (
        client.get(f"/cases/{case_id}/refund-approvals/{approval_id}").json()["status"]
        == "invalidated"
    )
    fresh = client.post(
        f"/cases/{case_id}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": "SIMCAPTUREOK",
            "amount": "100.00",
            "currency": "USD",
            "state_fingerprint": after["state_fingerprint"],
            "decision_note": "Reviewed capture details; refund history is still local.",
        },
    )
    assert fresh.status_code == 201
    assert fresh.json()["basis"]["capture_verification"] is not None
    assert fresh.json()["verified_with_paypal"] is False


def test_failed_refresh_preserves_previous_observation_and_approval(sandbox_client):
    client = sandbox_client
    case_id = make_case(client)
    url = f"/cases/{case_id}/paypal-capture-verifications"
    assert client.post(url).status_code == 201
    history = client.get(url).json()
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    decision = client.post(
        f"/cases/{case_id}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": "SIMCAPTUREOK",
            "amount": "100.00",
            "currency": "USD",
            "state_fingerprint": basis["state_fingerprint"],
            "decision_note": "Reviewed the existing observation.",
        },
    )
    assert decision.status_code == 201
    client.app.state.paypal_client.settings.paypal_sandbox_merchant_id = (
        "DIFFERENTSELLER"
    )
    assert client.post(url).status_code == 409
    assert client.get(url).json() == history
    assert client.get(f"/cases/{case_id}/reconciliation").json() == basis
    assert (
        client.get(f"/cases/{case_id}/refund-approvals/{decision.json()['id']}").json()[
            "status"
        ]
        == "approved"
    )
