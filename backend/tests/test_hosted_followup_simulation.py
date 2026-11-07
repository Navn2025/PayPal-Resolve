from datetime import datetime, timedelta, timezone
import os
from uuid import UUID, uuid4

import pytest
import test_resolution_simulation as proof_fixtures

from app.customer_email import deliver, enqueue_verified_refunds
from app.followup_worker import run_once
from app.paypal import SANDBOX_BASE_URL
from test_customer_workflow import NO_AUTH, case_for, submit
from test_hosted_followup import configured_mail, issue_email
from test_paypal_history_simulation import event, external, send_event
from test_resolution_simulation import tracker
from test_resolution_workspace import record, refund_case, workspace

pytestmark = pytest.mark.skipif(
    os.getenv("RESOLVE_RUN_FOLLOWUP_SIMULATION") != "1",
    reason="Requires the local Postman follow-up simulation",
)
resolution_client = proof_fixtures.resolution_client


def test_resend_retry_signin_replies_and_verified_refunds(resolution_client):
    client = resolution_client
    cfg = configured_mail(client)
    store = client.app.state.store
    paypal = client.app.state.paypal_client
    transport = paypal.http
    cfg.paypal_sandbox_enabled = True
    cfg.paypal_sandbox_webhook_id = paypal.settings.paypal_sandbox_webhook_id = (
        "SIMWEBHOOK001"
    )
    cfg.paypal_resolve_merchant_id = paypal.settings.paypal_resolve_merchant_id
    now = datetime.now(timezone.utc)
    token = issue_email(client, "MAIL-ORDER", "retry@example.com")
    assert deliver(store, cfg, transport)["retry"] == 1
    assert (
        deliver(store, cfg, transport, now=now + timedelta(seconds=60))["accepted"] == 1
    )
    assert submit(client, token, "refund_delay").status_code == 200
    url = case_for(client, "MAIL-ORDER")
    reply = {"request_id": str(uuid4()), "body": "PRIVATE conversation body"}
    assert client.post(url + "/customer-messages", json=reply).status_code == 201
    assert client.post(url + "/customer-messages", json=reply).status_code == 201
    assert (
        client.post(
            "/customer-account/request-sign-in",
            headers=NO_AUTH,
            json={"email": "retry@example.com"},
        ).status_code
        == 202
    )
    capture = "SIMHFOLLOWUP" + uuid4().hex[:8].upper()
    payment = refund_case(client, capture, "SIMORDER" + capture)
    assert (
        client.put(url + "/payment-link", json={"refund_case_id": payment}).status_code
        == 200
    )
    record(client, url, {"kind": "refund", "amount": "30.00"})
    assert enqueue_verified_refunds(store, datetime.now(timezone.utc), 20) == 0
    delivery = event(external(client, capture, 1000))
    assert send_event(client, delivery, "aW52YWxpZA==").status_code == 401
    assert send_event(client, delivery).status_code == 204
    assert send_event(client, delivery).status_code == 204
    tick = now + timedelta(minutes=2)
    report = run_once(store, client.app.state.paypal_client, cfg, transport, now=tick)
    assert report["paypal"]["processed"] == 1
    assert report["mail"]["new_refund_notices"] == 1 and report["mail"]["retry"] == 3
    assert (
        run_once(
            store,
            client.app.state.paypal_client,
            cfg,
            transport,
            now=tick + timedelta(minutes=1),
        )["mail"]["accepted"]
        == 3
    )
    assert (
        run_once(
            store,
            client.app.state.paypal_client,
            cfg,
            transport,
            now=tick + timedelta(minutes=2),
        )["mail"]["new_refund_notices"]
        == 0
    )
    messages = transport.get(
        "https://api.resend.com/__test/messages",
        headers={"Authorization": "Bearer simulation-resend-token"},
    ).json()
    by_subject = {
        message["body"]["subject"]: message["body"]["text"]
        for message in messages["accepted"]
    }
    assert by_subject["Your private Resolve support link"].endswith(
        "/customer#" + token
    )
    login = by_subject["Sign in to Resolve"].rsplit("#", 1)[1]
    assert (
        client.post(
            "/customer-account/redeem", headers=NO_AUTH, json={"token": login}
        ).status_code
        == 200
    )
    assert all(count == 2 for _, count in messages["attempts"])
    assert "PRIVATE conversation" not in by_subject["A merchant replied in Resolve"]
    assert "10.00" not in by_subject["PayPal confirmed a refund"]
    stats = transport.get(
        SANDBOX_BASE_URL + "/__resolve_test/state/" + capture,
        headers={"Authorization": "Bearer simulation-access-token"},
    )
    assert stats.json()["refund_posts"] == 0


