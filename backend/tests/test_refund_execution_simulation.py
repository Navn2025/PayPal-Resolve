"""Actual HTTP caller behavior behind the local Postman TLS proxy; fake money only."""

import os
from uuid import uuid4

import httpx
import pytest

from app.main import create_app
from app.paypal import SANDBOX_BASE_URL
from app.worker import run_once
from datetime import datetime, timedelta, timezone


pytestmark = pytest.mark.skipif(
    os.environ.get("RESOLVE_RUN_PAYPAL_SIMULATION") != "1",
    reason="Requires the local Postman PayPal simulation and fake credentials",
)


def ready(client, mode="COMPLETE"):
    capture_id = "SIMEXEC" + mode + uuid4().hex[:10].upper()
    result = client.post(
        "/cases",
        json={
            "order_id": "SIMULATION-ORDER",
            "complaint": "Simulated full refund",
            "payment": {"capture_id": capture_id, "captured_amount": "100.00"},
            "commitment": {
                "amount": "100.00",
                "status": "accepted",
                "source_message": "Simulated test agreement.",
            },
        },
    )
    assert result.status_code == 201
    case_id = result.json()["id"]
    verified = client.post(f"/cases/{case_id}/paypal-capture-verifications")
    assert verified.status_code == 201, verified.text
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    decision = client.post(
        f"/cases/{case_id}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": capture_id,
            "amount": "100.00",
            "state_fingerprint": basis["state_fingerprint"],
            "decision_note": "Simulated full-refund approval.",
        },
    )
    assert decision.status_code == 201
    return (
        case_id,
        {"request_id": str(uuid4()), "approval_id": decision.json()["id"]},
        capture_id,
    )


def statistics(client, capture_id):
    # Simulation-only observability: protected by fake auth and a required loopback proxy.
    response = client.app.state.paypal_client.http.get(
        SANDBOX_BASE_URL + "/__resolve_test/state/" + capture_id,
        headers={"Authorization": "Bearer simulation-access-token"},
    )
    assert response.status_code == 200
    return response.json()


def test_real_http_full_refund_persists_and_replay_creates_one_provider_refund(
    sandbox_client,
):
    client = sandbox_client
    case_id, body, capture_id = ready(client)
    url = f"/cases/{case_id}/refund-executions"
    response = client.post(url, json=body)
    assert response.status_code == 201, response.text
    execution = response.json()
    assert execution["status"] == "completed"
    assert execution["provider_refund"]["amount"] == "100.00"
    assert execution["provider_refund"]["refund_details_verified"] is True
    assert client.post(url, json=body).status_code == 200
    counters = statistics(client, capture_id)
    assert counters["refund_creations"] == 1 and counters["refund_posts"] == 1
    assert counters["request_ids"] == [execution["provider_request_id"]]
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    assert (
        basis["status"] == "fulfilled" and basis["completed_refund_amount"] == "100.00"
    )
    assert basis["verified_with_paypal"] is False
    assert (
        client.post(f"/cases/{case_id}/paypal-capture-verifications").json()[
            "capture_status"
        ]
        == "REFUNDED"
    )
    database = client.app.state.store.path.read_bytes()
    assert (
        b"simulation-secret" not in database
        and b"simulation-access-token" not in database
    )


