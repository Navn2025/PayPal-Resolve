import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.settings import BACKEND_DIR, Settings


@pytest.fixture
def durable_case():
    return {
        "order_id": "ORDER-PERSISTENCE",
        "complaint": "My agreed refund is incomplete.",
        "payment": {"capture_id": "CAPTURE-PERSISTENCE", "captured_amount": "100.00"},
        "commitment": {
            "amount": "100.00", "status": "accepted",
            "source_message": "We will refund $100 after receiving the return.",
            "condition": "Return must be received",
        },
    }


def observation(refund_id, amount="20.00", status="completed"):
    return {
        "refund_id": refund_id, "capture_id": "CAPTURE-PERSISTENCE",
        "amount": amount, "status": status,
    }


def test_records_and_replay_survive_restart_and_separate_process(
    tmp_path, durable_case, merchant_client
):
    database = tmp_path / "durable.sqlite3"
    with merchant_client(create_app(database)) as first:
        api_key = first.headers["Authorization"].split(" ", 1)[1]
        response = first.post("/cases", json=durable_case)
        assert response.status_code == 201
        saved_case = response.json()
        case_id = saved_case["id"]
        prefix = f"/cases/{case_id}"
        assert first.post(
            f"{prefix}/refunds", json=observation("REFUND-COMPLETED")
        ).status_code == 201
        assert first.post(
            f"{prefix}/refunds", json=observation("REFUND-PENDING", "80.00", "pending")
        ).status_code == 201
        for status in ("not_met", "met"):
            assert first.post(
                f"{prefix}/condition-checks",
                json={"status": status, "evidence_note": f"Development return check: {status}."},
            ).status_code == 201
        saved_checks = first.get(f"{prefix}/condition-checks").json()
        saved_summary = first.get(f"{prefix}/reconciliation").json()

    with merchant_client(create_app(database), api_key) as restarted:
        assert restarted.get(prefix).json() == saved_case
        assert restarted.get(f"{prefix}/condition-checks").json() == saved_checks
        assert restarted.get(f"{prefix}/reconciliation").json() == saved_summary
        assert restarted.post(
            f"{prefix}/refunds", json=observation("REFUND-PENDING", "80.00", "pending")
        ).status_code == 200
        assert restarted.patch(
            f"{prefix}/refunds/REFUND-PENDING", json={"status": "failed"}
        ).status_code == 200
        expected = restarted.get(f"{prefix}/reconciliation").json()
        assert expected["failed_refund_amount"] == "80.00"
        assert expected["recommended_refund_amount"] == "80.00"

    # A fresh Python interpreter has no shared app object or Python memory.
    script = """
import json, sys
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
options = json.load(sys.stdin)
with TestClient(create_app(Path(options['database']))) as client:
    client.headers['Authorization'] = 'Bearer ' + options['api_key']
    prefix = '/cases/' + options['case_id']
    case = client.get(prefix)
    assert case.status_code == 200
    result = client.get(prefix + '/reconciliation')
    assert result.status_code == 200
    replay = client.post(prefix + '/refunds', json={
        'refund_id': 'REFUND-COMPLETED', 'capture_id': 'CAPTURE-PERSISTENCE',
        'amount': '20.00', 'status': 'completed'
    })
    assert replay.status_code == 200
    print(json.dumps({
        'summary': result.json(),
        'refund_count': len(client.get(prefix + '/refunds').json()),
        'check_count': len(client.get(prefix + '/condition-checks').json())
    }))
"""
    process = subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND_DIR,
        input=json.dumps({"database": str(database), "case_id": case_id, "api_key": api_key}),
        capture_output=True, text=True, timeout=30, check=True,
    )
    result = json.loads(process.stdout)
    assert result["summary"] == expected
    assert result["refund_count"] == 2
    assert result["check_count"] == 2


def test_app_construction_does_not_create_runtime_database(tmp_path):
    database = tmp_path / "not-created-yet" / "resolve.sqlite3"
    create_app(database)
    assert not database.exists()
    assert not database.parent.exists()


def test_unknown_schema_fails_startup_without_resetting_existing_data(tmp_path):
    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('preserve me')")
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="Unsupported database schema version: 999"):
        with TestClient(create_app(database)):
            pass
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "preserve me"


