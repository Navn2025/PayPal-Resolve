import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app import approvals
from app.main import create_app
from app.models import CaseCreate
from app.settings import BACKEND_DIR
from app.storage import SQLiteStore


def case_body(condition=None):
    return {
        "order_id": "ORDER-APPROVAL",
        "complaint": "My refund is incomplete.",
        "payment": {"capture_id": "CAPTURE-APPROVAL", "captured_amount": "100.00"},
        "commitment": {
            "amount": "100.00",
            "source_message": "Refund $100 agreed.",
            "status": "accepted",
            "condition": condition,
        },
    }


def refund_body(refund_id="REFUND-INITIAL", amount="20.00", status="completed"):
    return {
        "refund_id": refund_id,
        "capture_id": "CAPTURE-APPROVAL",
        "amount": amount,
        "status": status,
    }


def approval_body(client, case_id):
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    return {
        "request_id": str(uuid4()),
        "capture_id": "CAPTURE-APPROVAL",
        "amount": basis["recommended_refund_amount"],
        "currency": "USD",
        "state_fingerprint": basis["state_fingerprint"],
        "decision_note": "Approve this exact remaining refund after review.",
    }


@pytest.fixture
def ready_case(client):
    created = client.post("/cases", json=case_body())
    assert created.status_code == 201
    case_id = created.json()["id"]
    assert (
        client.post(f"/cases/{case_id}/refunds", json=refund_body()).status_code == 201
    )
    return case_id


def create_approval(client, case_id):
    body = approval_body(client, case_id)
    response = client.post(f"/cases/{case_id}/refund-approvals", json=body)
    assert response.status_code == 201
    return response.json(), body


def test_approval_binds_exact_state_without_executing_or_counting_as_refund(
    client, ready_case
):
    before = client.get(f"/cases/{ready_case}/reconciliation").json()
    approval, request = create_approval(client, ready_case)
    UUID(approval["id"])
    assert approval["status"] == "approved"
    assert approval["amount"] == "80.00"
    assert approval["capture_id"] == "CAPTURE-APPROVAL"
    assert approval["state_fingerprint"] == before["state_fingerprint"]
    assert approval["basis"] == before
    assert approval["verified_with_paypal"] is False
    assert approval["merchant_id"] == client.get("/auth/me").json()["id"]
    assert datetime.fromisoformat(approval["expires_at"]) - datetime.fromisoformat(
        approval["approved_at"]
    ) == timedelta(minutes=15)
    assert client.get(f"/cases/{ready_case}/reconciliation").json() == before
    assert len(client.get(f"/cases/{ready_case}/refunds").json()) == 1
    events = client.get(
        f"/cases/{ready_case}/refund-approvals/{approval['id']}/events"
    ).json()
    assert [event["event_type"] for event in events] == ["approved"]
    assert events[0]["actor_merchant_id"] == approval["merchant_id"]
    assert events[0]["note"] == request["decision_note"]


def test_approval_retries_do_not_duplicate_and_changed_request_is_rejected(
    client, ready_case
):
    approval, body = create_approval(client, ready_case)
    url = f"/cases/{ready_case}/refund-approvals"
    assert client.post(url, json=body).json() == approval
    assert client.post(url, json=body).status_code == 200
    body["decision_note"] = "A different decision"
    assert client.post(url, json=body).status_code == 409
    assert len(client.get(url).json()) == 1


@pytest.mark.parametrize(
    ("field", "value", "status"),
    [
        ("amount", "81.00", 409),
        ("amount", "79.00", 409),
        ("amount", "0.00", 422),
        ("amount", "0.001", 422),
        ("capture_id", "OTHER-CAPTURE", 409),
        ("currency", "EUR", 422),
        ("state_fingerprint", "0" * 64, 409),
        ("state_fingerprint", "bad", 422),
        ("decision_note", "   ", 422),
        ("merchant_id", str(uuid4()), 422),
    ],
)
def test_tampered_or_invalid_approval_cannot_be_saved(
    client, ready_case, field, value, status
):
    body = approval_body(client, ready_case)
    body[field] = value
    url = f"/cases/{ready_case}/refund-approvals"
    assert client.post(url, json=body).status_code == status
    assert client.get(url).json() == []


def test_stale_preview_is_rejected_and_fresh_preview_uses_new_amount(
    client, ready_case
):
    stale = approval_body(client, ready_case)
    assert (
        client.post(
            f"/cases/{ready_case}/refunds", json=refund_body("REFUND-EXTRA", "10.00")
        ).status_code
        == 201
    )
    assert (
        client.post(f"/cases/{ready_case}/refund-approvals", json=stale).status_code
        == 409
    )
    fresh, _ = create_approval(client, ready_case)
    assert fresh["amount"] == "70.00"
    assert fresh["state_fingerprint"] != stale["state_fingerprint"]


