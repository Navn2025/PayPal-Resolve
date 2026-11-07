"""Sandbox history and signed-inbox behavior over the local Postman TLS proxy."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.paypal import SANDBOX_BASE_URL
from app.worker import run_once
from test_refund_execution_simulation import statistics

pytestmark = pytest.mark.skipif(
    os.environ.get("RESOLVE_RUN_PAYPAL_SIMULATION") != "1",
    reason="Requires the local Postman PayPal simulation",
)


@pytest.fixture
def history_client(sandbox_client):
    settings = sandbox_client.app.state.paypal_client.settings
    settings.paypal_sandbox_partial_refunds_enabled = True
    settings.paypal_sandbox_webhook_id = "SIMWEBHOOK001"
    return sandbox_client


def make_case(client, mode="OK"):
    capture = "SIMH" + mode + uuid4().hex[:10].upper()
    case = client.post(
        "/cases",
        json={
            "order_id": "SIMORDER" + capture,
            "complaint": "Simulation",
            "payment": {"capture_id": capture, "captured_amount": "100.00"},
            "commitment": {
                "amount": "100.00",
                "status": "accepted",
                "source_message": "Simulated consent.",
            },
        },
    )
    assert case.status_code == 201, case.text
    return "/cases/" + case.json()["id"], capture


def refresh(client, url):
    return client.post(url + "/paypal-refund-history/refresh")


def approve(client, url, capture, amount):
    basis = client.get(url + "/reconciliation").json()
    return client.post(
        url + "/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": capture,
            "amount": amount,
            "state_fingerprint": basis["state_fingerprint"],
            "decision_note": "Simulated merchant consent.",
        },
    )


def execute(client, url, approval):
    return client.post(
        url + "/refund-executions",
        json={
            "request_id": str(uuid4()),
            "approval_id": approval["id"],
        },
    )


def external(client, capture, cents, status="COMPLETED"):
    provider = client.app.state.paypal_client
    result = provider.http.post(
        SANDBOX_BASE_URL + "/__resolve_test/external/" + capture,
        headers={"Authorization": "Bearer simulation-access-token"},
        json={"cents": cents, "status": status},
    )
    assert result.status_code == 201
    return result.json()


def signed_headers(sig="c2lnbmVk"):
    return {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": SANDBOX_BASE_URL + "/v1/notifications/certs/CERT-123",
        "paypal-transmission-id": "test-transmission",
        "paypal-transmission-sig": sig,
        "paypal-transmission-time": "2026-11-07T00:00:00Z",
    }


def event(refund, kind="PAYMENT.CAPTURE.REFUNDED", resource_type="refund"):
    return {
        "id": "WH-" + str(uuid4()),
        "event_type": kind,
        "resource_type": resource_type,
        "resource": {"id": refund["id"], "links": refund.get("links", [])},
    }


def send_event(client, payload, sig="c2lnbmVk"):
    return client.post(
        "/webhooks/paypal/sandbox", headers=signed_headers(sig), json=payload
    )


def worker(client, now=None):
    return run_once(client.app.state.store, client.app.state.paypal_client, now=now)


def test_external_refund_then_two_approved_partials(history_client):
    client = history_client
    url, capture = make_case(client)
    outsider = external(client, capture, 2701)
    result = refresh(client, url)
    assert result.status_code == 200, result.text
    assert result.json()["remaining_amount"] == "72.99"
    assert result.json()["refund_ids"] == [outsider["id"]]
    assert approve(client, url, capture, "73.00").status_code == 409

    for amount, remaining in [("12.34", "60.65"), ("60.65", "0.00")]:
        approval = approve(client, url, capture, amount)
        assert approval.status_code == 201, approval.text
        execution = execute(client, url, approval.json())
        assert execution.status_code == 201, execution.text
        assert execution.json()["status"] == "completed", execution.text
        assert execution.json()["provider_refund"]["amount"] == amount
        assert execution.json()["full_refund_only"] is False
        result = refresh(client, url)
        assert result.status_code == 200, result.text
        assert result.json()["remaining_amount"] == remaining

    assert statistics(client, capture)["refund_creations"] == 2
    assert client.get(url + "/reconciliation").json()["status"] == "fulfilled"


def test_external_drift_invalidates_old_approval_without_a_provider_post(
    history_client,
):
    client = history_client
    url, capture = make_case(client)
    assert refresh(client, url).status_code == 200
    approval = approve(client, url, capture, "20.00").json()
    external(client, capture, 1000)
    assert execute(client, url, approval).status_code == 409
    assert statistics(client, capture)["refund_posts"] == 0
    basis = client.get(url + "/reconciliation").json()
    assert basis["remaining_refundable_amount"] == "90.00"
    assert (
        client.get(url + "/refund-approvals/" + approval["id"]).json()["status"]
        == "invalidated"
    )


def test_pending_reserves_failed_does_not_and_hidden_history_blocks(history_client):
    client = history_client
    url, capture = make_case(client)
    external(client, capture, 700, "FAILED")
    external(client, capture, 1250, "PENDING")
    verified = refresh(client, url)
    assert verified.status_code == 200, verified.text
    assert verified.json()["remaining_amount"] == "87.50"
    assert approve(client, url, capture, "2.00").status_code == 409

    bad_url, bad_capture = make_case(client, "HIDDEN")
    external(client, bad_capture, 1000)
    external(client, bad_capture, 2000)
    rejected = refresh(client, bad_url)
    assert rejected.status_code == 409, rejected.text
    assert client.get(bad_url + "/reconciliation").json()["status"] == "provider_review"
    issue = client.get("/review-queue").json()["items"][0]
    assert issue["blocking"] and issue["reason"] == "paypal_history_conflict"
    assert (
        client.post(
            f"/review-queue/{issue['id']}/resolve", json={"reason": "Ignore it"}
        ).status_code
        == 409
    )


def test_verified_webhook_dedup_retry_and_reversal_hold(history_client):
    client = history_client
    url, capture = make_case(client)
    assert refresh(client, url).status_code == 200
    refund = external(client, capture, 1550)
    payload = event(refund)
    assert send_event(client, payload, "aW52YWxpZA==").status_code == 401
    assert send_event(client, payload, "dW5hdmFpbGFibGU=").status_code == 503
    assert worker(client)["webhooks"]["processed"] == 0
    assert send_event(client, payload).status_code == 204
    assert send_event(client, payload).status_code == 204
    changed = {**payload, "event_type": "PAYMENT.REFUND.PENDING"}
    assert send_event(client, changed).status_code == 409
    assert client.get(url + "/reconciliation").json()["status"] == "provider_review"
    assert worker(client)["webhooks"]["processed"] == 1
    assert worker(client)["webhooks"]["processed"] == 0
    assert client.get(url + "/refunds").json()[0]["refund_id"] == refund["id"]

    reversal = event({"id": capture}, "PAYMENT.CAPTURE.REVERSED", "capture")
    assert send_event(client, reversal).status_code == 204
    assert worker(client)["webhooks"]["exceptions"] == 1
    assert refresh(client, url).status_code == 200
    assert client.get(url + "/reconciliation").json()["paypal_history_current"] is False
    assert approve(client, url, capture, "1.00").status_code == 409


def test_uncertain_partial_recovered_by_correlation_without_second_post(history_client):
    client = history_client
    url, capture = make_case(client, "BADJSON")
    assert refresh(client, url).status_code == 200
    approval = approve(client, url, capture, "9.99").json()
    submitted = execute(client, url, approval)
    assert submitted.status_code == 201, submitted.text
    execution = submitted.json()
    assert execution["status"] == "unknown"
    other = external(client, capture, 999)
    action_url = url + "/refund-executions/" + execution["id"]
    assert (
        client.post(
            action_url + "/refresh", json={"refund_id": other["id"]}
        ).status_code
        == 409
    )
    result = worker(client, datetime.now(timezone.utc) + timedelta(seconds=60))
    assert result["completed"] == 1, result
    assert statistics(client, capture)["refund_posts"] == 1
    assert client.get(action_url).json()["provider_refund"]["refund_id"] != other["id"]
