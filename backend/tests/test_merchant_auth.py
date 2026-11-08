from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from app.main import create_app
from app.settings import Settings


NO_AUTH = {"Authorization": ""}
BASE = "/merchant-auth"


def session(client, key=None):
    key = key or client.headers["Authorization"].removeprefix("Bearer ")
    response = client.post(BASE + "/session/key", headers=NO_AUTH, json={"key": key})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def start(client, intent, headers=NO_AUTH):
    response = client.post(
        BASE + "/paypal/start", headers=headers, json={"intent": intent}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    url = urlsplit(data["authorize_url"])
    params = parse_qs(url.query)
    assert url.hostname == "www.sandbox.paypal.com"
    assert params["scope"] == ["openid"]
    assert params["redirect_uri"] == [
        "https://resolve.example.com/api/auth/paypal/callback"
    ]
    return {
        "state": params["state"][0],
        "browser_token": data["browser_token"],
        "code": "resolve-code-merchant",
    }


def configure(client):
    client.app.state.settings = Settings(
        _env_file=None,
        merchant_web_origin="https://resolve.example.com",
        paypal_login_enabled=True,
        paypal_login_client_id="simulation-login-client",
        paypal_login_client_secret="simulation-login-secret",
    )


def test_merchant_browser_session_is_hashed_durable_and_revoked(
    client, merchant_client
):
    store = client.app.state.store
    identity = client.get("/auth/me").json()
    key = store.issue_key(UUID(identity["id"]))
    web = session(client, key.api_key)
    token = web["Authorization"].removeprefix("Bearer ")
    with store.transaction() as db:
        row = db.execute(
            "SELECT token_hash,api_key_id FROM merchant_web_sessions"
        ).fetchone()
        assert row["token_hash"] == sha256(token.encode()).hexdigest()
        assert row["api_key_id"] == str(key.key_id)
    with merchant_client(
        create_app(settings=Settings(_env_file=None), store=store), key.api_key
    ) as restarted:
        assert restarted.get("/auth/me", headers=web).json() == identity
        current = restarted.get(BASE + "/session", headers=web)
        assert current.json()["method"] == "key" and "token" not in current.json()
        assert current.headers["cache-control"] == "private, no-store"
        store.revoke_key(key.key_id)
        assert restarted.get("/auth/me", headers=web).status_code == 401
        assert restarted.get(BASE + "/session", headers=web).status_code == 401
        assert (
            restarted.post(BASE + "/session/key", json={"key": key.api_key}).status_code
            == 401
        )


def test_oauth_flow_requires_a_recent_key_and_correct_browser(client):
    client.app.state.settings = Settings(_env_file=None)
    assert client.get(BASE + "/capabilities").json()["paypal_enabled"] is False
    assert (
        client.post(BASE + "/paypal/start", json={"intent": "signin"}).status_code
        == 503
    )
    configure(client)
    assert (
        client.post(BASE + "/paypal/start", json={"intent": "link"}).status_code == 403
    )
    web = session(client)
    request = start(client, "link", web)
    wrong_browser = {**request, "browser_token": "x" * 43}
    assert (
        client.post(
            BASE + "/paypal/finish", headers=web, json=wrong_browser
        ).status_code
        == 400
    )
    assert (
        client.post(BASE + "/paypal/finish", headers=NO_AUTH, json=request).status_code
        == 403
    )
    with client.app.state.store.transaction(write=True) as db:
        db.execute(
            "UPDATE merchant_paypal_flows SET expires_at=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
        )
        db.execute(
            "UPDATE merchant_web_sessions SET issued_at=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(),),
        )
    assert (
        client.post(BASE + "/paypal/finish", headers=web, json=request).status_code
        == 400
    )
    assert (
        client.post(
            BASE + "/paypal/start", headers=web, json={"intent": "link"}
        ).status_code
        == 403
    )
    assert client.delete(BASE + "/session", headers=web).status_code == 200
    assert client.get("/auth/me", headers=web).status_code == 401


@pytest.mark.skipif(
    os.getenv("RESOLVE_RUN_LOGIN_SIMULATION") != "1",
    reason="Requires the PayPal HTTPS simulation",
)
def test_verified_paypal_identity_links_only_to_existing_merchant(
    client, sandbox_client_factory
):
    sandbox_client_factory(client)
    configure(client)
    client.app.state.followup_http = client.app.state.paypal_client.http
    finish = BASE + "/paypal/finish"
    unknown = start(client, "signin")
    assert client.post(finish, headers=NO_AUTH, json=unknown).status_code == 403
    assert client.post(finish, headers=NO_AUTH, json=unknown).status_code == 400
    web = session(client)
    merchant = client.get("/auth/me").json()
    second = client.app.state.store.create_merchant("Another workspace")
    other_web = session(client, second.api_key)
    link = start(client, "link", web)
    assert client.post(finish, headers=other_web, json=link).status_code == 403
    assert client.post(finish, headers=web, json=link).json() == {
        "intent": "link",
        "session": None,
    }
    assert client.get(BASE + "/session", headers=web).json()["paypal_linked"]
    assert (
        client.post(
            finish, headers=other_web, json=start(client, "link", other_web)
        ).status_code
        == 409
    )
    other_subject = {**start(client, "signin"), "code": "resolve-code-other"}
    assert client.post(finish, headers=NO_AUTH, json=other_subject).status_code == 403
    missing = {**start(client, "signin"), "code": "resolve-code-missing"}
    assert client.post(finish, headers=NO_AUTH, json=missing).status_code == 503
    outage = {**start(client, "signin"), "code": "resolve-code-outage"}
    error = client.post(finish, headers=NO_AUTH, json=outage)
    assert error.status_code == 503 and "PRIVATE-PROVIDER-ERROR" not in error.text
    auth = client.post(finish, headers=NO_AUTH, json=start(client, "signin")).json()[
        "session"
    ]
    assert auth["method"] == "paypal" and auth["merchant"] == merchant
    paypal_session = {"Authorization": "Bearer " + auth["token"]}
    assert client.get("/auth/me", headers=paypal_session).json() == merchant
    assert (
        client.delete(BASE + "/paypal/link", headers=paypal_session).status_code == 403
    )
    assert client.delete(BASE + "/paypal/link", headers=web).status_code == 200
    assert client.get("/auth/me", headers=paypal_session).status_code == 401
    assert client.get("/auth/me", headers=web).status_code == 200


def test_browser_sdk_keys_are_once_only_scoped_and_revocable(client):
    from uuid import UUID

    base = "/merchant-auth/commerce-keys"
    store = client.app.state.store
    merchant = UUID(client.get("/auth/me").json()["id"])
    full = store.issue_key(merchant)
    web = session(client, full.api_key)
    foreign = store.create_merchant("Different workspace")
    other_web = session(client, foreign.api_key)
    assert client.get(base, headers=web).json() == {"keys": [], "can_manage": True}

    created = client.post(base, headers=web)
    assert created.status_code == 201
    assert "no-store" in created.headers["cache-control"]
    secret, identifier = created.json()["api_key"], created.json()["key_id"]
    scoped = {"Authorization": "Bearer " + secret}
    listing = client.get(base, headers=web)
    assert listing.json()["keys"][0]["key_id"] == identifier
    assert secret not in listing.text and "token_hash" not in listing.text
    with store.transaction() as db:
        row = db.execute(
            "SELECT token_hash, scope FROM merchant_api_keys WHERE id=?", (identifier,)
        ).fetchone()
        assert row["token_hash"] == sha256(secret.encode()).hexdigest()
        assert row["scope"] == "commerce"

    path = base + "/" + identifier
    assert client.get(base, headers=scoped).status_code == 401
    assert client.post(base, headers=scoped).status_code == 403
    assert client.delete(path, headers=other_web).status_code == 404
    assert client.delete(base + "/" + str(full.key_id), headers=web).status_code == 404
    assert (
        client.post("/merchant-auth/session/key", json={"key": secret}).status_code
        == 401
    )
    assert client.get("/commerce/orders", headers=scoped).status_code == 401
    order = {"source": "sdk-key-test", "order_reference": "ORDER-SDK-1", "revision": 1}
    route = "/commerce/orders/register"
    assert client.post(route, headers=scoped, json=order).status_code == 200

    assert client.delete(path, headers=web).status_code == 200
    assert client.delete(path, headers=web).status_code == 200
    assert client.post(route, headers=scoped, json=order).status_code == 401
    assert client.get(base, headers=web).json()["keys"] == []
    assert client.get("/auth/me", headers=web).status_code == 200

    old = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    with store.transaction(write=True) as db:
        db.execute(
            "UPDATE merchant_web_sessions SET issued_at=? WHERE api_key_id=?",
            (old, str(full.key_id)),
        )
    assert client.get(base, headers=web).json()["can_manage"] is False
    assert client.post(base, headers=web).status_code == 403
    assert client.delete(path, headers=web).status_code == 403
