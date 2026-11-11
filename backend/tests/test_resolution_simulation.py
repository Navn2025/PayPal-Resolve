"""Evidence adapters run through actual HTTP and the local Postman TLS proxy."""

import os
from uuid import uuid4

import pytest

from app.paypal import SANDBOX_BASE_URL
from test_paypal_history_simulation import external
from test_resolution_workspace import approval, finding, record, refund_case, workspace


pytestmark = pytest.mark.skipif(
    os.environ.get("RESOLVE_RUN_PAYPAL_SIMULATION") != "1",
    reason="Requires the local Postman resolution simulation",
)


@pytest.fixture
def resolution_client(sandbox_client):
    settings = sandbox_client.app.state.paypal_client.settings
    settings.paypal_sandbox_partial_refunds_enabled = True
    settings.resolution_connector_merchant_id = settings.paypal_resolve_merchant_id
    from pydantic import SecretStr

    settings.easypost_api_key = SecretStr("simulation-easypost-key")
    settings.shopify_shop_domain = "resolve-shop.myshopify.com"
    settings.shopify_admin_token = SecretStr("simulation-shopify-token")
    return sandbox_client


def refresh(client, url, promise):
    return client.post(
        f"{url}/promises/{promise['id']}/refresh",
        json={"expected_revision": promise["revision"]},
    )


def tracker(label):
    return {
        "tracker_id": "trk_" + label,
        "tracking_code": "TEST" + label,
        "carrier": "UPS",
    }


def linked(client):
    capture = "SIMHRESOLUTION" + uuid4().hex[:10].upper()
    refund = refund_case(client, capture, "SIMORDER" + capture)
    return workspace(client, linked=refund), refund, capture


def test_public_refund_amounts_require_current_provider_history(resolution_client):
    from test_customer_portal import buyer_view, issue

    client = resolution_client
    url, refund, capture = linked(client)
    cash = record(client, url, {"kind": "refund", "amount": "30.00"})
    token = issue(client, url)
    unseen = buyer_view(client, token).json()["refund"]
    assert unseen["verification"] == "unverified"
    assert unseen["confirmed_amount"] is None
    assert unseen["pending_amount"] is None
    assert unseen["outstanding_amount"] is None
    external(client, capture, 1000)
    assert refresh(client, url, cash).status_code == 200
    current = buyer_view(client, token).json()["refund"]
    assert current["verification"] == "current"
    assert current["confirmed_amount"] == "10.00"
    assert current["pending_amount"] == "0.00"
    assert current["outstanding_amount"] == "20.00"
    # Unchanged refund details are deduplicated, but a successful fresh history
    # read must refresh the public SDK journey's verification timestamp.
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with client.app.state.store.transaction(write=True) as db:
        db.execute("UPDATE paypal_refund_verifications SET checked_at=? WHERE capture_id=?", (old, capture))
    renewed = refresh(client, url, cash)
    assert renewed.status_code == 200
    assert datetime.fromisoformat(renewed.json()["checked_at"]) > datetime.fromisoformat(old)
    synced = client.post("/commerce/orders/sync", json={"case_id": url.rsplit("/", 1)[1], "source": "fresh-history-qa", "order_reference": "STOREORDER1", "revision": 1})
    assert synced.status_code == 200, synced.text
    journey = client.post("/platform/buyer/assurance", json={"token": token})
    assert journey.status_code == 200
    assert journey.json()["journey"]["resolution"]["refund"]["verification"] == "current"