@pytest.mark.parametrize(
    "blocked_state", ["proposed", "no_commitment", "condition", "pending", "fulfilled"]
)
def test_ineligible_case_cannot_authorize_a_refund(client, blocked_state):
    payload = case_body()
    if blocked_state == "proposed":
        payload["commitment"]["status"] = "proposed"
    elif blocked_state == "no_commitment":
        payload["commitment"] = None
    elif blocked_state == "condition":
        payload["commitment"]["condition"] = "Return must arrive"
    case_id = client.post("/cases", json=payload).json()["id"]
    if blocked_state in ("pending", "fulfilled"):
        client.post(
            f"/cases/{case_id}/refunds",
            json=refund_body(
                amount="100.00",
                status="pending" if blocked_state == "pending" else "completed",
            ),
        )
    body = approval_body(client, case_id)
    body["amount"] = "1.00"
    assert (
        client.post(f"/cases/{case_id}/refund-approvals", json=body).status_code == 409
    )


def test_refund_observation_invalidates_approval_and_preserves_original_basis(
    client, ready_case
):
    approval, original = create_approval(client, ready_case)
    refund = refund_body("REFUND-EXTRA", "10.00")
    assert client.post(f"/cases/{ready_case}/refunds", json=refund).status_code == 201
    url = f"/cases/{ready_case}/refund-approvals/{approval['id']}"
    record = client.get(url).json()
    assert record["status"] == "invalidated"
    assert record["basis"]["recommended_refund_amount"] == "80.00"
    assert (
        client.get(f"/cases/{ready_case}/reconciliation").json()[
            "recommended_refund_amount"
        ]
        == "70.00"
    )
    assert [event["event_type"] for event in client.get(url + "/events").json()] == [
        "approved",
        "invalidated",
    ]
    assert client.post(f"/cases/{ready_case}/refunds", json=refund).status_code == 200
    replay = client.post(f"/cases/{ready_case}/refund-approvals", json=original)
    assert replay.status_code == 200
    assert replay.json()["status"] == "invalidated"
    assert len(client.get(url + "/events").json()) == 2


def test_condition_changes_invalidate_even_when_the_amount_remains_the_same(client):
    case_id = client.post("/cases", json=case_body("Return must arrive")).json()["id"]
    check = {"status": "met", "evidence_note": "Return receipt A"}
    assert (
        client.post(f"/cases/{case_id}/condition-checks", json=check).status_code == 201
    )
    approval, _ = create_approval(client, case_id)
    check["evidence_note"] = "Revised receipt B"
    client.post(f"/cases/{case_id}/condition-checks", json=check)
    assert (
        client.get(f"/cases/{case_id}/refund-approvals/{approval['id']}").json()[
            "status"
        ]
        == "invalidated"
    )


def test_noop_refund_observations_and_status_updates_do_not_invalidate(
    client, ready_case
):
    # Failed observations do not reserve funds, so an approval remains possible.
    client.post(
        f"/cases/{ready_case}/refunds",
        json=refund_body("REFUND-FAILED", "10.00", "failed"),
    )
    approval, _ = create_approval(client, ready_case)
    client.post(f"/cases/{ready_case}/refunds", json=refund_body())
    client.patch(
        f"/cases/{ready_case}/refunds/REFUND-INITIAL", json={"status": "completed"}
    )
    url = f"/cases/{ready_case}/refund-approvals/{approval['id']}"
    assert client.get(url).json()["status"] == "approved"
    assert len(client.get(url + "/events").json()) == 1


def test_revoke_is_idempotent_and_fresh_approval_requires_new_request_id(
    client, ready_case
):
    approval, body = create_approval(client, ready_case)
    prefix = f"/cases/{ready_case}/refund-approvals"
    url = f"{prefix}/{approval['id']}"
    reason = {"reason": "I need to review this again"}
    assert client.post(url + "/revoke", json=reason).json()["status"] == "revoked"
    assert client.post(url + "/revoke", json=reason).status_code == 200
    assert len(client.get(url + "/events").json()) == 2
    assert client.post(prefix, json=body).json()["status"] == "revoked"
    body["request_id"] = str(uuid4())
    assert client.post(prefix, json=body).status_code == 201


def test_expiry_is_persistent_and_old_request_never_reactivates(
    client, ready_case, monkeypatch
):
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(approvals, "utc_now", lambda: clock[0])
    approval, body = create_approval(client, ready_case)
    clock[0] += timedelta(minutes=15)
    prefix = f"/cases/{ready_case}/refund-approvals"
    url = f"{prefix}/{approval['id']}"
    assert client.get(url).json()["status"] == "expired"
    events = client.get(url + "/events").json()
    assert [event["event_type"] for event in events] == ["approved", "expired"]
    assert events[-1]["actor_merchant_id"] is None
    assert client.post(prefix, json=body).json()["status"] == "expired"
    assert client.post(url + "/revoke", json={"reason": "Too late"}).status_code == 409
    body["request_id"] = str(uuid4())
    assert client.post(prefix, json=body).status_code == 201
    assert len(client.get(url + "/events").json()) == 2


