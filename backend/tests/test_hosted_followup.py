from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.customer_email import mail_token, stamp
from app.settings import Settings
from test_customer_workflow import NO_AUTH, case_for, submit


def configured_mail(client):
    merchant = UUID(client.get("/auth/me").json()["id"])
    config = Settings(
        _env_file=None,
        customer_email_enabled=True,
        customer_email_merchant_id=merchant,
        customer_public_origin="https://resolve.example.com",
        customer_signing_key="synthetic-signing-key-for-tests-not-production",
        resend_api_key="simulation-resend-token",
        resend_from="updates@example.com",
    )
    client.app.state.settings = config
    return config


def issue_email(client, order, email):
    response = client.post(
        "/resolution-cases/intake-invites",
        json={"order_reference": order, "customer_email": email},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["email_queued"]
    return data["token"]


def sign_in(client, email, config):
    response = client.post(
        "/customer-account/request-sign-in", headers=NO_AUTH, json={"email": email}
    )
    assert response.status_code == 202, response.text
    with client.app.state.store.transaction() as db:
        job = db.execute(
            "SELECT id FROM customer_mail_outbox WHERE recipient=? AND kind='signin'",
            (email,),
        ).fetchone()
    token = mail_token(
        config.customer_signing_key.get_secret_value().encode(), "signin", job["id"]
    )
    response = client.post(
        "/customer-account/redeem", headers=NO_AUTH, json={"token": token}
    )
    assert response.status_code == 200, response.text
    assert (
        client.post(
            "/customer-account/redeem", headers=NO_AUTH, json={"token": token}
        ).status_code
        == 404
    )
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_email_bound_my_cases_and_revoke_checks(client):
    config = configured_mail(client)
    one = issue_email(client, "ORDER-EMAIL-A", "Buyer@EXAMPLE.COM")
    two = issue_email(client, "ORDER-EMAIL-B", "other@example.com")
    assert submit(client, one).status_code == submit(client, two).status_code == 200
    first = case_for(client, "ORDER-EMAIL-A")
    second = case_for(client, "ORDER-EMAIL-B")
    stranger = client.post(
        "/customer-account/request-sign-in",
        headers=NO_AUTH,
        json={"email": "unknown@example.com"},
    )
    assert stranger.status_code == 202 and stranger.json() == {"accepted": True}
    with client.app.state.store.transaction() as db:
        assert not db.execute(
            "SELECT 1 FROM customer_mail_outbox WHERE recipient='unknown@example.com'"
        ).fetchone()
        assert not db.execute(
            "SELECT 1 FROM customer_intake_invites WHERE token_hash=?", (one,)
        ).fetchone()
    assert client.get("/customer-account/cases").status_code == 401
    session = sign_in(client, "buyer@example.com", config)
    cases = client.get("/customer-account/cases", headers=session)
    assert (
        cases.status_code == 200
        and cases.headers["cache-control"] == "private, no-store"
    )
    assert [row["order_reference"] for row in cases.json()] == ["ORDER-EMAIL-A"]
    assert (
        client.post(
            "/customer-account/cases/" + second.split("/")[-1] + "/open",
            headers=session,
        ).status_code
        == 404
    )
    open_url = "/customer-account/cases/" + first.split("/")[-1] + "/open"
    # A verified mailbox can come back after the original share URL expires.
    with client.app.state.store.transaction(write=True) as db:
        db.execute(
            "UPDATE customer_portal_links SET expires_at=? WHERE resolution_id=?",
            (
                stamp(datetime.now(timezone.utc) - timedelta(hours=1)),
                first.split("/")[-1],
            ),
        )
    assert (
        client.post(
            "/customer-portal/view", headers=NO_AUTH, json={"token": one}
        ).status_code
        == 404
    )
    grant = client.post(open_url, headers=session).json()["token"]
    assert (
        client.post(
            "/customer-portal/view", headers=NO_AUTH, json={"token": grant}
        ).status_code
        == 200
    )
    assert client.delete(first + "/customer-link").status_code == 200
    assert (
        client.post(
            "/customer-portal/view", headers=NO_AUTH, json={"token": grant}
        ).status_code
        == 404
    )
    assert client.get("/customer-account/cases", headers=session).json() == []
    assert client.post("/customer-account/sign-out", headers=session).status_code == 200
    assert client.get("/customer-account/cases", headers=session).status_code == 401


def test_default_link_survives_and_mail_queue_deduplicates_replies(client):
    client.app.state.settings = Settings(_env_file=None)
    assert (
        client.post(
            "/resolution-cases/intake-invites",
            json={
                "order_reference": "NO-MAIL",
                "customer_email": "buyer@example.com",
            },
        ).status_code
        == 503
    )
    local = client.post(
        "/resolution-cases/intake-invites", json={"order_reference": "LOCAL"}
    )
    assert local.status_code == 201 and not local.json()["email_queued"]
    configured_mail(client)
    token = issue_email(client, "EMAIL-REPLIES", "buyer@example.com")
    assert submit(client, token).status_code == 200
    root = case_for(client, "EMAIL-REPLIES")
    message = {"request_id": str(uuid4()), "body": "Private text stays in Resolve"}
    assert client.post(root + "/customer-messages", json=message).status_code == 201
    assert client.post(root + "/customer-messages", json=message).status_code == 201
    with client.app.state.store.transaction() as db:
        jobs = db.execute(
            "SELECT kind,event_key FROM customer_mail_outbox ORDER BY kind"
        ).fetchall()
        assert [job["kind"] for job in jobs] == ["invite", "reply"]
        assert not any(message["body"] in job["event_key"] for job in jobs)


def test_signin_throttles_and_expired_tokens_cannot_be_redeemed(client):
    config = configured_mail(client)
    address = "buyer@example.com"
    assert (
        submit(client, issue_email(client, "ORDER-EXPIRY", address)).status_code == 200
    )
    for _ in range(3):
        assert (
            client.post(
                "/customer-account/request-sign-in",
                headers=NO_AUTH,
                json={"email": address},
            ).status_code
            == 202
        )
    with client.app.state.store.transaction(write=True) as db:
        rows = db.execute(
            "SELECT id FROM customer_mail_outbox WHERE kind='signin'"
        ).fetchall()
        assert len(rows) == 1
        db.execute(
            "UPDATE customer_signins SET expires_at=?",
            (stamp(datetime.now(timezone.utc) - timedelta(minutes=1)),),
        )
    token = mail_token(
        config.customer_signing_key.get_secret_value().encode(), "signin", rows[0]["id"]
    )
    assert (
        client.post(
            "/customer-account/redeem", headers=NO_AUTH, json={"token": token}
        ).status_code
        == 404
    )