def test_conditional_refund_external_history_and_replacement_in_one_case(
    resolution_client,
):
    client = resolution_client
    url, refund, capture = linked(client)
    returned = record(
        client,
        url,
        {
            "kind": "return",
            "milestone": "warehouse_received",
            "return_reference": "RMA1",
            "tracking": tracker("RETURNED"),
        },
    )
    cash = record(
        client, url, {"kind": "refund", "amount": "30.00"}, requires=[returned["id"]]
    )
    replacement = record(
        client,
        url,
        {
            "kind": "replacement",
            "replacement_reference": "REPLACE1",
            "milestone": "delivered",
            "tracking": tracker("MOVE" + uuid4().hex[:8].upper()),
        },
    )
    received = refresh(client, url, returned)
    assert received.status_code == 200, received.text
    assert (
        received.json()["outcome"] == "waiting"
    )  # Carrier delivery is not warehouse receipt.
    assert received.json()["provider_proofs"][0]["status"] == "delivered"
    assert approval(client, refund, capture).status_code == 409
    assert finding(client, url, returned, "confirmed").status_code == 201

    external(client, capture, 1000)
    checked = refresh(client, url, cash)
    assert checked.status_code == 200, checked.text
    assert checked.json()["refund_progress"]["outstanding_amount"] == "20.00"
    assert (
        checked.json()["refund_progress"]["verified_remaining_refundable_amount"]
        == "90.00"
    )
    decision = approval(client, refund, capture, "20.00")
    assert decision.status_code == 201, decision.text
    execution = client.post(
        f"/cases/{refund}/refund-executions",
        json={
            "request_id": str(uuid4()),
            "approval_id": decision.json()["id"],
        },
    )
    assert execution.status_code == 201 and execution.json()["status"] == "completed", (
        execution.text
    )
    for status, outcome in [
        ("pre_transit", "pending"),
        ("in_transit", "pending"),
        ("delivered", "fulfilled"),
    ]:
        observed = refresh(client, url, replacement)
        assert observed.status_code == 200, observed.text
        assert observed.json()["outcome"] == outcome
        assert observed.json()["provider_proofs"][0]["status"] == status
        assert observed.json()["provider_proofs"][0]["environment"] == "test"
    case = client.get(url).json()
    assert case["outcome"] == "fulfilled"
    assert (
        case["promises"][1]["refund_progress"]["provider_completed_amount"] == "30.00"
    )
    trace = client.get(url + "/timeline").json()
    assert any(e["source"] == "approval" for e in trace["refund_items"])
    assert any(e["source"] == "provider_confirmed" for e in trace["items"])


def test_cancellation_requires_both_store_and_payment_and_subscription_is_separate(
    resolution_client,
):
    client = resolution_client
    url = workspace(client)
    for order, auth, outcome in [
        (101, "SIMAUTHVOIDED", "fulfilled"),
        (102, "SIMAUTHVOIDED", "pending"),
        (101, "SIMAUTHCAPTURED", "needs_review"),
    ]:
        promise = record(
            client,
            url,
            {
                "kind": "order_cancellation",
                "shopify_order_id": f"gid://shopify/Order/{order}",
                "paypal_authorization_id": auth,
            },
        )
        response = refresh(client, url, promise)
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == outcome
        assert {p["provider"] for p in response.json()["provider_proofs"]} == {
            "paypal",
            "shopify",
        }
    for action, identifier in [("cancel", "I-SIMCANCEL"), ("pause", "I-SIMPAUSE")]:
        item = record(
            client,
            url,
            {
                "kind": "subscription",
                "action": action,
                "paypal_subscription_id": identifier,
            },
        )
        status = refresh(client, url, item)
        assert status.status_code == 200, status.text
        assert status.json()["outcome"] == "fulfilled"
        assert status.json()["refund_progress"] is None


def test_credit_checks_exact_amount_and_account_and_exchange_matches_line_item(
    resolution_client,
):
    client = resolution_client
    url = workspace(client)
    credit = {
        "kind": "store_credit_or_exchange",
        "action": "store_credit",
        "credit_transaction_id": "gid://shopify/StoreCreditAccountCreditTransaction/301",
        "credit_account_id": "gid://shopify/StoreCreditAccount/201",
        "amount": "15.00",
        "currency": "USD",
    }
    item = record(client, url, credit)
    accepted = refresh(client, url, item)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["provider_proofs"][0]["amount"] == "15.00"
    wrong = record(
        client,
        url,
        {**credit, "credit_account_id": "gid://shopify/StoreCreditAccount/202"},
    )
    assert refresh(client, url, wrong).status_code == 409
    exchange = {
        "kind": "store_credit_or_exchange",
        "action": "exchange",
        "fulfillment_id": "gid://shopify/Fulfillment/401",
        "shopify_order_id": "gid://shopify/Order/101",
        "exchange_line_item_id": "gid://shopify/LineItem/501",
    }
    item = record(client, url, exchange)
    assert refresh(client, url, item).json()["outcome"] == "fulfilled"
    label_only = record(
        client, url, {**exchange, "fulfillment_id": "gid://shopify/Fulfillment/402"}
    )
    assert refresh(client, url, label_only).json()["outcome"] == "pending"
    wrong = record(
        client, url, {**exchange, "exchange_line_item_id": "gid://shopify/LineItem/999"}
    )
    assert refresh(client, url, wrong).status_code == 409