@pytest.mark.parametrize("already_has_claim", [False, True])
def test_sqlite_14_upgrades_both_paypal_flow_variants(tmp_path, already_has_claim):
    database = tmp_path / "prior.sqlite3"
    with sqlite3.connect(database) as connection:
        files = sorted((BACKEND_DIR / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
        for path in files[:14]:
            connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 14")
        connection.execute(
            """INSERT INTO merchant_paypal_flows
               (state_hash,browser_hash,issuer_key,intent,expires_at)
               VALUES ('existing','browser','issuer','signin','2030-01-01')"""
        )
        if already_has_claim:
            connection.execute(
                "ALTER TABLE merchant_paypal_flows ADD COLUMN claimed_at TEXT"
            )
            connection.execute(
                "UPDATE merchant_paypal_flows SET claimed_at='already claimed'"
            )
    app = create_app(database, settings=Settings(_env_file=None))
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 25
        flows = connection.execute(
            "SELECT state_hash,claimed_at FROM merchant_paypal_flows"
        ).fetchall()
        assert flows == [("existing", "already claimed" if already_has_claim else None)]


@pytest.mark.parametrize("already_has_flags", [False, True])
def test_sqlite_16_upgrades_both_notification_variants(tmp_path, already_has_flags):
    database = tmp_path / "customer-16.sqlite3"
    with sqlite3.connect(database) as db:
        files = sorted((BACKEND_DIR / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
        for path in files[:16]:
            db.executescript(path.read_text(encoding="utf-8"))
        db.execute("PRAGMA user_version = 16")
        if already_has_flags:
            db.executescript(files[16].read_text(encoding="utf-8"))
        db.execute("INSERT INTO merchants VALUES ('existing','Existing merchant','2026-01-01')")
        db.execute(
            """INSERT INTO customer_intake_invites
               (token_hash,merchant_id,order_reference,created_at,expires_at)
               VALUES ('prior','existing','ORDER-16','2026-01-01','2030-01-01')"""
        )
        if already_has_flags:
            db.execute("UPDATE customer_intake_invites SET email_notifications=0")
    app = create_app(database, settings=Settings(_env_file=None))
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 25
        assert db.execute(
            "SELECT order_reference,email_notifications FROM customer_intake_invites"
        ).fetchone() == ("ORDER-16", int(not already_has_flags))
        assert db.execute("SELECT email_notifications FROM customer_case_contacts").fetchall() == []


def test_first_migration_is_recorded_and_repeated_startup_preserves_data(
    tmp_path, durable_case, merchant_client
):
    database = tmp_path / "schema.sqlite3"
    api_key = None
    for run in range(2):
        with merchant_client(create_app(database), api_key) as client:
            api_key = client.headers["Authorization"].split(" ", 1)[1]
            if run == 0:
                case_id = client.post("/cases", json=durable_case).json()["id"]
            assert client.get(f"/cases/{case_id}").status_code == 200
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 25
        assert connection.execute("SELECT count(*) FROM cases").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM captures").fetchone()[0] == 1


@pytest.mark.parametrize("same_refund_id", [False, True])
def test_independent_app_instances_share_atomic_balance_and_replay_protection(
    tmp_path, durable_case, same_refund_id, merchant_client
):
    database = tmp_path / "shared.sqlite3"
    with merchant_client(create_app(database)) as first:
        api_key = first.headers["Authorization"].split(" ", 1)[1]
        with merchant_client(create_app(database), api_key) as second:
            _check_competing_instances(first, second, durable_case, same_refund_id)


def _check_competing_instances(first, second, durable_case, same_refund_id):
        case_id = first.post("/cases", json=durable_case).json()["id"]
        url = f"/cases/{case_id}/refunds"

        def submit(item):
            client, refund_id = item
            return client.post(url, json=observation(refund_id, "60.00", "pending"))

        identifiers = ("REFUND-A", "REFUND-A" if same_refund_id else "REFUND-B")
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit, [(first, identifiers[0]), (second, identifiers[1])]))
        expected = [200, 201] if same_refund_id else [201, 409]
        assert sorted(response.status_code for response in responses) == expected
        assert len(second.get(url).json()) == 1
        result = second.get(f"/cases/{case_id}/reconciliation").json()
        assert result["pending_refund_amount"] == "60.00"
        assert result["remaining_refundable_amount"] == "40.00"


def test_failed_case_insert_rolls_back_its_capture(client, durable_case):
    # Force a database failure after capture insertion to test the transaction boundary.
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_case BEFORE INSERT ON cases
            BEGIN SELECT RAISE(ABORT, 'forced insert failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced insert failure"):
        client.post("/cases", json=durable_case)
    with sqlite3.connect(client.app.state.store.path) as connection:
        assert connection.execute("SELECT count(*) FROM captures").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM cases").fetchone()[0] == 0


def test_money_is_persisted_as_integer_cents(client, durable_case):
    durable_case["payment"]["captured_amount"] = "0.30"
    durable_case["commitment"]["amount"] = "0.20"
    case_id = client.post("/cases", json=durable_case).json()["id"]
    assert client.post(
        f"/cases/{case_id}/refunds", json=observation("REFUND-CENTS", "0.10")
    ).status_code == 201
    with sqlite3.connect(client.app.state.store.path) as connection:
        assert connection.execute(
            "SELECT captured_cents, typeof(captured_cents) FROM captures"
        ).fetchone() == (30, "integer")
        assert connection.execute(
            "SELECT amount_cents, typeof(amount_cents) FROM refunds"
        ).fetchone() == (10, "integer")


def test_busy_database_returns_retryable_error_without_writing(client, durable_case):
    case_id = client.post("/cases", json=durable_case).json()["id"]
    client.app.state.store.timeout = 0.01
    locker = sqlite3.connect(client.app.state.store.path, isolation_level=None)
    try:
        locker.execute("BEGIN IMMEDIATE")
        response = client.post(
            f"/cases/{case_id}/refunds", json=observation("REFUND-BUSY")
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Database is busy; retry the request"}
    finally:
        locker.rollback()
        locker.close()
    assert client.get(f"/cases/{case_id}/refunds").json() == []
    assert client.post(
        f"/cases/{case_id}/refunds", json=observation("REFUND-BUSY")
    ).status_code == 201


def test_relative_database_setting_resolves_from_backend(monkeypatch):
    monkeypatch.setenv("RESOLVE_DATABASE_PATH", "data/alternate.sqlite3")
    assert Settings(_env_file=None).database_path == BACKEND_DIR / "data" / "alternate.sqlite3"


@pytest.mark.parametrize("value", ["", "   ", ":memory:"])
def test_database_setting_requires_a_real_file_path(monkeypatch, value):
    monkeypatch.setenv("RESOLVE_DATABASE_PATH", value)
    with pytest.raises(ValidationError, match="non-empty local database file path"):
        Settings(_env_file=None)
