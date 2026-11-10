"""The SDK order-support use case, exercised against disposable real application storage."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from test_platform_operations import promise

pytest_plugins = ("test_platform_operations",)


def setup_order(api, source="my-store", reference="AFTERCARE-1"):
    response = api.post(
        "/commerce/orders/register",
        json={
            "source": source,
            "order_reference": reference,
            "revision": 1,
            "order_status": "paid",
            "items": [{"product_id": "SKU1", "quantity": 1}],
        },
    )
    assert response.status_code == 200, response.text
    return {"source": source, "order_reference": reference}


def support_key(api, source="my-store"):
    response = api.post("/platform/support-keys", json={"source": source})
    assert response.status_code == 201, response.text
    return response.json(), {"Authorization": "Bearer " + response.json()["api_key"]}


def report(locator):
    return {
        **locator,
        "request_id": str(uuid4()),
        "reason": "damaged_item",
        "message": "My item arrived damaged.",
        "requested_resolution": "replacement",
    }


def test_support_workflow_is_opt_in_scoped_and_retry_safe(api):
    locator = setup_order(api)
    ordinary = api.post("/platform/sdk-keys").json()["api_key"]
    assert (
        api.post(
            "/aftercare/status",
            json=locator,
            headers={"Authorization": "Bearer " + ordinary},
        ).status_code
        == 403
    )
    key, headers = support_key(api)
    assert (
        api.post("/aftercare/status", json=locator, headers=headers).json()["stage"]
        == "no_issue"
    )
    assert api.get("/resolution-cases").json()["total"] == 0
    request = report(locator)
    response = api.post("/aftercare/issues", json=request, headers=headers)
    assert response.status_code == 201, response.text
    assert (
        api.post("/aftercare/issues", json=request, headers=headers).json()
        == response.json()
    )
    assert (
        api.post(
            "/aftercare/issues",
            json={**request, "message": "Changed request"},
            headers=headers,
        ).status_code
        == 409
    )
    progress = api.post("/aftercare/status", json=locator, headers=headers)
    assert progress.status_code == 200, progress.text
    assert progress.json()["issue_count"] == 1
    assert progress.json()["stage"] == "under_review"
    assert progress.json()["authorizes_payment"] is False
    case_id = response.json()["case_id"]
    requests = api.get(f"/platform/cases/{case_id}/support-requests").json()["items"]
    assert requests[0]["requested_resolution"] == "replacement"
    assert requests[0]["message"] == request["message"]
    assert (
        api.get(
            f"/platform/cases/{case_id}/support-requests", headers=headers
        ).status_code
        == 401
    )

    assert (
        api.post(
            "/aftercare/status",
            json={**locator, "source": "other-store"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        api.post(
            "/aftercare/status",
            json={**locator, "order_reference": "UNKNOWN"},
            headers=headers,
        ).status_code
        == 404
    )
    assert api.get("/platform/dashboard", headers=headers).status_code == 401
    assert api.get("/resolution-cases", headers=headers).status_code == 401
    with api.app.state.store.transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM customer_portal_messages").fetchone()[0]
            == 1
        )
        assert db.execute("SELECT count(*) FROM resolution_promises").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0
    assert api.delete("/platform/sdk-keys/" + key["key_id"]).status_code == 200
    assert (
        api.post("/aftercare/status", json=locator, headers=headers).status_code == 401
    )


def test_customer_status_offers_privacy_and_portal_rotation(api):
    api.app.state.settings.merchant_web_origin = "https://resolve.example.test"
    locator = setup_order(api)
    _, headers = support_key(api)
    assert (
        api.post("/aftercare/portal", json=locator, headers=headers).status_code == 409
    )
    receipt = api.post(
        "/aftercare/issues", json=report(locator), headers=headers
    ).json()
    identifier = receipt["case_id"]
    p = promise(api, identifier)
    offered = api.post(
        f"/platform/cases/{identifier}/offers",
        json={
            "choices": [{"promise_id": p["id"], "expected_revision": 1}],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert offered.status_code == 201, offered.text
    progress = api.post("/aftercare/status", json=locator, headers=headers)
    assert progress.json()["next_action"] == "review_offer", progress.text
    assert "PRIVATE SYNTHETIC SOURCE" not in progress.text
    assert "RMA-TEST" not in progress.text
    portal = api.post("/aftercare/portal", json=locator, headers=headers)
    assert portal.status_code == 201, portal.text
    assert (
        portal.json()["public_url"]
        == "https://resolve.example.test/customer#" + portal.json()["token"]
    )
    buyer = api.post("/customer-portal/view", json={"token": portal.json()["token"]})
    assert buyer.status_code == 200, buyer.text
    assert buyer.json()["messages"][0]["body"] == "My item arrived damaged."
    revised = api.put(
        f"/resolution-cases/{identifier}/promises/{p['id']}",
        json={**p["terms"], "promise": "We will inspect it", "expected_revision": 1},
    )
    assert revised.status_code == 200
    progress = api.post("/aftercare/status", json=locator, headers=headers)
    assert progress.json()["next_action"] == "wait"
    assert (
        api.post("/aftercare/portal", json=locator, headers=headers).status_code == 201
    )
    assert (
        api.post(
            "/customer-portal/view", json={"token": portal.json()["token"]}
        ).status_code
        == 404
    )
    assert (
        api.post(
            f"/resolution-cases/{identifier}/promises/{p['id']}/evidence",
            json={
                "expected_revision": 2,
                "finding": "confirmed",
                "note": "PRIVATE warehouse record",
            },
        ).status_code
        == 201
    )
    progress = api.post("/aftercare/status", json=locator, headers=headers)
    assert progress.json()["stage"] == "resolved"
    assert progress.json()["promises"][0]["provider_confirmed"] is False
    assert "PRIVATE warehouse record" not in progress.text


def test_support_requests_do_not_turn_reported_refunds_into_verified_money(api):
    locator = setup_order(api)
    _, headers = support_key(api)
    identifier = api.post(
        "/aftercare/issues", json=report(locator), headers=headers
    ).json()["case_id"]
    legacy = api.post(
        "/cases",
        json={
            "order_id": "AFTERCARE-1",
            "complaint": "Synthetic refund",
            "payment": {"capture_id": "AFTERCARETOTAL", "captured_amount": "25.00"},
            "commitment": {
                "amount": "25.00",
                "status": "accepted",
                "source_message": "PRIVATE finance note",
            },
        },
    ).json()["id"]
    assert (
        api.put(
            f"/resolution-cases/{identifier}/payment-link",
            json={"refund_case_id": legacy},
        ).status_code
        == 200
    )
    promise(api, identifier, kind="refund")
    assert (
        api.post(
            f"/cases/{legacy}/refunds",
            json={
                "refund_id": "UNVERIFIEDREFUND",
                "capture_id": "AFTERCARETOTAL",
                "amount": "25.00",
                "status": "completed",
            },
        ).status_code
        == 201
    )
    response = api.post("/aftercare/status", json=locator, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["refund"]["verification"] == "unverified"
    assert response.json()["refund"]["completed_amount"] is None
    assert response.json()["refund"]["remaining_amount"] is None
    assert response.json()["stage"] != "resolved"


def test_other_workspace_cannot_read_order_and_staff_cannot_issue_support_keys(api):
    from test_platform_operations import invite

    locator = setup_order(api)
    agent = invite(api, "agent")
    assert (
        api.post(
            "/platform/support-keys",
            json={"source": "my-store"},
            headers={"Authorization": "Bearer " + agent["token"]},
        ).status_code
        == 403
    )
    other = api.post(
        "/platform/account/signup",
        json={
            "workspace": "Other store",
            "name": "Other owner",
            "email": "other-aftercare@example.test",
            "password": "synthetic-other-password-123",
        },
    ).json()
    assert (
        api.post(
            "/aftercare/status",
            json=locator,
            headers={"Authorization": "Bearer " + other["token"]},
        ).status_code
        == 404
    )
    _, headers = support_key(api)
    oversized = report(locator)
    oversized["message"] = "x" * 40000
    response = api.post("/aftercare/issues", json=oversized, headers=headers)
    assert response.status_code == 413
    assert "x" * 100 not in response.text
