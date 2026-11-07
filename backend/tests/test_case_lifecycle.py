from hashlib import sha256
from uuid import uuid4

import httpx
from starlette.datastructures import Headers

from app.paypal import PayPalSandboxClient, SANDBOX_BASE_URL
from app.settings import Settings
from app.case_workspace import add_exception


def create_case(client):
    response = client.post(
        "/cases",
        json={
            "order_id": "TESTORDER",
            "complaint": "Evidence test",
            "payment": {"capture_id": "TESTCAPTURE", "captured_amount": "20.00"},
            "commitment": {
                "amount": "10.00",
                "status": "accepted",
                "source_message": "Test",
            },
        },
    )
    assert response.status_code == 201
    return "/cases/" + response.json()["id"]


def test_attachments_lifecycle_and_tenant_boundaries(client):
    url = create_case(client)
    sibling = create_case(client)
    data = b"%PDF-1.7\nTest evidence"
    headers = {"Content-Type": "application/pdf"}
    files = url + "/attachments"
    assert (
        client.post(
            files, params={"filename": "../case.pdf"}, headers=headers, content=data
        ).status_code
        == 422
    )
    assert (
        client.post(
            files, params={"filename": "case.pdf"}, headers=headers, content=b"<script>"
        ).status_code
        == 422
    )
    assert (
        client.post(
            files,
            params={"filename": "case.pdf"},
            headers=headers,
            content=data * 120000,
        ).status_code
        == 413
    )
    result = client.post(
        files, params={"filename": "case.pdf"}, headers=headers, content=data
    )
    assert result.status_code == 201, result.text
    attachment = result.json()
    assert attachment["sha256"] == sha256(data).hexdigest()
    downloaded = client.get(files + "/" + attachment["id"])
    assert downloaded.content == data
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert (
        downloaded.headers["content-disposition"] == 'attachment; filename="case.pdf"'
    )
    assert client.get(sibling + "/attachments/" + attachment["id"]).status_code == 404
    assert not any(
        e["event_type"] == "evidence_attached"
        for e in client.get(sibling + "/timeline").json()["items"]
    )

    basis = client.get(url + "/reconciliation").json()
    approval = client.post(
        url + "/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": "TESTCAPTURE",
            "amount": "10.00",
            "state_fingerprint": basis["state_fingerprint"],
            "decision_note": "Test approval",
        },
    ).json()
    assert (
        client.post(url + "/close", json={"reason": "Close after review"}).json()[
            "status"
        ]
        == "closed"
    )
    assert (
        client.get(url + "/reconciliation").json()["recommended_refund_amount"]
        == "0.00"
    )
    assert (
        client.post(
            files, params={"filename": "case.pdf"}, headers=headers, content=data
        ).status_code
        == 409
    )
    assert client.get(files).json() == [attachment]
    assert (
        client.get(url + "/refund-approvals/" + approval["id"]).json()["status"]
        == "invalidated"
    )
    assert (
        client.post(url + "/reopen", json={"reason": "New evidence"}).json()["status"]
        == "open"
    )
    assert (
        client.get(url + "/reconciliation").json()["state_fingerprint"]
        != basis["state_fingerprint"]
    )

    store = client.app.state.store
    second = store.create_merchant("Other")
    other = {"Authorization": "Bearer " + second.api_key}
    assert client.get(files + "/" + attachment["id"], headers=other).status_code == 404
    assert (
        client.post(url + "/close", headers=other, json={"reason": "Other"}).status_code
        == 404
    )


def test_review_queue_deduplicates_and_retains_resolution(client):
    url = create_case(client)
    store = client.app.state.store
    owner = client.get("/auth/me").json()["id"]
    case = store.get_case(url.split("/")[-1], owner)
    with store.transaction(write=True) as db:
        for _ in range(2):
            add_exception(db, owner, "test:exception", "test_issue", case=case)
    queue = client.get("/review-queue").json()
    assert queue["total"] == 1
    identifier = queue["items"][0]["id"]
    other = {"Authorization": "Bearer " + store.create_merchant("Another").api_key}
    assert client.get("/review-queue", headers=other).json()["total"] == 0
    action = f"/review-queue/{identifier}/resolve"
    assert (
        client.post(action, headers=other, json={"reason": "Test"}).status_code == 404
    )
    assert (
        client.post(action, json={"reason": "Reviewed ledger"}).json()["status"]
        == "resolved"
    )
    assert client.get("/review-queue").json()["total"] == 0
    assert (
        client.get("/review-queue?status=resolved").json()["items"][0][
            "resolution_note"
        ]
        == "Reviewed ledger"
    )


def test_paypal_postback_preserves_original_event_bytes():
    raw = b'{\n "id": "WH-TEST",  "event_type" : "PAYMENT.CAPTURE.REFUNDED" \n}'
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "fake",
                    "token_type": "Bearer",
                    "expires_in": 300,
                },
            )
        assert request.url.path == "/v1/notifications/verify-webhook-signature"
        assert request.content.endswith(b'"webhook_event":' + raw + b"}")
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    settings = Settings(
        _env_file=None,
        paypal_sandbox_enabled=True,
        paypal_resolve_merchant_id=uuid4(),
        paypal_sandbox_client_id="client",
        paypal_sandbox_client_secret="secret",
        paypal_sandbox_merchant_id="seller",
        paypal_sandbox_webhook_id="SIMHOOK",
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        provider = PayPalSandboxClient(settings, http)
        provider.verify_webhook(
            Headers(
                {
                    "paypal-auth-algo": "SHA256withRSA",
                    "paypal-transmission-id": "txn",
                    "paypal-transmission-time": "2026-11-07T00:00:00Z",
                    "paypal-transmission-sig": "c2ln",
                    "paypal-cert-url": SANDBOX_BASE_URL
                    + "/v1/notifications/certs/CERT-123",
                }
            ),
            raw,
        )
    assert len(requests) == 2
