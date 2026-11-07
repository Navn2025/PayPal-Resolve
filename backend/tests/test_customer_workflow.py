from hashlib import sha256
from uuid import uuid4

from test_customer_portal import buyer_view
from test_refund_executions import LocalProvider, ready
from test_resolution_workspace import approval, finding, record, refund_case, workspace


NO_AUTH = {"Authorization": ""}
PDF = b"%PDF-1.7\nreceipt fixture\n"


def invite(client, order="ORDER-CUSTOMER-1"):
    response = client.post(
        "/resolution-cases/intake-invites", json={"order_reference": order}
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def submit(
    client, token, issue_type="damaged_delivery", description="A cracked lamp arrived."
):
    return client.post(
        "/customer-portal/intake",
        headers=NO_AUTH,
        json={
            "token": token,
            "issue_type": issue_type,
            "description": description,
        },
    )


def case_for(client, order):
    entries = client.get("/resolution-cases").json()["items"]
    return "/resolution-cases/" + next(
        row["id"] for row in entries if row["order_reference"] == order
    )


def test_order_invite_is_bound_one_use_expiring_and_revocable(client):
    order = "ORDER-CUSTOMER-1"
    token = invite(client, order)
    route = "/customer-portal/intake-view"
    assert client.post(route, headers=NO_AUTH, json={"token": order}).status_code == 404
    assert buyer_view(client, token).status_code == 404
    assert client.post(route, headers=NO_AUTH, json={"token": token}).json() == {
        "order_reference": order,
        "submitted": False,
    }
    overridden = client.post(
        "/customer-portal/intake",
        headers=NO_AUTH,
        json={
            "token": token,
            "order_reference": "OTHER",
            "issue_type": "missing_item",
            "description": "Wrong order",
        },
    )
    assert overridden.status_code == 422 and token not in overridden.text
    original = submit(client, token)
    assert original.status_code == 200, original.text
    data = original.json()
    assert data["order_reference"] == order and data["title"] == "Damaged delivery"
    assert data["timeline"][0]["label"] == "Request received"
    assert data["timeline"][0]["source"] == "customer_submitted"
    assert data["next_step"]["actor"] == "merchant"
    assert (
        submit(client, token, "refund_delay", "This is a retry.").json()["messages"]
        == data["messages"]
    )
    assert client.get("/resolution-cases").json()["total"] == 1
    url = case_for(client, order)
    assert client.get(url + "/operations").json()["issue_type"] == "damaged_delivery"
    expired = invite(client, "EXPIRED")
    with client.app.state.store.transaction(write=True) as db:
        db.execute(
            "UPDATE customer_intake_invites SET expires_at=? WHERE token_hash=?",
            ("2000-01-01T00:00:00.000000+00:00", sha256(expired.encode()).hexdigest()),
        )
    assert submit(client, expired).status_code == 404
    assert client.delete(url + "/customer-link").status_code == 200
    assert client.post(route, headers=NO_AUTH, json={"token": token}).status_code == 404
    assert submit(client, token).status_code == 404


def test_evidence_is_customer_submitted_bounded_and_case_scoped(client):
    token = invite(client)
    assert submit(client, token).status_code == 200
    url = case_for(client, "ORDER-CUSTOMER-1")
    upload = "/customer-portal/evidence"
    headers = {
        **NO_AUTH,
        "X-Customer-Link": token,
        "X-File-Name": "return-slip.pdf",
        "Content-Type": "application/pdf",
    }
    assert (
        client.post(
            upload,
            content=PDF,
            headers={**headers, "X-File-Name": "../return-slip.pdf"},
        ).status_code
        == 422
    )
    assert client.post(upload, content=b"not a PDF", headers=headers).status_code == 422
    assert (
        client.post(upload, content=PDF + b"x" * 2_097_152, headers=headers).status_code
        == 413
    )
    added = client.post(upload, content=PDF, headers=headers)
    assert added.status_code == 201, added.text
    file = added.json()
    assert file["source"] == "customer_submitted" and file["size_bytes"] == len(PDF)
    assert client.post(upload, content=PDF, headers=headers).json() == file
    assert buyer_view(client, token).json()["evidence"] == [file]
    assert client.get(url + "/customer-evidence").json() == [file]
    download = upload + "/" + file["id"]
    merchant_download = url + "/customer-evidence/" + file["id"]
    for response in (
        client.post(download, headers=NO_AUTH, json={"token": token}),
        client.get(merchant_download),
    ):
        assert response.content == PDF
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="return-slip.pdf"'
        )
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    other_token = invite(client, "ORDER-CUSTOMER-2")
    assert (
        client.post(
            upload, content=PDF, headers={**headers, "X-Customer-Link": other_token}
        ).status_code
        == 404
    )
    assert submit(client, other_token).status_code == 200
    assert (
        client.post(download, headers=NO_AUTH, json={"token": other_token}).status_code
        == 404
    )
    foreign = {
        "Authorization": "Bearer "
        + client.app.state.store.create_merchant("Other merchant").api_key
    }
    assert client.get(merchant_download, headers=foreign).status_code == 404
    assert client.get(url + "/operations", headers=foreign).status_code == 404
    assert client.delete(url + "/customer-link").status_code == 200
    assert (
        client.post(download, headers=NO_AUTH, json={"token": token}).status_code == 404
    )
    assert client.get(merchant_download).content == PDF


