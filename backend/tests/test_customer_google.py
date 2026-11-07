from datetime import datetime, timedelta, timezone
import os
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

import pytest

from app.customer_email import stamp
from app.settings import Settings
from google_simulation_support import register_google_code
from test_customer_workflow import NO_AUTH, case_for, submit


ROOT = "/customer-account"


def configure(client):
    settings = Settings(
        _env_file=None,
        customer_google_enabled=True,
        google_client_id="simulation-google-client",
        google_client_secret="simulation-google-secret",
        customer_public_origin="https://resolve.example.com",
    )
    client.app.state.settings = settings


def start(client):
    response = client.post(ROOT + "/google/start", headers=NO_AUTH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    query = dict(parse_qsl(urlsplit(body["authorize_url"]).query))
    assert query["scope"] == "openid email"
    assert (
        query["redirect_uri"]
        == "https://resolve.example.com/api/customer-account/google/callback"
    )
    assert query["code_challenge_method"] == "S256"
    return query, body["browser_token"]


def copy_invite(client, email, order):
    response = client.post(
        "/resolution-cases/intake-invites",
        json={"order_reference": order, "customer_email": email, "send_email": False},
    )
    assert response.status_code == 201, response.text
    assert response.json()["email_queued"] is False
    assert submit(client, response.json()["token"], "missing_item").status_code == 200


def test_google_flow_requires_configuration_browser_and_unexpired_state(client):
    client.app.state.settings = Settings(_env_file=None)
    assert client.get(ROOT + "/capabilities").json() == {
        "google_enabled": False,
        "email_enabled": False,
    }
    assert client.post(ROOT + "/google/start").status_code == 503
    configure(client)
    assert client.get(ROOT + "/capabilities").json() == {
        "google_enabled": True,
        "email_enabled": False,
    }
    query, browser = start(client)
    body = {"state": query["state"], "code": "unregistered", "browser_token": "z" * 43}
    assert client.post(ROOT + "/google/finish", json=body).status_code == 400
    with client.app.state.store.transaction(write=True) as db:
        row = db.execute(
            "SELECT state_hash,browser_hash FROM customer_google_flows"
        ).fetchone()
        assert query["state"] != row["state_hash"] and browser != row["browser_hash"]
        db.execute(
            "UPDATE customer_google_flows SET expires_at=?",
            (stamp(datetime.now(timezone.utc) - timedelta(seconds=1)),),
        )
    body["browser_token"] = browser
    assert client.post(ROOT + "/google/finish", json=body).status_code == 400


@pytest.mark.skipif(
    os.environ.get("RESOLVE_RUN_GOOGLE_SIMULATION") != "1",
    reason="Requires the Google HTTPS simulation",
)
def test_google_uses_signed_mailbox_identity_and_never_accepts_a_callback_twice(
    client, sandbox_client_factory
):
    sandbox_client_factory(client)
    configure(client)
    proxy_http = client.app.state.paypal_client.http
    client.app.state.followup_http = proxy_http
    copy_invite(client, "buyer@gmail.com", "GOOGLE-CASE")
    copy_invite(client, "other@gmail.com", "OTHER-CASE")
    assert (
        client.post(
            case_for(client, "GOOGLE-CASE") + "/customer-messages",
            json={
                "request_id": str(uuid4()),
                "body": "Merchant follow-up stays in the portal.",
            },
        ).status_code
        == 201
    )
    with client.app.state.store.transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM customer_mail_outbox").fetchone()[0] == 0
        )

    def finish(expect, **options):
        query, browser = start(client)
        code = register_google_code(proxy_http, query, **options)
        payload = {"state": query["state"], "code": code, "browser_token": browser}
        response = client.post(ROOT + "/google/finish", headers=NO_AUTH, json=payload)
        assert response.status_code == expect, response.text
        assert (
            client.post(
                ROOT + "/google/finish", headers=NO_AUTH, json=payload
            ).status_code
            == 400
        )
        return response.json()

    token = finish(200)["token"]
    headers = {"Authorization": "Bearer " + token}
    cases = client.get(ROOT + "/cases", headers=headers).json()
    assert [entry["order_reference"] for entry in cases] == ["GOOGLE-CASE"]
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert (
        client.post(
            ROOT + "/cases/" + cases[0]["id"] + "/open", headers=headers
        ).status_code
        == 200
    )
    assert client.post(ROOT + "/sign-out", headers=headers).status_code == 200
    assert client.get(ROOT + "/cases", headers=headers).status_code == 401
    assert finish(200, email="employee@workspace.example", hd="workspace.example")[
        "token"
    ].startswith("racs_")
    finish(403, email="buyer@example.com")
    finish(403, email_verified=False)
    finish(400, nonce="unmatched")
    finish(503, aud="wrong-client")
    finish(503, invalid_signature=True)
