from hashlib import sha256
from uuid import uuid4

from test_resolution_workspace import record, refund_case, workspace


def issue(client, url, **settings):
    response = client.post(url + "/customer-link", json=settings)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()["token"]


def buyer_view(client, token):
    return client.post(
        "/customer-portal/view", headers={"Authorization": ""}, json={"token": token}
    )


def test_customer_sees_limited_case_without_merchant_auth(client):
    payment = refund_case(client)
    url = workspace(client, linked=payment, order="PRIVATE-ORDER-REF")
    record(
        client,
        url,
        {"kind": "refund", "amount": "30.00"},
        promise="We agreed to refund $30.00.",
        source_note="PRIVATE SUPPORT NOTE",
    )
    token = issue(client, url, title="Return update")
    response = buyer_view(client, token)
    assert response.status_code == 200, response.text
    assert response.headers["referrer-policy"] == "no-referrer"
    data = response.json()
    assert data["title"] == "Return update" and data["order_reference"] is None
    assert data["promises"][0]["promise"] == "We agreed to refund $30.00."
    assert data["refund"]["confirmed_amount"] is None
    assert data["refund"]["outstanding_amount"] is None
    assert data["refund"]["verification"] == "unverified"
    for value in (
        "PRIVATE SUPPORT NOTE",
        "PRIVATE-ORDER-REF",
        "TESTRESOLUTION",
        payment,
        token,
    ):
        assert value not in response.text
    assert set(data) == {
        "title",
        "order_reference",
        "outcome",
        "expires_at",
        "promises",
        "refund",
        "messages",
        "evidence",
        "timeline",
        "next_step",
    }
    assert set(data["promises"][0]) == {
        "kind",
        "promise",
        "outcome",
        "due_at",
        "provider_confirmed",
    }
    assert "token" not in client.get(url + "/customer-link").json()
    with client.app.state.store.transaction() as connection:
        stored = connection.execute(
            "SELECT token_hash FROM customer_portal_links"
        ).fetchone()[0]
    assert stored == sha256(token.encode()).hexdigest() and stored != token


def test_rotation_revocation_expiration_and_ownership(client):
    url = workspace(client, order="VISIBLE-ORDER")
    token = issue(client, url)
    other = client.app.state.store.create_merchant("Other merchant")
    foreign = {"Authorization": "Bearer " + other.api_key}
    for action in ("get", "post", "delete"):
        kwargs = {"json": {}} if action == "post" else {}
        response = getattr(client, action)(
            url + "/customer-link", headers=foreign, **kwargs
        )
        assert response.status_code == 404
    assert client.get(url + "/customer-messages", headers=foreign).status_code == 404
    assert (
        client.post(
            url + "/customer-messages",
            headers=foreign,
            json={"request_id": str(uuid4()), "body": "No access"},
        ).status_code
        == 404
    )
    new_token = issue(client, url, show_order_reference=True)
    assert new_token != token and buyer_view(client, token).status_code == 404
    assert buyer_view(client, new_token).json()["order_reference"] == "VISIBLE-ORDER"
    assert client.delete(url + "/customer-link").json()["active"] is False
    assert buyer_view(client, new_token).status_code == 404
    expired = issue(client, url)
    with client.app.state.store.transaction(write=True) as connection:
        connection.execute(
            "UPDATE customer_portal_links SET expires_at=?",
            ("2020-01-01T00:00:00.000000+00:00",),
        )
    assert client.get(url + "/customer-link").json()["active"] is False
    assert buyer_view(client, expired).status_code == 404


def test_conversation_is_scoped_idempotent_and_separate_from_refund_state(client):
    payment = refund_case(client)
    url = workspace(client, linked=payment)
    token = issue(client, url)
    before = client.get(f"/cases/{payment}/reconciliation").json()["state_fingerprint"]
    body = {"request_id": str(uuid4()), "body": "Please send a status update."}
    missing = client.post("/customer-portal/messages", json={"token": token})
    assert missing.status_code == 422 and token not in missing.text
    first = client.post("/customer-portal/messages", json={**body, "token": token})
    assert first.status_code == 201 and first.json()["sender"] == "customer"
    assert (
        client.post("/customer-portal/messages", json={**body, "token": token}).json()
        == first.json()
    )
    assert (
        client.post(
            "/customer-portal/messages",
            json={**body, "token": token, "body": "Different"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            url + "/customer-messages",
            json={"request_id": str(uuid4()), "body": "We received your return."},
        ).status_code
        == 201
    )
    assert [
        entry["sender"] for entry in buyer_view(client, token).json()["messages"]
    ] == ["customer", "merchant"]
    assert len(client.get(url + "/customer-messages").json()) == 2
    other = issue(client, workspace(client))
    assert buyer_view(client, other).json()["messages"] == []
    assert (
        client.get(f"/cases/{payment}/reconciliation").json()["state_fingerprint"]
        == before
    )
    for _ in range(5):
        assert (
            client.post(
                "/customer-portal/messages",
                json={
                    "token": token,
                    "request_id": str(uuid4()),
                    "body": "Test follow-up",
                },
            ).status_code
            == 201
        )
    assert (
        client.post(
            "/customer-portal/messages",
            json={
                "token": token,
                "request_id": str(uuid4()),
                "body": "Rate limit",
            },
        ).status_code
        == 429
    )
    client.delete(url + "/customer-link")
    assert (
        client.post(
            "/customer-portal/messages", json={**body, "token": token}
        ).status_code
        == 404
    )
