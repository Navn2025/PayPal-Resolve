import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.manage import main as manage
from app.settings import BACKEND_DIR
from app.storage import LEGACY_MERCHANT_ID, StoreError


def case_body(capture_id="CAPTURE-A", amount="100.00"):
    return {
        "order_id": "ORDER-A", "complaint": "My refund is incomplete.",
        "payment": {"capture_id": capture_id, "captured_amount": amount},
        "commitment": {
            "amount": amount, "status": "accepted", "source_message": "Full refund agreed.",
            "condition": "Return must arrive",
        },
    }


def refund_body(capture_id="CAPTURE-A", amount="20.00"):
    return {
        "refund_id": "REFUND-A", "capture_id": capture_id,
        "amount": amount, "status": "pending",
    }


@pytest.fixture
def owned_case(client):
    response = client.post("/cases", json=case_body())
    assert response.status_code == 201
    case_id = response.json()["id"]
    assert client.post(f"/cases/{case_id}/refunds", json=refund_body()).status_code == 201
    return case_id


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("GET", "/refunds", None),
        ("POST", "/refunds", refund_body()),
        ("PATCH", "/refunds/REFUND-A", {"status": "completed"}),
        ("GET", "/condition-checks", None),
        ("POST", "/condition-checks", {"status": "met", "evidence_note": "Forged receipt"}),
        ("GET", "/reconciliation", None),
    ],
)
def test_other_merchant_cannot_read_or_mutate_case(client, owned_case, method, suffix, body):
    other = client.app.state.store.create_merchant("Other merchant")
    response = client.request(
        method, f"/cases/{owned_case}{suffix}", json=body,
        headers={"Authorization": f"Bearer {other.api_key}"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Case not found"}
    assert client.get(f"/cases/{owned_case}/refunds").json()[0]["status"] == "pending"
    assert client.get(f"/cases/{owned_case}/condition-checks").json() == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/auth/me", None),
        ("POST", "/cases", case_body()),
        ("GET", "/cases/{id}", None),
        ("GET", "/cases/{id}/refunds", None),
        ("POST", "/cases/{id}/refunds", refund_body()),
        ("PATCH", "/cases/{id}/refunds/REFUND-A", {"status": "completed"}),
        ("GET", "/cases/{id}/condition-checks", None),
        ("POST", "/cases/{id}/condition-checks", {"status": "met", "evidence_note": "Receipt"}),
        ("GET", "/cases/{id}/reconciliation", None),
    ],
)
def test_missing_credentials_block_every_protected_route(client, method, path, body):
    response = client.request(
        method, path.replace("{id}", str(uuid4())), json=body,
        headers={"Authorization": ""},
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer invalid", "Bearer rslv_fake", "Bearer " + "x" * 600])
def test_invalid_credentials_receive_uniform_error(client, authorization):
    response = client.get("/auth/me", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing merchant credentials"}


def test_health_is_public_and_openapi_declares_bearer_auth(client):
    assert client.post("/health", headers={"Authorization": ""}).status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/cases"]["post"]["security"] == [{"MerchantBearer": []}]
    assert "security" not in schema["paths"]["/health"]["post"]


def test_owner_is_derived_from_token_and_cannot_be_spoofed(client, owned_case):
    identity = client.get("/auth/me").json()
    assert client.get(f"/cases/{owned_case}").json()["merchant_id"] == identity["id"]
    body = case_body()
    body["merchant_id"] = str(uuid4())
    assert client.post("/cases", json=body).status_code == 422
    other = client.app.state.store.create_merchant("Other merchant")
    assert client.get(
        f"/cases/{owned_case}?merchant_id={identity['id']}",
        headers={"Authorization": f"Bearer {other.api_key}"},
    ).status_code == 404


def test_same_provider_ids_have_independent_balances_across_merchants(client, owned_case):
    other = client.app.state.store.create_merchant("Other merchant")
    headers = {"Authorization": f"Bearer {other.api_key}"}
    response = client.post("/cases", json=case_body(amount="50.00"), headers=headers)
    assert response.status_code == 201
    other_id = response.json()["id"]
    assert client.get(f"/cases/{other_id}/refunds", headers=headers).json() == []
    assert client.post(
        f"/cases/{other_id}/refunds", json=refund_body(amount="30.00"), headers=headers
    ).status_code == 201
    own = client.get(f"/cases/{owned_case}/reconciliation").json()
    theirs = client.get(f"/cases/{other_id}/reconciliation", headers=headers).json()
    assert own["pending_refund_amount"] == "20.00"
    assert own["remaining_refundable_amount"] == "80.00"
    assert theirs["pending_refund_amount"] == "30.00"
    assert theirs["remaining_refundable_amount"] == "20.00"


def test_condition_actor_is_recorded_by_server(client, owned_case):
    identity = client.get("/auth/me").json()
    body = {"status": "met", "evidence_note": "Warehouse receipt"}
    response = client.post(f"/cases/{owned_case}/condition-checks", json=body)
    assert response.status_code == 201
    assert response.json()["recorded_by_merchant_id"] == identity["id"]
    body["recorded_by_merchant_id"] = str(uuid4())
    assert client.post(f"/cases/{owned_case}/condition-checks", json=body).status_code == 422


def test_keys_are_random_hash_only_and_revocable(client):
    store = client.app.state.store
    issued = store.create_merchant("Key test")
    extra = store.issue_key(issued.merchant.id)
    assert issued.api_key.startswith("rslv_")
    assert len(issued.api_key) == 48
    assert issued.api_key != extra.api_key
    assert issued.api_key not in repr(issued)
    with sqlite3.connect(store.path) as connection:
        digest = connection.execute(
            "SELECT token_hash FROM merchant_api_keys WHERE id = ?", (str(issued.key_id),)
        ).fetchone()[0]
        assert digest == hashlib.sha256(issued.api_key.encode()).hexdigest()
    assert issued.api_key.encode() not in store.path.read_bytes()
    headers = {"Authorization": f"Bearer {issued.api_key}"}
    assert client.get("/auth/me", headers=headers).status_code == 200
    store.revoke_key(issued.key_id)
    store.revoke_key(issued.key_id)
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.get(
        "/auth/me", headers={"Authorization": f"Bearer {extra.api_key}"}
    ).status_code == 200


@pytest.fixture
def legacy_database(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy_id = str(uuid4())
    with sqlite3.connect(path) as connection:
        connection.executescript((BACKEND_DIR / "migrations/001_initial.sql").read_text())
        connection.execute("INSERT INTO captures VALUES ('CAPTURE-A', 10000, 'USD')")
        connection.execute(
            "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?)",
            (legacy_id, "OLD-ORDER", "Old complaint", "CAPTURE-A",
             json.dumps(case_body()["commitment"]), "open"),
        )
        connection.execute(
            """INSERT INTO refunds (refund_id, capture_id, amount_cents, currency, status)
               VALUES ('REFUND-A', 'CAPTURE-A', 2000, 'USD', 'completed')"""
        )
        connection.execute(
            """INSERT INTO condition_checks (case_id, status, evidence_note, recorded_at)
               VALUES (?, 'met', 'Preserve original receipt', '2026-11-07T01:00:00+00:00')""",
            (legacy_id,),
        )
        connection.execute("PRAGMA user_version = 1")
    return path, legacy_id


def test_version_one_upgrade_preserves_records_without_automatic_assignment(legacy_database):
    path, case_id = legacy_database
    with TestClient(create_app(path)) as client:
        store = client.app.state.store
        first = store.create_merchant("First new merchant")
        second = store.create_merchant("Second new merchant")
        headers = {"Authorization": f"Bearer {first.api_key}"}
        assert client.get(f"/cases/{case_id}", headers=headers).status_code == 404
        with sqlite3.connect(path) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
            assert connection.execute("SELECT merchant_id FROM cases").fetchone()[0] == str(LEGACY_MERCHANT_ID)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        counts = store.claim_legacy(first.merchant.id)
        assert counts == {"captures": 1, "cases": 1, "refunds": 1}
        result = client.get(f"/cases/{case_id}", headers=headers)
        assert result.status_code == 200
        assert result.json()["merchant_id"] == str(first.merchant.id)
        history = client.get(f"/cases/{case_id}/condition-checks", headers=headers).json()
        assert history[0]["evidence_note"] == "Preserve original receipt"
        assert history[0]["recorded_by_merchant_id"] is None
        summary = client.get(f"/cases/{case_id}/reconciliation", headers=headers).json()
        assert summary["recommended_refund_amount"] == "80.00"
        assert client.get(
            f"/cases/{case_id}", headers={"Authorization": f"Bearer {second.api_key}"}
        ).status_code == 404
        assert store.claim_legacy(first.merchant.id) == {"captures": 0, "cases": 0, "refunds": 0}
        with pytest.raises(StoreError, match="Merchant not found"):
            store.issue_key(LEGACY_MERCHANT_ID)
        with sqlite3.connect(path) as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("collision", ["capture", "refund"])
def test_conflicting_legacy_assignment_rolls_back_every_record(legacy_database, collision):
    path, legacy_id = legacy_database
    with TestClient(create_app(path)) as client:
        store = client.app.state.store
        issued = store.create_merchant("Target merchant")
        client.headers["Authorization"] = f"Bearer {issued.api_key}"
        capture = "CAPTURE-A" if collision == "capture" else "DIFFERENT-CAPTURE"
        case_id = client.post("/cases", json=case_body(capture)).json()["id"]
        if collision == "refund":
            assert client.post(
                f"/cases/{case_id}/refunds", json=refund_body(capture)
            ).status_code == 201
        with pytest.raises(StoreError, match="conflicting capture or refund IDs"):
            store.claim_legacy(issued.merchant.id)
        assert client.get(f"/cases/{legacy_id}").status_code == 404
        with sqlite3.connect(path) as connection:
            assert connection.execute(
                "SELECT merchant_id FROM cases WHERE id = ?", (legacy_id,)
            ).fetchone()[0] == str(LEGACY_MERCHANT_ID)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_database_foreign_keys_reject_mixed_merchant_capture_ownership(client, owned_case):
    other = client.app.state.store.create_merchant("Other merchant")
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO cases (id, merchant_id, order_id, complaint, capture_id, status)
                   VALUES (?, ?, 'MIXED', 'Must fail', 'CAPTURE-A', 'open')""",
                (str(uuid4()), str(other.merchant.id)),
            )


def test_admin_commands_create_rotate_revoke_and_report_errors(tmp_path, capsys):
    database = tmp_path / "admin.sqlite3"
    prefix = ["--database", str(database)]
    assert manage(prefix + ["create-merchant", "--name", "CLI merchant"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["api_key"].startswith("rslv_")
    merchant_id = first["merchant"]["id"]
    assert manage(prefix + ["issue-key", "--merchant-id", merchant_id]) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["api_key"] != second["api_key"]
    assert manage(prefix + ["revoke-key", "--key-id", first["key_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["revoked"] is True
    assert manage(prefix + ["claim-legacy", "--merchant-id", merchant_id]) == 0
    assert json.loads(capsys.readouterr().out) == {"captures": 0, "cases": 0, "refunds": 0}
    with TestClient(create_app(database)) as client:
        assert client.get(
            "/auth/me", headers={"Authorization": f"Bearer {first['api_key']}"}
        ).status_code == 401
        assert client.get(
            "/auth/me", headers={"Authorization": f"Bearer {second['api_key']}"}
        ).json()["id"] == merchant_id
    assert manage(prefix + ["issue-key", "--merchant-id", str(uuid4())]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Merchant not found" in captured.err


def test_no_public_merchant_provisioning_endpoint(client):
    assert client.post("/merchants", json={"name": "Untrusted"}).status_code == 404