def test_triage_deadline_and_read_marker_handle_a_new_reply(client):
    token = invite(client)
    assert submit(client, token).status_code == 200
    url = case_for(client, "ORDER-CUSTOMER-1") + "/operations"
    first = client.get(url).json()
    assert first["unread_count"] == 1 and first["message_watermark"] > 0
    update = {
        "expected_revision": first["revision"],
        "assignee": "Returns team",
        "due_at": "2000-01-01T00:00:00Z",
        "waiting_on_customer": True,
    }
    saved = client.put(url, json=update).json()
    assert (
        saved["assignee"] == "Returns team"
        and saved["workflow"] == "waiting_on_customer"
    )
    assert saved["overdue"] and saved["next_actor"] == "customer"
    assert client.put(url, json=update).status_code == 409
    public = buyer_view(client, token)
    assert (
        public.json()["next_step"]["overdue"]
        and public.json()["next_step"]["actor"] == "customer"
    )
    assert "Returns team" not in public.text
    message = {
        "token": token,
        "request_id": str(uuid4()),
        "body": "I have the receipt.",
    }
    reply = client.post("/customer-portal/messages", headers=NO_AUTH, json=message)
    assert reply.status_code == 201, reply.text
    marked = client.post(
        url + "/read", json={"through": first["message_watermark"]}
    ).json()
    assert marked["unread_count"] == 1 and marked["workflow"] == "merchant_action"
    assert (
        client.post(
            url + "/read", json={"through": marked["message_watermark"] + 1}
        ).status_code
        == 422
    )
    cleared = client.post(
        url + "/read", json={"through": marked["message_watermark"]}
    ).json()
    assert cleared["unread_count"] == 0
    assert (
        client.put(
            url, json={**update, "expected_revision": cleared["revision"]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/customer-portal/messages", headers=NO_AUTH, json=message
        ).status_code
        == 201
    )
    assert client.get(url).json()["waiting_on_customer"]


def test_attach_existing_payment_to_intake_case_without_public_ids(client):
    token = invite(client)
    assert submit(client, token).status_code == 200
    url = case_for(client, "ORDER-CUSTOMER-1")
    payment = refund_case(client)
    route = url + "/payment-link"
    params = {"refund_case_id": payment}
    other = client.app.state.store.create_merchant("Other merchant")
    foreign = {"Authorization": "Bearer " + other.api_key}
    assert client.put(route, headers=foreign, json=params).status_code == 404
    assert client.put(route, json=params).json()["refund_case_id"] == payment
    assert client.put(route, json=params).status_code == 200
    extra = workspace(client, order="ANOTHER-ORDER")
    assert client.put(extra + "/payment-link", json=params).status_code == 409
    ret = record(
        client,
        url,
        {
            "kind": "return",
            "milestone": "warehouse_received",
            "return_reference": "PRIVATE-RMA",
        },
    )
    assert finding(client, url, ret, "confirmed").status_code == 201
    record(client, url, {"kind": "refund", "amount": "30.00"}, requires=[ret["id"]])
    public = buyer_view(client, token)
    assert public.status_code == 200, public.text
    assert [item["label"] for item in public.json()["timeline"]] == [
        "Request received",
        "Return confirmed",
    ]
    assert public.json()["refund"]["outstanding_amount"] == "30.00"
    assert not any(
        value in public.text
        for value in (payment, "PRIVATE-RMA", "TESTRESOLUTION", "Warehouse operator")
    )


def test_inbox_filters_before_pagination_and_respects_tenant(client):
    token = invite(client, "OLDER")
    assert submit(client, token).status_code == 200
    old = case_for(client, "OLDER")
    assert (
        client.put(
            old + "/operations",
            json={
                "expected_revision": 0,
                "waiting_on_customer": True,
                "assignee": "Returns queue",
            },
        ).status_code
        == 200
    )
    workspace(client, order="MIDDLE")
    newer = invite(client, "NEWER")
    assert submit(client, newer).status_code == 200
    assert (
        client.get("/resolution-cases/inbox?limit=1").json()["items"][0][
            "order_reference"
        ]
        == "NEWER"
    )
    second = client.get(
        "/resolution-cases/inbox?limit=1&offset=1&filter_by=unread"
    ).json()
    assert second["total"] == 2 and second["items"][0]["order_reference"] == "OLDER"
    waiting = client.get(
        "/resolution-cases/inbox?limit=1&filter_by=waiting_on_customer&q=returns"
    ).json()
    assert waiting["total"] == 1 and waiting["items"][0]["order_reference"] == "OLDER"
    other = client.app.state.store.create_merchant("Other merchant")
    foreign = {"Authorization": "Bearer " + other.api_key}
    assert (
        client.get("/resolution-cases/inbox?filter_by=unread", headers=foreign).json()[
            "total"
        ]
        == 0
    )


def test_pending_refund_timeline_updates_after_independent_provider_read(client):
    provider = LocalProvider(client.get("/auth/me").json()["id"])
    client.app.state.paypal_client.close()
    client.app.state.paypal_client = provider
    token = invite(client, "EXECUTION-ORDER")
    assert submit(client, token, "refund_delay").status_code == 200
    url = case_for(client, "EXECUTION-ORDER")
    payment, _ = ready(client)
    assert (
        client.put(url + "/payment-link", json={"refund_case_id": payment}).status_code
        == 200
    )
    record(client, url, {"kind": "refund", "amount": "100.00"})
    approved = approval(client, payment, "EXECCAPTURE", amount="100.00")
    assert approved.status_code == 201, approved.text
    request = {"request_id": str(uuid4()), "approval_id": approved.json()["id"]}
    assert (
        client.get("/resolution-cases/inbox?filter_by=pending_with_paypal").json()[
            "total"
        ]
        == 0
    )
    provider.mode = "pending"
    sent = client.post(f"/cases/{payment}/refund-executions", json=request)
    assert sent.status_code == 201, sent.text
    assert sent.json()["status"] == "pending"
    pending = client.get("/resolution-cases/inbox?filter_by=pending_with_paypal").json()
    assert (
        pending["total"] == 1
        and pending["items"][0]["operations"]["next_actor"] == "paypal"
    )
    view = buyer_view(client, token).json()
    assert [item["label"] for item in view["timeline"]] == [
        "Request received",
        "Refund approved",
    ]
    assert view["next_step"]["actor"] == "paypal"
    response = client.post(
        f"/cases/{payment}/refund-executions/{sent.json()['id']}/refresh"
    )
    assert response.status_code == 200 and response.json()["status"] == "completed"
    view = buyer_view(client, token).json()
    assert [item["label"] for item in view["timeline"]] == [
        "Request received",
        "Refund approved",
        "PayPal confirmed a refund",
    ]
    assert view["next_step"]["actor"] == "none"
    assert (
        client.get("/resolution-cases/inbox?filter_by=pending_with_paypal").json()[
            "total"
        ]
        == 0
    )