@pytest.mark.parametrize("identical_request", [False, True])
def test_concurrent_app_instances_cannot_create_duplicate_active_approvals(
    client, ready_case, merchant_client, identical_request
):
    api_key = client.headers["Authorization"].split(" ", 1)[1]
    first_body = approval_body(client, ready_case)
    second_body = dict(first_body)
    if not identical_request:
        second_body["request_id"] = str(uuid4())
    with merchant_client(create_app(client.app.state.store.path), api_key) as second:

        def submit(item):
            caller, body = item
            return caller.post(f"/cases/{ready_case}/refund-approvals", json=body)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(submit, [(client, first_body), (second, second_body)])
            )
    assert sorted(response.status_code for response in responses) == (
        [200, 201] if identical_request else [201, 409]
    )
    assert len(client.get(f"/cases/{ready_case}/refund-approvals").json()) == 1


def test_capture_level_limit_applies_across_cases(client, ready_case):
    approval, _ = create_approval(client, ready_case)
    second_id = client.post("/cases", json=case_body()).json()["id"]
    body = approval_body(client, second_id)
    assert (
        client.post(f"/cases/{second_id}/refund-approvals", json=body).status_code
        == 409
    )
    assert (
        client.get(f"/cases/{second_id}/refund-approvals/{approval['id']}").status_code
        == 404
    )


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("POST", "", "approval"),
        ("GET", "", None),
        ("GET", "/{id}", None),
        ("POST", "/{id}/revoke", {"reason": "Not my case"}),
        ("GET", "/{id}/events", None),
    ],
)
def test_approval_routes_require_owner_and_authentication(
    client, ready_case, method, suffix, body
):
    approval, request = create_approval(client, ready_case)
    other = client.app.state.store.create_merchant("Other merchant")
    url = f"/cases/{ready_case}/refund-approvals" + suffix.replace(
        "{id}", approval["id"]
    )
    payload = request if body == "approval" else body
    assert (
        client.request(
            method, url, json=payload, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert (
        client.request(
            method,
            url,
            json=payload,
            headers={"Authorization": f"Bearer {other.api_key}"},
        ).status_code
        == 404
    )
    assert (
        client.get(f"/cases/{ready_case}/refund-approvals/{approval['id']}").json()[
            "status"
        ]
        == "approved"
    )


def test_approval_events_and_replay_survive_new_application(
    client, ready_case, merchant_client
):
    approval, body = create_approval(client, ready_case)
    token = client.headers["Authorization"].split(" ", 1)[1]
    prefix = f"/cases/{ready_case}/refund-approvals"
    with merchant_client(create_app(client.app.state.store.path), token) as restarted:
        assert restarted.get(f"{prefix}/{approval['id']}").json() == approval
        assert restarted.post(prefix, json=body).status_code == 200
        assert len(restarted.get(f"{prefix}/{approval['id']}/events").json()) == 1


def test_approval_insert_rolls_back_if_event_record_cannot_be_written(
    client, ready_case
):
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_approval_event
            BEFORE INSERT ON refund_approval_events
            BEGIN SELECT RAISE(ABORT, 'forced event failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced event failure"):
        client.post(
            f"/cases/{ready_case}/refund-approvals",
            json=approval_body(client, ready_case),
        )
    with sqlite3.connect(client.app.state.store.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM refund_approvals").fetchone()[0]
            == 0
        )


def test_refund_and_approval_invalidation_roll_back_together_on_audit_failure(
    client, ready_case
):
    approval, _ = create_approval(client, ready_case)
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_invalidation_event
            BEFORE INSERT ON refund_approval_events WHEN NEW.event_type = 'invalidated'
            BEGIN SELECT RAISE(ABORT, 'forced invalidation failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced invalidation failure"):
        client.post(
            f"/cases/{ready_case}/refunds",
            json=refund_body("SHOULD-ROLL-BACK", "10.00"),
        )
    assert len(client.get(f"/cases/{ready_case}/refunds").json()) == 1
    url = f"/cases/{ready_case}/refund-approvals/{approval['id']}"
    assert client.get(url).json()["status"] == "approved"
    assert len(client.get(url + "/events").json()) == 1


def test_version_two_upgrade_keeps_existing_identity_and_case(tmp_path):
    database = tmp_path / "version-two.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            (BACKEND_DIR / "migrations/001_initial.sql").read_text()
        )
        connection.executescript(
            (BACKEND_DIR / "migrations/002_merchants.sql").read_text()
        )
        connection.execute("PRAGMA user_version = 2")
    old_store = SQLiteStore(database)
    issued = old_store.create_merchant("Existing version-two merchant")
    payload = CaseCreate.model_validate(case_body())
    case_id = uuid4()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO captures VALUES (?,?,?,?)",
            (str(issued.merchant.id), payload.payment.capture_id, 10000, "USD"),
        )
        connection.execute(
            "INSERT INTO cases (id,merchant_id,order_id,complaint,capture_id,commitment_json,status) VALUES (?,?,?,?,?,?,?)",
            (
                str(case_id),
                str(issued.merchant.id),
                payload.order_id,
                payload.complaint,
                payload.payment.capture_id,
                payload.commitment.model_dump_json(),
                "open",
            ),
        )
    with TestClient(create_app(database)) as upgraded:
        upgraded.headers["Authorization"] = f"Bearer {issued.api_key}"
        assert upgraded.get(f"/cases/{case_id}").status_code == 200
        assert upgraded.get(f"/cases/{case_id}/refund-approvals").json() == []
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