def test_billing_correction_requires_verified_money_and_dispute_export_is_read_only(
    resolution_client,
):
    client = resolution_client
    url, _, capture = linked(client)
    cash = record(client, url, {"kind": "refund", "amount": "30.00"})
    duplicate = record(
        client,
        url,
        {
            "kind": "billing_correction",
            "action": "duplicate_charge",
            "original_capture_id": "SIMHOTHER" + uuid4().hex[:8].upper(),
        },
        requires=[cash["id"]],
    )
    checked = refresh(client, url, duplicate)
    assert checked.status_code == 200, checked.text
    assert (
        checked.json()["outcome"] == "waiting"
    )  # Two captures alone do not prove correction.
    assert len(checked.json()["provider_proofs"]) == 2
    external(client, capture, 3000)
    assert refresh(client, url, cash).json()["outcome"] == "fulfilled"
    assert refresh(client, url, duplicate).json()["outcome"] == "fulfilled"
    for invoice, expected in [
        ("INV2-SIMCANCEL", "fulfilled"),
        ("INV2-SIMOFFLINE", "needs_review"),
    ]:
        item = record(
            client,
            url,
            {
                "kind": "billing_correction",
                "action": "cancel_invoice",
                "paypal_invoice_id": invoice,
            },
        )
        result = refresh(client, url, item)
        assert result.status_code == 200, result.text
        assert result.json()["outcome"] == expected
    dispute = record(
        client, url, {"kind": "dispute_handoff", "paypal_dispute_id": "PP-D-" + capture}
    )
    response = refresh(client, url, dispute)
    assert response.status_code == 200, response.text
    proof = response.json()["provider_proofs"][0]
    assert proof["status"] == "WAITING_FOR_SELLER_RESPONSE"
    assert proof["response_due_at"] == "2027-01-01T12:00:00Z"
    bundle = client.get(url + "/evidence-bundle")
    assert bundle.status_code == 200 and "UNNEEDED-BUYER-DATA" not in bundle.text
    wrong = record(
        client, url, {"kind": "dispute_handoff", "paypal_dispute_id": "PP-D-DIFFERENT"}
    )
    assert refresh(client, url, wrong).status_code == 409
    counters = client.app.state.paypal_client.http.get(
        SANDBOX_BASE_URL + "/__resolve_test/state/" + capture,
        headers={"Authorization": "Bearer simulation-access-token"},
    ).json()
    assert counters["refund_posts"] == 0


def test_outage_and_wrong_connector_owner_do_not_manufacture_proof(resolution_client):
    client = resolution_client
    url = workspace(client)
    item = record(
        client,
        url,
        {
            "kind": "replacement",
            "replacement_reference": "R1",
            "milestone": "shipped",
            "tracking": tracker("OUTAGE"),
        },
    )
    failure = refresh(client, url, item)
    assert failure.status_code == 503 and "PRIVATE-UPSTREAM-ERROR" not in failure.text
    assert client.get(url).json()["promises"][0]["evidence_source"] == "system"
    assert (
        client.get(url + "/timeline").json()["items"][0]["event_type"]
        == "verification_failed"
    )
    client.app.state.paypal_client.settings.resolution_connector_merchant_id = uuid4()
    assert refresh(client, url, item).status_code == 403
