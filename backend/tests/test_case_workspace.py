import sqlite3
from uuid import uuid4

import pytest


def new_case(client, condition=None):
    result = client.post(
        "/cases",
        json={
            "order_id": "WORKSPACE-ORDER",
            "complaint": "Workspace test",
            "payment": {"capture_id": "WORKSPACECAPTURE", "captured_amount": "100.00"},
            "commitment": {
                "amount": "100.00",
                "source_message": "Test agreement",
                "condition": condition,
                "status": "accepted",
            },
        },
    )
    assert result.status_code == 201
    return result.json()["id"]


def update_body(client, case_id, **changes):
    case = client.get(f"/cases/{case_id}").json()
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    return {
        "state_fingerprint": basis["state_fingerprint"],
        "commitment": case["commitment"] | changes,
    }


def approval(client, case_id):
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    result = client.post(
        f"/cases/{case_id}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": "WORKSPACECAPTURE",
            "amount": basis["recommended_refund_amount"],
            "state_fingerprint": basis["state_fingerprint"],
            "decision_note": "Test decision",
        },
    )
    assert result.status_code == 201
    return result.json()


def test_case_list_paginates_and_filters_only_the_owner(client):
    first, second = new_case(client), new_case(client)
    other = client.app.state.store.create_merchant("Other workspace")
    headers = {"Authorization": f"Bearer {other.api_key}"}
    client.post(
        "/cases",
        json={
            "order_id": "OTHER",
            "complaint": "Other case",
            "payment": {"capture_id": "WORKSPACECAPTURE", "captured_amount": "100.00"},
        },
        headers=headers,
    )
    page = client.get("/cases?limit=1").json()
    assert page["total"] == 2 and page["items"][0]["id"] == second
    assert client.get("/cases?limit=1&offset=1").json()["items"][0]["id"] == first
    assert client.get("/cases?capture_id=missing").json()["total"] == 0
    assert client.get("/cases?capture_id=WORKSPACECAPTURE").json()["total"] == 2
    assert client.get("/cases", headers=headers).json()["total"] == 1
    assert client.get("/cases", headers={"Authorization": ""}).status_code == 401


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "capture_id=",
        "capture_id=%20",
    ],
)
def test_invalid_case_pagination_and_filters_are_rejected(client, query):
    assert client.get("/cases?" + query).status_code == 422


def test_commitment_can_be_added_after_case_creation(client):
    case_id = client.post(
        "/cases",
        json={
            "order_id": "EMPTY",
            "complaint": "No agreement yet",
            "payment": {"capture_id": "EMPTYCAPTURE", "captured_amount": "100.00"},
        },
    ).json()["id"]
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    result = client.put(
        f"/cases/{case_id}/commitment",
        json={
            "state_fingerprint": basis["state_fingerprint"],
            "commitment": {
                "amount": "50.00",
                "source_message": "New proposed agreement",
                "status": "proposed",
            },
        },
    )
    assert result.status_code == 200
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["status"]
        == "awaiting_acceptance"
    )


def test_commitment_revision_invalidates_approval_and_replay_is_a_noop(client):
    case_id = new_case(client)
    decision = approval(client, case_id)
    body = update_body(
        client, case_id, amount="80.00", source_message="Revised test agreement"
    )
    result = client.put(f"/cases/{case_id}/commitment", json=body)
    assert result.status_code == 200
    assert (
        client.get(f"/cases/{case_id}/refund-approvals/{decision['id']}").json()[
            "status"
        ]
        == "invalidated"
    )
    timeline = client.get(f"/cases/{case_id}/timeline").json()
    assert client.put(f"/cases/{case_id}/commitment", json=body).json() == result.json()
    assert client.get(f"/cases/{case_id}/timeline").json() == timeline
    stale = body | {"commitment": body["commitment"] | {"amount": "70.00"}}
    assert client.put(f"/cases/{case_id}/commitment", json=stale).status_code == 409


def test_changed_condition_does_not_reuse_old_physical_evidence(client):
    case_id = new_case(client, "Return received")
    check_url = f"/cases/{case_id}/condition-checks"
    assert (
        client.post(
            check_url, json={"status": "met", "evidence_note": "Test return received"}
        ).status_code
        == 201
    )
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["status"]
        == "refund_required"
    )
    body = update_body(client, case_id, condition="Inspection passed")
    assert client.put(f"/cases/{case_id}/commitment", json=body).status_code == 200
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    assert basis["status"] == "awaiting_condition" and basis["condition_check"] is None
    assert (
        client.post(
            f"/cases/{case_id}/refund-approvals",
            json={
                "request_id": str(uuid4()),
                "capture_id": "WORKSPACECAPTURE",
                "amount": "100.00",
                "state_fingerprint": basis["state_fingerprint"],
                "decision_note": "Old condition evidence cannot authorize this.",
            },
        ).status_code
        == 409
    )
    assert len(client.get(check_url).json()) == 1
    assert (
        client.post(
            check_url, json={"status": "met", "evidence_note": "Test inspection passed"}
        ).status_code
        == 201
    )
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["status"]
        == "refund_required"
    )