@pytest.mark.parametrize("mode", ["TIMEOUT", "BADJSON", "BADAMOUNT", "BADPARENT"])
def test_ambiguous_http_response_recovers_after_restart_without_duplicate_refund(
    sandbox_client, merchant_client, sandbox_client_factory, mode
):
    client = sandbox_client
    case_id, body, capture_id = ready(client, mode)
    if mode == "TIMEOUT":
        client.app.state.paypal_client.http.timeout = httpx.Timeout(0.3, connect=2.0)
    response = client.post(f"/cases/{case_id}/refund-executions", json=body)
    assert response.status_code == 201, response.text
    execution = response.json()
    assert execution["status"] == "unknown"
    assert "DO-NOT-LEAK" not in response.text
    assert client.get(f"/cases/{case_id}/refunds").json() == []
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["status"]
        == "execution_pending"
    )
    assert statistics(client, capture_id)["refund_creations"] == 1
    assert (
        client.post(f"/cases/{case_id}/refund-executions", json=body).json()["status"]
        == "unknown"
    )
    assert statistics(client, capture_id)["refund_posts"] == 1
    key = client.headers["Authorization"].split(" ", 1)[1]
    with merchant_client(create_app(client.app.state.store.path), key) as restarted:
        sandbox_client_factory(restarted)
        result = restarted.post(
            f"/cases/{case_id}/refund-executions/{execution['id']}/retry"
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "completed"
        assert result.json()["provider_request_id"] == execution["provider_request_id"]
        assert result.json()["attempt_count"] == 2
        counters = statistics(restarted, capture_id)
        assert counters["refund_creations"] == 1 and counters["refund_posts"] == 2
        assert set(counters["request_ids"]) == {execution["provider_request_id"]}
        assert len(restarted.get(f"/cases/{case_id}/refunds").json()) == 1


def test_real_http_pending_refund_refreshes_from_provider_without_new_post(
    sandbox_client,
):
    client = sandbox_client
    case_id, body, capture_id = ready(client, "PENDING")
    result = client.post(f"/cases/{case_id}/refund-executions", json=body)
    assert result.status_code == 201, result.text
    execution = result.json()
    assert execution["status"] == "pending"
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["pending_refund_amount"]
        == "100.00"
    )
    refreshed = client.post(
        f"/cases/{case_id}/refund-executions/{execution['id']}/refresh"
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "completed"
    assert statistics(client, capture_id)["refund_posts"] == 1
    assert len(client.get(f"/cases/{case_id}/paypal-refund-verifications").json()) == 2


@pytest.mark.parametrize("mode", ["REJECT", "FAILREFUND"])
def test_provider_rejection_or_failed_refund_does_not_fulfill_commitment(
    sandbox_client, mode
):
    client = sandbox_client
    case_id, body, capture_id = ready(client, mode)
    result = client.post(f"/cases/{case_id}/refund-executions", json=body)
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "failed"
    assert "DO-NOT-LEAK" not in result.text
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["completed_refund_amount"]
        == "0.00"
    )
    assert statistics(client, capture_id)["refund_posts"] == 1


@pytest.mark.parametrize("mode", ["READBADPARENT", "READNOUP", "READBADURL"])
def test_refund_read_refuses_missing_wrong_or_malformed_parent_without_mutation(
    sandbox_client, mode
):
    client = sandbox_client
    case_id, body, capture_id = ready(client, "PENDING" + mode)
    execution = client.post(f"/cases/{case_id}/refund-executions", json=body).json()
    assert execution["status"] == "pending"
    before = client.get(f"/cases/{case_id}/paypal-refund-verifications").json()
    result = client.post(
        f"/cases/{case_id}/refund-executions/{execution['id']}/refresh"
    )
    assert result.status_code == 502, result.text
    assert client.get(f"/cases/{case_id}/paypal-refund-verifications").json() == before
    assert (
        client.get(f"/cases/{case_id}/refund-executions/{execution['id']}").json()[
            "status"
        ]
        == "pending"
    )
    assert statistics(client, capture_id)["refund_posts"] == 1


def test_known_refund_verification_is_provider_backed_and_shared_between_owner_cases(
    sandbox_client,
):
    client = sandbox_client
    case_id, body, capture_id = ready(client)
    execution = client.post(f"/cases/{case_id}/refund-executions", json=body).json()
    refund_id = execution["provider_refund"]["refund_id"]
    other_case = client.post(
        "/cases",
        json={
            "order_id": "RELATED",
            "complaint": "Same capture",
            "payment": {"capture_id": capture_id, "captured_amount": "100.00"},
        },
    ).json()["id"]
    result = client.post(
        f"/cases/{other_case}/paypal-refund-verifications",
        json={"refund_id": refund_id},
    )
    assert result.status_code == 201, result.text
    assert result.json()["refund_details_verified"] is True
    assert len(client.get(f"/cases/{case_id}/paypal-refund-verifications").json()) == 2
    assert statistics(client, capture_id)["refund_posts"] == 1


def test_recovery_worker_refreshes_actual_http_pending_refund_with_writes_disabled(
    sandbox_client,
):
    client = sandbox_client
    case_id, body, capture_id = ready(client, "PENDING")
    result = client.post(f"/cases/{case_id}/refund-executions", json=body)
    assert result.json()["status"] == "pending"
    paypal = client.app.state.paypal_client
    paypal.settings.paypal_sandbox_refunds_enabled = False
    report = run_once(
        client.app.state.store,
        paypal,
        now=datetime.now(timezone.utc) + timedelta(seconds=31),
    )
    assert report["completed"] == 1
    assert statistics(client, capture_id)["refund_posts"] == 1