def test_automatic_tracking_and_shopify_do_not_confirm_warehouse(resolution_client):
    client = resolution_client
    paypal = client.app.state.paypal_client
    cfg = paypal.settings
    cfg.auto_provider_refresh_enabled = True
    store = client.app.state.store
    url = workspace(client, order="FOLLOWUP-TRACKING")
    move = tracker("MOVE" + uuid4().hex[:8].upper())
    record(
        client,
        url,
        {
            "kind": "replacement",
            "replacement_reference": "REPL",
            "milestone": "delivered",
            "tracking": move,
        },
    )
    record(
        client,
        url,
        {
            "kind": "return",
            "return_reference": "RMA-1",
            "milestone": "warehouse_received",
            "tracking": tracker("RETURNED"),
        },
    )
    record(
        client,
        url,
        {
            "kind": "return",
            "return_reference": "RMA-1",
            "milestone": "carrier_delivered",
            "tracking": tracker("RETURNED"),
        },
    )
    record(
        client,
        url,
        {"kind": "order_cancellation", "shopify_order_id": "gid://shopify/Order/101"},
    )
    now = datetime.now(timezone.utc)
    first = run_once(store, paypal, cfg, paypal.http, now=now)
    assert first["provider_checks"] == {"checked": 3, "failed": 0}
    assert (
        run_once(store, paypal, cfg, paypal.http, now=now)["provider_checks"]["checked"]
        == 0
    )
    assert (
        run_once(store, paypal, cfg, paypal.http, now=now + timedelta(minutes=5))[
            "provider_checks"
        ]["checked"]
        == 1
    )
    assert (
        run_once(store, paypal, cfg, paypal.http, now=now + timedelta(minutes=10))[
            "provider_checks"
        ]["checked"]
        == 1
    )
    updated = client.get(url).json()["promises"]
    assert [item["outcome"] for item in updated] == [
        "fulfilled",
        "waiting",
        "fulfilled",
        "fulfilled",
    ]
    count = client.get(url + "/timeline").json()["total"]
    assert (
        run_once(store, paypal, cfg, paypal.http, now=now + timedelta(minutes=71))[
            "provider_checks"
        ]["checked"]
        == 3
    )
    assert client.get(url + "/timeline").json()["total"] == count


def test_zendesk_links_and_refreshes_only_ticket_status(resolution_client):
    client = resolution_client
    cfg = client.app.state.paypal_client.settings
    cfg.helpdesk_merchant_id = UUID(client.get("/auth/me").json()["id"])
    from pydantic import SecretStr

    cfg.zendesk_subdomain = "resolve-helpdesk"
    cfg.zendesk_oauth_token = SecretStr("simulation-zendesk-oauth")
    client.app.state.settings = cfg
    client.app.state.followup_http = client.app.state.paypal_client.http
    url = workspace(client, order="ZENDESK-ORDER") + "/helpdesk"
    assert client.get(url).json() == {"configured": True, "ticket": None}
    first = client.put(url, json={"ticket_id": 123})
    assert first.status_code == 200, first.text
    assert (
        first.json()["ticket"]["status"] == "open"
        and "PRIVATE ZENDESK BODY" not in first.text
    )
    assert (
        client.put(url, json={"ticket_id": 123}).json()["ticket"]["status"] == "pending"
    )
    assert client.put(url, json={"ticket_id": 404}).status_code == 404
    assert client.get(url).json()["ticket"]["ticket_id"] == 123
    other = client.app.state.store.create_merchant("Another store")
    assert (
        client.put(
            url,
            headers={"Authorization": "Bearer " + other.api_key},
            json={"ticket_id": 123},
        ).status_code
        == 404
    )