def test_unchanged_condition_retains_applicable_evidence(client):
    case_id = new_case(client, "Return received")
    client.post(
        f"/cases/{case_id}/condition-checks",
        json={"status": "met", "evidence_note": "Test return received"},
    )
    assert (
        client.put(
            f"/cases/{case_id}/commitment",
            json=update_body(client, case_id, amount="90.00"),
        ).status_code
        == 200
    )
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()[
            "recommended_refund_amount"
        ]
        == "90.00"
    )


def test_over_capture_commitment_is_rejected_without_mutation(client):
    case_id = new_case(client)
    body = update_body(client, case_id, amount="100.01")
    before = client.get(f"/cases/{case_id}/timeline").json()
    assert client.put(f"/cases/{case_id}/commitment", json=body).status_code == 422
    assert client.get(f"/cases/{case_id}/timeline").json() == before
    assert client.get(f"/cases/{case_id}").json()["commitment"]["amount"] == "100.00"


def test_failed_audit_insert_rolls_back_commitment_and_approval_invalidation(client):
    case_id = new_case(client)
    decision = approval(client, case_id)
    body = update_body(client, case_id, amount="80.00")
    before = client.get(f"/cases/{case_id}/reconciliation").json()
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_commitment_event BEFORE INSERT ON case_events
            WHEN NEW.event_type='commitment.updated' BEGIN SELECT RAISE(ABORT, 'forced commitment audit failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced commitment"):
        client.put(f"/cases/{case_id}/commitment", json=body)
    assert client.get(f"/cases/{case_id}/reconciliation").json() == before
    assert (
        client.get(f"/cases/{case_id}/refund-approvals/{decision['id']}").json()[
            "status"
        ]
        == "approved"
    )


def test_case_and_new_capture_roll_back_if_creation_audit_fails(client):
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_case_created BEFORE INSERT ON case_events
            WHEN NEW.event_type='case.created' BEGIN SELECT RAISE(ABORT, 'forced case audit failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced case audit"):
        new_case(client)
    assert client.get("/cases").json()["total"] == 0
    with sqlite3.connect(client.app.state.store.path) as connection:
        assert connection.execute("SELECT count(*) FROM captures").fetchone()[0] == 0


def test_timeline_preserves_refund_transitions_and_is_shared_only_within_owner(client):
    case_id, sibling = new_case(client), new_case(client)
    url = f"/cases/{case_id}/refunds"
    body = {
        "refund_id": "TIMELINEREFUND",
        "capture_id": "WORKSPACECAPTURE",
        "amount": "10.00",
        "status": "pending",
    }
    assert client.post(url, json=body).status_code == 201
    assert (
        client.patch(url + "/TIMELINEREFUND", json={"status": "failed"}).status_code
        == 200
    )
    entries = client.get(f"/cases/{sibling}/timeline").json()
    kinds = [item["event_type"] for item in entries["items"]]
    assert kinds.count("case.created") == 2
    assert "refund.recorded" in kinds and "refund.status_changed" in kinds
    assert all(item["actor_kind"] == "merchant" for item in entries["items"])
    assert (
        client.get(f"/cases/{case_id}/timeline?limit=1").json()["total"]
        == entries["total"]
    )
    other = client.app.state.store.create_merchant("Foreign timeline")
    assert (
        client.get(
            f"/cases/{case_id}/timeline",
            headers={"Authorization": f"Bearer {other.api_key}"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "method,suffix", [("GET", "/timeline"), ("PUT", "/commitment")]
)
def test_workspace_routes_require_auth_and_owner(client, method, suffix):
    case_id = new_case(client)
    body = update_body(client, case_id, amount="50.00") if method == "PUT" else None
    url = f"/cases/{case_id}" + suffix
    assert (
        client.request(
            method, url, json=body, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    other = client.app.state.store.create_merchant("Foreign owner")
    assert (
        client.request(
            method, url, json=body, headers={"Authorization": f"Bearer {other.api_key}"}
        ).status_code
        == 404
    )
