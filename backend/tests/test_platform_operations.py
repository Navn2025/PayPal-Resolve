"""Disposable end-to-end merchant/buyer operations; no configured accounts are used."""

import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from threading import Thread
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from app.main import create_app
from app.platform_connections import Connections
from app.platform_imports import process_jobs
from app.settings import Settings


@pytest.fixture
def api(tmp_path, request):
    cfg = Settings(
        _env_file=None, platform_encryption_key=Fernet.generate_key().decode()
    )
    store = (
        request.getfixturevalue("postgres_store")
        if os.environ.get("RESOLVE_TEST_STORAGE") == "postgres"
        else None
    )
    with TestClient(
        create_app(tmp_path / "operations.sqlite3", settings=cfg, store=store)
    ) as client:
        result = client.post(
            "/platform/account/signup",
            json={
                "workspace": "Synthetic store",
                "name": "Owner",
                "email": "owner@example.test",
                "password": "synthetic-password-123",
            },
        )
        assert result.status_code == 201, result.text
        account = result.json()
        client.headers["Authorization"] = "Bearer " + account["token"]
        client.owner = account
        yield client


def case(api, reference="ORDER-TEST"):
    result = api.post(
        "/resolution-cases",
        json={"title": "Synthetic return", "order_reference": reference},
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def promise(api, case_id, *, kind="return", due=True):
    target = {
        "kind": "return",
        "milestone": "warehouse_received",
        "return_reference": "RMA-TEST",
    }
    if kind == "refund":
        target = {"kind": "refund", "amount": "25.00", "currency": "USD"}
    result = api.post(
        f"/resolution-cases/{case_id}/promises",
        json={
            "promise": "We will complete the agreed remedy",
            "source_note": "PRIVATE SYNTHETIC SOURCE",
            "due_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            if due
            else None,
            "requires": [],
            "target": target,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def buyer_link(api, case_id):
    result = api.post(
        f"/resolution-cases/{case_id}/customer-link",
        json={"title": "Your case", "show_order_reference": True},
    )
    assert result.status_code == 201, result.text
    return result.json()["token"]


def invite(api, role, email=None):
    email = email or role + "@example.test"
    result = api.post("/platform/team/invites", json={"email": email, "role": role})
    assert result.status_code == 201, result.text
    result = api.post(
        "/platform/account/accept-invite",
        json={
            "token": result.json()["token"],
            "email": email,
            "name": role,
            "password": "synthetic-password-123",
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_session_revoked_during_authorization_never_gains_owner_role(api, monkeypatch):
    from app.merchant_auth import MerchantAuth

    original = MerchantAuth.session
    calls = 0

    def revoked(self, token):
        nonlocal calls
        calls += 1
        return original(self, token) if calls == 1 else None

    monkeypatch.setattr(MerchantAuth, "session", revoked)
    assert api.post("/platform/sdk-keys").status_code == 401
    with api.app.state.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM merchant_api_keys").fetchone()[0] == 0


def test_signup_sessions_team_and_revocation(api):
    assert api.get("/merchant-auth/session").json()["method"] == "password"
    assert api.get("/platform/me").json()["role"] == "owner"
    agent = invite(api, "agent")
    header = {"Authorization": "Bearer " + agent["token"]}
    assert api.get("/platform/dashboard", headers=header).status_code == 200
    assert api.post(
        "/platform/team/invites",
        json={"email": "deny@example.test", "role": "owner"},
        headers=header,
    ).status_code in (403, 422)
    staff_id = agent["staff"]["id"]
    response = api.put(
        "/platform/team/" + staff_id, json={"role": "agent", "active": False}
    )
    assert response.status_code == 200, response.text
    assert api.get("/platform/me", headers=header).status_code == 401
    owner_id = api.owner["staff"]["id"]
    assert (
        api.put(
            "/platform/team/" + owner_id, json={"role": "viewer", "active": True}
        ).status_code
        == 409
    )
    issued = api.post("/platform/sdk-keys")
    assert issued.status_code == 201
    assert (
        api.get(
            "/platform/dashboard",
            headers={"Authorization": "Bearer " + issued.json()["api_key"]},
        ).status_code
        == 401
    )
    assert (
        api.post(
            "/platform/account/login",
            json={"email": "owner@example.test", "password": "synthetic-password-123"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "role,approval,execution",
    [
        ("viewer", 403, 403),
        ("agent", 403, 403),
        ("manager", 404, 403),
        ("finance", 404, 404),
    ],
)
def test_financial_role_boundaries(api, role, approval, execution):
    member = invite(api, role)
    headers = {"Authorization": "Bearer " + member["token"]}
    identifier = str(uuid4())
    payload = {
        "request_id": str(uuid4()),
        "capture_id": "SYNTHETIC",
        "amount": "1.00",
        "currency": "USD",
        "state_fingerprint": "0" * 64,
        "decision_note": "Synthetic reviewed action",
    }
    assert (
        api.post(
            f"/cases/{identifier}/refund-approvals", json=payload, headers=headers
        ).status_code
        == approval
    )
    assert (
        api.post(
            f"/cases/{identifier}/refund-executions",
            json={"request_id": str(uuid4()), "approval_id": str(uuid4())},
            headers=headers,
        ).status_code
        == execution
    )
    if role == "viewer":
        assert (
            api.post(
                "/resolution-cases", json={"title": "Denied"}, headers=headers
            ).status_code
            == 403
        )


def test_offers_are_private_version_bound_and_idempotent(api):
    identifier = case(api)
    p = promise(api, identifier)
    token = buyer_link(api, identifier)
    created = api.post(
        f"/platform/cases/{identifier}/offers",
        json={
            "choices": [{"promise_id": p["id"], "expected_revision": 1}],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    offer = api.post("/platform/buyer/offers", json={"token": token}).json()["items"][0]
    assert "PRIVATE SYNTHETIC SOURCE" not in json.dumps(offer)
    assert "return_reference" not in json.dumps(offer)
    decision = {
        "token": token,
        "offer_id": offer["id"],
        "expected_revision": offer["revision"],
        "choice_id": offer["choices"][0]["id"],
        "decision": "accept",
    }
    first = api.post("/platform/buyer/decision", json=decision)
    assert first.status_code == 200, first.text
    assert first.json()["authorizes_payment"] is False
    assert api.post("/platform/buyer/decision", json=decision).json() == first.json()
    assert (
        api.post(
            "/platform/buyer/decision",
            json={**decision, "decision": "decline", "choice_id": None},
        ).status_code
        == 409
    )
    api.delete(f"/resolution-cases/{identifier}/customer-link")
    assert api.post("/platform/buyer/decision", json=decision).status_code == 404


def test_revised_promises_reject_old_buyer_acceptance(api):
    identifier = case(api)
    p = promise(api, identifier)
    token = buyer_link(api, identifier)
    response = api.post(
        f"/platform/cases/{identifier}/offers",
        json={
            "choices": [{"promise_id": p["id"], "expected_revision": 1}],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 201
    offer = response.json()
    revised = api.put(
        f"/resolution-cases/{identifier}/promises/{p['id']}",
        json={**p["terms"], "promise": "Changed terms", "expected_revision": 1},
    )
    assert revised.status_code == 200, revised.text
    assert (
        api.post(
            "/platform/buyer/decision",
            json={
                "token": token,
                "offer_id": offer["id"],
                "expected_revision": 1,
                "choice_id": offer["choices"][0]["id"],
                "decision": "accept",
            },
        ).status_code
        == 409
    )


def test_watchdog_deduplicates_and_resolves_current_revision(api):
    identifier = case(api)
    p = promise(api, identifier)
    a = api.post("/platform/watchdog/scan")
    assert a.status_code == 200, a.text
    b = api.post("/platform/watchdog/scan")
    assert len(a.json()["items"]) == len(b.json()["items"]) == 1
    assert b.json()["items"][0]["assignee"] == "Owner"
    with api.app.state.store.transaction() as db:
        assert (
            db.execute(
                "SELECT assignee FROM resolution_operations WHERE resolution_id=?",
                (identifier,),
            ).fetchone()[0]
            == "Owner"
        )
    metrics = api.get("/platform/dashboard")
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["overdue_promises"] == 1
    result = api.post(
        f"/resolution-cases/{identifier}/promises/{p['id']}/evidence",
        json={
            "expected_revision": 1,
            "note": "Warehouse inspection recorded",
            "finding": "confirmed",
        },
    )
    assert result.status_code == 201, result.text
    assert not api.post("/platform/watchdog/scan").json()["items"]


def test_returns_quantities_retries_and_state_transitions(api):
    from app.commerce_models import CommerceSyncInput
    from app.commerce_workspace import CommerceWorkspace

    identifier = case(api)
    milestone = promise(api, identifier)
    store = api.app.state.store
    merchant = api.owner["merchant"]["id"]
    CommerceWorkspace(store).sync(
        merchant,
        CommerceSyncInput(
            source="synthetic",
            order_reference="ORDER-TEST",
            revision=1,
            case_id=identifier,
            items=[{"product_id": "P1", "name": "Synthetic item", "quantity": 2}],
        ),
    )
    catalog = api.get(f"/platform/cases/{identifier}/returns").json()
    order = catalog["orders"][0]
    payload = {
        "request_id": str(uuid4()),
        "order_id": order["id"],
        "items": [{"product_id": "P1", "quantity": 1}],
        "reason": "Damaged item",
    }
    first = api.post(f"/platform/cases/{identifier}/returns", json=payload)
    assert first.status_code == 201, first.text
    assert (
        api.post(f"/platform/cases/{identifier}/returns", json=payload).json()["id"]
        == first.json()["id"]
    )
    assert (
        api.post(
            f"/platform/cases/{identifier}/returns",
            json={
                **payload,
                "request_id": str(uuid4()),
                "items": [{"product_id": "P1", "quantity": 2}],
            },
        ).status_code
        == 409
    )
    path = f"/platform/cases/{identifier}/returns/{first.json()['id']}"
    assert (
        api.put(
            path,
            json={
                "expected_revision": 1,
                "action": "ship_replacement",
                "note": "Too early",
            },
        ).status_code
        == 409
    )
    for version, action in enumerate(
        [
            "approve",
            "ship_return",
            "receive",
            "pass_inspection",
            "ship_replacement",
            "complete",
        ],
        1,
    ):
        body = {
            "expected_revision": version,
            "action": action,
            "note": "Synthetic merchant reviewed step",
        }
        if action in ("ship_return", "ship_replacement"):
            body["shipment"] = {
                "carrier": "Synthetic",
                "tracking_code": "TRACKTEST",
                "reference": "SHIPTEST",
            }
        if action == "receive":
            body.update(promise_id=milestone["id"], promise_revision=1)
        response = api.put(path, json=body)
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    fulfilled = api.get(f"/resolution-cases/{identifier}").json()["promises"][0]
    assert fulfilled["outcome"] == "fulfilled"
    assert fulfilled["evidence_source"] == "merchant_recorded"


def test_shared_capture_dashboard_precision_and_pending_failed_refunds(api):
    payload = {
        "order_id": "SHARED-ORDER",
        "complaint": "Synthetic refund issue",
        "payment": {"capture_id": "SHAREDCAPTURE", "captured_amount": "100.00"},
        "commitment": {
            "amount": "25.00",
            "status": "accepted",
            "source_message": "Synthetic accepted cumulative refund",
        },
    }
    first = api.post("/cases", json=payload).json()["id"]
    second = api.post("/cases", json={**payload, "order_id": "SHARED-ORDER-2"}).json()[
        "id"
    ]
    for refund_id, amount, status in [
        ("CENTREFUND", "0.10", "completed"),
        ("PENDINGREFUND", "0.20", "pending"),
        ("FAILEDREFUND", "0.30", "failed"),
    ]:
        body = {
            "refund_id": refund_id,
            "capture_id": "SHAREDCAPTURE",
            "amount": amount,
            "status": status,
        }
        assert api.post(f"/cases/{first}/refunds", json=body).status_code == 201
        assert api.post(f"/cases/{second}/refunds", json=body).status_code == 200
    result = api.get("/platform/dashboard")
    assert result.status_code == 200, result.text
    totals = result.json()["financial"]
    assert totals["shared_capture_count"] == 1
    assert (
        totals["promised"],
        totals["completed"],
        totals["pending"],
        totals["outstanding_excluding_pending"],
    ) == ("25.00", "0.10", "0.20", "24.70")
    assert totals["source"] == "recorded_ledger_not_independent_provider_verification"


def test_buyer_offer_gate_invalidates_approvals_and_cannot_be_removed_by_other_offer(
    api,
):
    legacy = api.post(
        "/cases",
        json={
            "order_id": "OFFER-ORDER",
            "complaint": "Synthetic refund",
            "payment": {"capture_id": "OFFERCAPTURE", "captured_amount": "25.00"},
            "commitment": {
                "amount": "25.00",
                "status": "accepted",
                "source_message": "Synthetic promise",
            },
        },
    ).json()["id"]
    identifier = api.post(
        "/resolution-cases",
        json={
            "title": "Offer gate",
            "order_reference": "OFFER-ORDER",
            "refund_case_id": legacy,
        },
    ).json()["id"]
    p = promise(api, identifier, kind="refund")
    basis = api.get(f"/cases/{legacy}/reconciliation").json()
    approval = {
        "request_id": str(uuid4()),
        "capture_id": "OFFERCAPTURE",
        "amount": "25.00",
        "currency": "USD",
        "state_fingerprint": basis["state_fingerprint"],
        "decision_note": "Synthetic explicit approval",
    }
    result = api.post(f"/cases/{legacy}/refund-approvals", json=approval)
    assert result.status_code == 201, result.text
    published = api.post(
        f"/platform/cases/{identifier}/offers",
        json={
            "choices": [{"promise_id": p["id"], "expected_revision": 1}],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert published.status_code == 201, published.text
    assert (
        api.get(f"/cases/{legacy}/refund-approvals").json()[0]["status"]
        == "invalidated"
    )
    assert (
        api.get(f"/cases/{legacy}/reconciliation").json()["status"]
        == "awaiting_prerequisite"
    )
    token = buyer_link(api, identifier)
    offer = published.json()
    decision = api.post(
        "/platform/buyer/decision",
        json={
            "token": token,
            "offer_id": offer["id"],
            "expected_revision": offer["revision"],
            "choice_id": offer["choices"][0]["id"],
            "decision": "accept",
        },
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["authorizes_payment"] is False
    assert (
        api.get(f"/cases/{legacy}/reconciliation").json()["status"] == "refund_required"
    )
    other = promise(api, identifier)
    assert (
        api.post(
            f"/platform/cases/{identifier}/offers",
            json={
                "choices": [{"promise_id": other["id"], "expected_revision": 1}],
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
            },
        ).status_code
        == 201
    )
    assert (
        api.get(f"/cases/{legacy}/reconciliation").json()["status"]
        == "awaiting_prerequisite"
    )
    with api.app.state.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0


def test_workspace_connection_does_not_inherit_another_owners_provider_key(api):
    from uuid import UUID

    settings = api.app.state.settings
    settings.resolution_connector_merchant_id = uuid4()
    settings.easypost_api_key = __import__("pydantic").SecretStr(
        "another-workspaces-key"
    )
    saved = api.put(
        "/platform/connections/shopify",
        json={
            "expected_revision": 0,
            "enabled": True,
            "config": {"shop_domain": "synthetic.myshopify.com"},
            "credentials": {"admin_token": "own-synthetic-token"},
        },
    )
    assert saved.status_code == 200, saved.text
    scoped = Connections(api.app.state.store, settings).settings_for(
        api.owner["merchant"]["id"]
    )
    assert scoped.easypost_api_key is None
    assert scoped.resolution_connector_merchant_id == UUID(api.owner["merchant"]["id"])
    assert scoped.shopify_admin_token.get_secret_value() == "own-synthetic-token"


def test_dispute_package_is_reviewed_immutable_and_tenant_scoped(api):
    identifier = case(api)
    promise(api, identifier)
    response = api.post(
        f"/platform/cases/{identifier}/dispute-packages",
        json={"dispute_id": "PP-SYNTHETIC", "reason": "item_not_received"},
    )
    assert response.status_code == 201, response.text
    package = response.json()
    path = f"/platform/cases/{identifier}/dispute-packages/{package['id']}"
    assert api.get(path + "/export").status_code == 409
    assert api.post(path + "/review").status_code == 200
    exported = api.get(path + "/export")
    assert exported.status_code == 200
    assert exported.json()["reviewed"] is True
    original = api.get(path).json()
    promise(api, identifier)
    assert api.get(path).json()["snapshot"] == original["snapshot"]
    assert api.get(path + "/export").status_code == 409
    assert api.get(path).json()["stale"] is True
    other = api.post(
        "/platform/account/signup",
        json={
            "workspace": "Other",
            "name": "Other",
            "email": "other@example.test",
            "password": "synthetic-password-123",
        },
    ).json()
    assert (
        api.get(path, headers={"Authorization": "Bearer " + other["token"]}).status_code
        == 404
    )


class LoopbackTransport(httpx.BaseTransport):
    """Production hostnames go over a real local HTTP socket; no pass-through."""

    def __init__(self, port):
        self.port = port
        self.transport = httpx.HTTPTransport()

    def handle_request(self, request):
        assert request.url.host == "synthetic.zendesk.com"
        url = httpx.URL(f"http://127.0.0.1:{self.port}").copy_with(
            raw_path=request.url.raw_path
        )
        return self.transport.handle_request(
            httpx.Request(
                request.method, url, headers=request.headers, content=request.read()
            )
        )

    def close(self):
        self.transport.close()


@pytest.fixture
def zendesk_http():
    requests = []
    state = {"unavailable": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            assert self.headers["Authorization"] == "Bearer synthetic-token"
            if state["unavailable"]:
                self.send_response(503)
                self.end_headers()
                return
            if self.path.startswith("/api/v2/tickets/123/comments.json"):
                value = {
                    "comments": [
                        {
                            "id": 91,
                            "author_id": 7,
                            "plain_body": "We will refund $25 after the return.",
                            "public": False,
                            "created_at": "2026-11-09T10:00:00Z",
                        },
                        {
                            "id": 92,
                            "author_id": 8,
                            "plain_body": "My item is damaged.",
                            "public": True,
                            "created_at": "2026-11-09T09:00:00Z",
                        },
                    ],
                    "next_page": None,
                }
            elif self.path.startswith("/api/v2/users/show_many.json"):
                value = {
                    "users": [{"id": 7, "role": "agent"}, {"id": 8, "role": "end-user"}]
                }
            elif self.path == "/api/v2/users/me.json":
                value = {"user": {"id": 7, "role": "agent"}}
            elif self.path == "/api/v2/tickets/123.json":
                value = {
                    "ticket": {
                        "id": 123,
                        "subject": "Synthetic refund",
                        "external_id": "ORDER-TEST",
                    }
                }
            else:
                self.send_response(501)
                self.end_headers()
                return
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with httpx.Client(transport=LoopbackTransport(server.server_port)) as http:
        yield http, requests, state
    server.shutdown()
    server.server_close()
    thread.join(2)


def connect_zendesk(api):
    result = api.put(
        "/platform/connections/zendesk",
        json={
            "expected_revision": 0,
            "enabled": True,
            "config": {"subdomain": "synthetic"},
            "credentials": {
                "oauth_token": "synthetic-token",
                "webhook_secret": "synthetic-signature-key",
            },
        },
    )
    assert result.status_code == 200, result.text
    assert "synthetic-token" not in result.text
    return result.json()


def test_encrypted_ticket_import_matching_webhook_and_failure_retry(api, zendesk_http):
    http, requests, state = zendesk_http
    api.app.state.followup_http = http
    identifier = case(api)
    connect_zendesk(api)
    assert (
        api.post("/platform/connections/zendesk/check").json()["check_status"]
        == "read_verified"
    )
    response = api.post("/platform/imports/zendesk", json={"ticket_id": 123})
    assert response.status_code == 200, response.text
    imported = response.json()
    assert api.get("/platform/imports/" + imported["id"]).json()["id"] == imported["id"]
    matched = api.put("/platform/imports/" + imported["id"] + "/match", json={"case_id": identifier})
    assert matched.status_code == 200 and matched.json()["case_id"] == identifier
    assert imported["case_id"] == identifier
    assert imported["suggestions"]["skipped_reason"] == "extraction_disabled"
    assert len(imported["messages"]) == 2
    assert (
        api.post("/platform/imports/zendesk", json={"ticket_id": 123}).json()["id"]
        == imported["id"]
    )
    token = buyer_link(api, identifier)
    assert (
        "We will refund"
        not in api.post("/customer-portal/view", json={"token": token}).text
    )
    row = Connections(api.app.state.store, api.app.state.settings).get(
        api.owner["merchant"]["id"], "zendesk"
    )
    assert "synthetic-token" not in row["credentials_ciphertext"]
    body = json.dumps(
        {"ticket_id": 123, "event_id": "123:2026-11-10 12:00:00"}
    ).encode()
    timestamp = datetime.now(timezone.utc).isoformat()
    signature = base64.b64encode(
        hmac.new(b"synthetic-signature-key", timestamp.encode() + body, sha256).digest()
    ).decode()
    headers = {
        "X-Zendesk-Webhook-Signature": signature,
        "X-Zendesk-Webhook-Signature-Timestamp": timestamp,
        "Content-Type": "application/json",
    }
    path = "/webhooks/zendesk/" + api.owner["merchant"]["id"]
    assert (
        api.post(
            path,
            content=body,
            headers={**headers, "X-Zendesk-Webhook-Signature": "bad"},
        ).status_code
        == 401
    )
    assert api.post(path, content=body, headers=headers).status_code == 202
    assert api.post(path, content=body, headers=headers).json()["duplicate"] is True
    state["unavailable"] = True
    assert (
        process_jobs(api.app.state.store, api.app.state.settings, http)["processed"]
        == 1
    )
    with api.app.state.store.transaction() as db:
        assert (
            db.execute("SELECT state FROM platform_webhook_jobs").fetchone()[0]
            == "retry"
        )
        assert (
            db.execute("SELECT count(*) FROM platform_ticket_messages").fetchone()[0]
            == 2
        )
    assert len(requests) >= 8


@pytest.mark.skipif(
    os.environ.get("RESOLVE_PLATFORM_POSTMAN") != "1",
    reason="Use the merchant-operations Postman TLS simulation",
)
def test_postman_zendesk_paginated_import_preserves_private_sources(api):
    import ssl

    proxy = os.environ["HTTPS_PROXY"]
    assert proxy.startswith("http://127.0.0.1:")
    certificate = os.environ["NODE_EXTRA_CA_CERTS"]
    api.app.state.followup_http.close()
    with httpx.Client(
        proxy=proxy,
        verify=ssl.create_default_context(cafile=certificate),
        trust_env=False,
        timeout=15,
    ) as http:
        api.app.state.followup_http = http
        identifier = case(api)
        response = api.put(
            "/platform/connections/zendesk",
            json={
                "expected_revision": 0,
                "enabled": True,
                "config": {"subdomain": "resolve-helpdesk"},
                "credentials": {
                    "oauth_token": "simulation-zendesk-oauth",
                    "webhook_secret": "synthetic",
                },
            },
        )
        assert response.status_code == 200, response.text
        result = api.post("/platform/imports/zendesk", json={"ticket_id": 123})
        assert result.status_code == 200, result.text
        assert result.json()["case_id"] == identifier
        assert len(result.json()["messages"]) == 2
        assert {m["sender"] for m in result.json()["messages"]} == {"buyer", "merchant"}
        token = buyer_link(api, identifier)
        assert (
            "We will refund"
            not in api.post("/customer-portal/view", json={"token": token}).text
        )
        assert (
            api.post("/platform/imports/zendesk", json={"ticket_id": 123}).json()["id"]
            == result.json()["id"]
        )
        with api.app.state.store.transaction() as db:
            assert (
                db.execute("SELECT count(*) FROM platform_ticket_messages").fetchone()[
                    0
                ]
                == 2
            )
            assert (
                db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0
            )


def test_read_authorization_uses_one_session_lookup_and_rechecks_next_request(api, monkeypatch):
    from app.merchant_auth import MerchantAuth

    original = MerchantAuth.session
    calls = []

    def tracked(self, token):
        calls.append(token)
        return original(self, token)

    monkeypatch.setattr(MerchantAuth, "session", tracked)
    assert api.get("/platform/me").status_code == 200
    assert len(calls) == 1
    with api.app.state.store.transaction(write=True) as db:
        db.execute("DELETE FROM platform_sessions")
    assert api.get("/platform/me").status_code == 401
    assert len(calls) == 2
