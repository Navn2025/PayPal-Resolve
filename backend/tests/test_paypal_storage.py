"""Local database guarantees using synthetic provider DTOs; no HTTP verification."""

import json
import sqlite3
from uuid import UUID, uuid4

import pytest

from app.main import create_app
from app.paypal import PayPalCaptureDetails
from app.storage import StoreError


@pytest.fixture
def capture_case(client):
    body = {
        "order_id": "STORAGE-ORDER",
        "complaint": "Verify payment evidence",
        "payment": {"capture_id": "SIMCAPTUREOK", "captured_amount": "100.00"},
        "commitment": {
            "amount": "100.00",
            "status": "accepted",
            "source_message": "Full refund agreed.",
        },
    }
    first = client.post("/cases", json=body)
    assert first.status_code == 201
    return first.json()["id"], body


def synthetic_capture(**changes):
    data = {
        "id": "SIMCAPTUREOK",
        "amount": {"value": "100.00", "currency_code": "USD"},
        "status": "COMPLETED",
        "payee": {"merchant_id": "SIMSELLER001"},
    }
    return PayPalCaptureDetails.model_validate(data | changes)


def approve(client, case_id):
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    response = client.post(
        f"/cases/{case_id}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": "SIMCAPTUREOK",
            "amount": "100.00",
            "currency": "USD",
            "state_fingerprint": basis["state_fingerprint"],
            "decision_note": "Local storage test decision.",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_capture_evidence_is_shared_only_within_its_merchant(client, capture_case):
    case_id, body = capture_case
    sibling = client.post("/cases", json=body).json()["id"]
    other = client.app.state.store.create_merchant("Other evidence owner")
    other_headers = {"Authorization": f"Bearer {other.api_key}"}
    foreign_case = client.post("/cases", json=body, headers=other_headers).json()["id"]
    before = client.get(f"/cases/{sibling}/reconciliation").json()
    client.app.state.store.record_capture_verification(
        UUID(case_id), UUID(client.get("/auth/me").json()["id"]), synthetic_capture()
    )
    history = client.get(f"/cases/{sibling}/paypal-capture-verifications").json()
    assert len(history) == 1
    assert (
        history[0]["case_id"] == case_id
    )  # Preserve the observation's originating case.
    after = client.get(f"/cases/{sibling}/reconciliation").json()
    assert after["capture_verification"] == history[0]
    assert after["state_fingerprint"] != before["state_fingerprint"]
    assert (
        client.get(
            f"/cases/{foreign_case}/paypal-capture-verifications", headers=other_headers
        ).json()
        == []
    )
    assert (
        client.get(
            f"/cases/{foreign_case}/reconciliation", headers=other_headers
        ).json()["capture_verification"]
        is None
    )


def test_verification_and_approval_invalidation_roll_back_together(
    client, capture_case
):
    case_id, _ = capture_case
    approval = approve(client, case_id)
    before = client.get(f"/cases/{case_id}/reconciliation").json()
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_capture_invalidation
            BEFORE INSERT ON refund_approval_events WHEN NEW.event_type = 'invalidated'
            BEGIN SELECT RAISE(ABORT, 'forced capture invalidation failure'); END""")
    with pytest.raises(
        sqlite3.IntegrityError, match="forced capture invalidation failure"
    ):
        client.app.state.store.record_capture_verification(
            UUID(case_id), UUID(approval["merchant_id"]), synthetic_capture()
        )
    assert client.get(f"/cases/{case_id}/paypal-capture-verifications").json() == []
    assert client.get(f"/cases/{case_id}/reconciliation").json() == before
    prefix = f"/cases/{case_id}/refund-approvals/{approval['id']}"
    assert client.get(prefix).json()["status"] == "approved"
    assert len(client.get(prefix + "/events").json()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "OTHERID"},
        {"amount": {"value": "90.00", "currency_code": "USD"}},
    ],
)
def test_store_rechecks_case_payment_when_saving_external_evidence(
    client, capture_case, changes
):
    case_id, _ = capture_case
    with pytest.raises(StoreError) as error:
        client.app.state.store.record_capture_verification(
            UUID(case_id),
            UUID(client.get("/auth/me").json()["id"]),
            synthetic_capture(**changes),
        )
    assert error.value.status_code == 409
    assert client.get(f"/cases/{case_id}/paypal-capture-verifications").json() == []


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_old_schema_upgrade_preserves_approval_and_snapshot(
    client, capture_case, merchant_client, tmp_path, version
):
    from app.settings import BACKEND_DIR

    case_id, _ = capture_case
    approval = approve(client, case_id)
    database = tmp_path / f"version-{version}.sqlite3"
    migrations = sorted((BACKEND_DIR / "migrations").glob("*.sql"))
    with (
        sqlite3.connect(client.app.state.store.path) as source,
        sqlite3.connect(database) as target,
    ):
        for migration in migrations[:version]:
            target.executescript(migration.read_text(encoding="utf-8"))
        # Copy only columns/tables from the real historical schema, not a modern
        # database with a lowered version marker. Missing JSON fields are legacy.
        tables = [
            "merchants",
            "merchant_api_keys",
            "captures",
            "cases",
            "refunds",
            "condition_checks",
            "refund_approvals",
            "refund_approval_events",
            "paypal_capture_verifications",
            "refund_executions",
            "refund_execution_events",
            "paypal_refund_verifications",
        ]
        for table in tables:
            columns = [row[1] for row in target.execute(f"PRAGMA table_info({table})")]
            if not columns:
                continue
            fields = ",".join(columns)
            rows = source.execute(f"SELECT {fields} FROM {table}").fetchall()
            for row in rows:
                values = list(row)
                if table == "refund_approvals":
                    index = columns.index("snapshot_json")
                    snapshot = json.loads(values[index])
                    if version < 4:
                        snapshot["basis"].pop("capture_verification", None)
                    if version < 5:
                        snapshot["basis"].pop("refund_verifications", None)
                        snapshot["basis"].pop("active_refund_execution_id", None)
                    if version < 7:
                        snapshot["basis"].pop("failed_refund_execution_id", None)
                    values[index] = json.dumps(snapshot)
                target.execute(
                    f"INSERT OR IGNORE INTO {table} ({fields}) VALUES ({','.join('?' for _ in columns)})",
                    values,
                )
        target.execute(f"PRAGMA user_version={version}")
    key = client.headers["Authorization"].split(" ", 1)[1]
    with merchant_client(create_app(database), key) as upgraded:
        assert upgraded.get(f"/cases/{case_id}").status_code == 200
        assert (
            upgraded.get(f"/cases/{case_id}/refund-approvals/{approval['id']}").json()
            == approval
        )
        timeline = upgraded.get(f"/cases/{case_id}/timeline").json()
        assert not any(
            item["event_type"] == "case.created" for item in timeline["items"]
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
