from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from app.errors import StoreError
from app.main import create_app
from app.migrate_sqlite import migrate
from app.postgres import MIGRATIONS, PostgresStore
from app.settings import Settings
from test_customer_portal import buyer_view
from test_customer_workflow import NO_AUTH, PDF, invite, submit as issue
from test_refund_executions import LocalProvider, ready, submit as refund
from test_resolution_workspace import refund_case


def test_applied_postgres_scripts_keep_their_canonical_checksums():
    expected = {
        1: "a4e55ff2c62d62cbfc39b33a59c049472f6e0e2c6db2b66e956a2fde986a1f9b",
        2: "35d9a244575d7bfed8505a8d17d251a859148fb537b432a79615a6b0c1097d16",
        3: "eb6e217bdade284267610657924ef64e70198a21eefca840f0233edea2cc3e64",
        4: "4c958258bd1653264a3566b3669bcaa29fc19ede1b221366e4f584ab4e60617e",
        5: "f35198f84e02a31e1a364d945b25507e685415c6c8401cfdc41e811f0829a1bc",
        6: "6bd216c8fce4340b220ff04ec5b765bbfe62201c7f378d81f566a0110bea31f5",
        7: "60d75405896d21b771ff8696f085f485acb458b1e89e4171213eaaba37aab91f",
    }
    found = {
        int(path.name[:3]): sha256(
            path.read_text(encoding="utf-8").encode()
        ).hexdigest()
        for path in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")
    }
    for version, checksum in expected.items():
        assert found.get(version) == checksum, (
            f"Append a migration instead of editing {version:03d}"
        )


def _rewind_evidence_schema(db):
    for suffix in ("events", "state", "links", "refs"):
        db.execute("DROP TABLE resolution_evidence_" + suffix)


@pytest.mark.parametrize(
    ("old_checksum", "already_has_claim"),
    [
        ("eb6e217bdade284267610657924ef64e70198a21eefca840f0233edea2cc3e64", False),
        ("930815d19dd63d32ca11991c9ced6409e6f0617e4cbe34a094896a0c5daf676a", True),
    ],
)
def test_postgres_003_upgrades_both_paypal_flow_variants(
    postgres_store, old_checksum, already_has_claim
):
    key = postgres_store.create_merchant("Existing workspace")
    with postgres_store.transaction(write=True) as db:
        db.execute("DELETE FROM schema_migrations WHERE version>=4")
        _rewind_evidence_schema(db)
        db.execute("DROP TABLE customer_google_flows")
        db.execute("ALTER TABLE customer_mail_outbox DROP COLUMN delivery_transport")
        db.execute(
            "ALTER TABLE customer_intake_invites DROP COLUMN email_notifications"
        )
        db.execute("ALTER TABLE customer_case_contacts DROP COLUMN email_notifications")
        db.execute(
            "UPDATE schema_migrations SET checksum=? WHERE version=3", (old_checksum,)
        )
        if not already_has_claim:
            db.execute("ALTER TABLE merchant_paypal_flows DROP COLUMN claimed_at")
        db.execute(
            """INSERT INTO merchant_paypal_flows
               (state_hash,browser_hash,issuer_key,intent,expires_at)
               VALUES ('existing','browser','issuer','signin','2030-01-01')"""
        )
        if already_has_claim:
            db.execute("UPDATE merchant_paypal_flows SET claimed_at='already claimed'")
    app = create_app(settings=Settings(_env_file=None), store=postgres_store)
    headers = {"Authorization": f"Bearer {key.api_key}"}
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/auth/me", headers=headers).json()["id"] == str(
                key.merchant.id
            )
    with postgres_store.transaction() as db:
        assert (
            db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 7
        )
        assert (
            db.execute(
                "SELECT checksum FROM schema_migrations WHERE version=3"
            ).fetchone()[0]
            == old_checksum
        )
        assert tuple(
            db.execute(
                "SELECT state_hash,claimed_at FROM merchant_paypal_flows"
            ).fetchone()
        ) == ("existing", "already claimed" if already_has_claim else None)


@pytest.mark.parametrize(
    ("old_checksum", "already_has_flags"),
    [
        ("f35198f84e02a31e1a364d945b25507e685415c6c8401cfdc41e811f0829a1bc", False),
        ("a40a7fd1a6d29de6d8a5ce8e2a4ae6e8db7a664701b47850ebdba363f8cd4c54", True),
    ],
)
def test_postgres_005_upgrades_both_notification_variants(
    postgres_store, old_checksum, already_has_flags
):
    merchant_id = str(postgres_store.create_merchant("Existing workspace").merchant.id)
    with postgres_store.transaction(write=True) as db:
        db.execute("DELETE FROM schema_migrations WHERE version>=6")
        _rewind_evidence_schema(db)
        db.execute(
            "UPDATE schema_migrations SET checksum=? WHERE version=5", (old_checksum,)
        )
        if not already_has_flags:
            db.execute(
                "ALTER TABLE customer_intake_invites DROP COLUMN email_notifications"
            )
            db.execute(
                "ALTER TABLE customer_case_contacts DROP COLUMN email_notifications"
            )
        db.execute(
            """INSERT INTO customer_intake_invites
               (token_hash,merchant_id,order_reference,created_at,expires_at)
               VALUES ('prior',?,'ORDER-005','2026-01-01','2030-01-01')""",
            (merchant_id,),
        )
        if already_has_flags:
            db.execute("UPDATE customer_intake_invites SET email_notifications=0")
    app = create_app(settings=Settings(_env_file=None), store=postgres_store)
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    with postgres_store.transaction() as db:
        assert (
            db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 7
        )
        assert (
            db.execute(
                "SELECT checksum FROM schema_migrations WHERE version=5"
            ).fetchone()[0]
            == old_checksum
        )
        assert tuple(
            db.execute(
                "SELECT order_reference,email_notifications FROM customer_intake_invites"
            ).fetchone()
        ) == ("ORDER-005", int(not already_has_flags))
        assert (
            db.execute(
                "SELECT email_notifications FROM customer_case_contacts"
            ).fetchall()
            == []
        )


@pytest.mark.parametrize("version", [3, 5])
def test_postgres_still_rejects_an_unknown_migration_checksum(postgres_store, version):
    with postgres_store.transaction(write=True) as db:
        db.execute("DELETE FROM schema_migrations WHERE version>?", (version,))
        db.execute(
            "UPDATE schema_migrations SET checksum=? WHERE version=?",
            ("0" * 64, version),
        )
    with pytest.raises(
        RuntimeError,
        match=f"modified PostgreSQL migration history at version {version:03d}",
    ):
        postgres_store.initialize()
    with postgres_store.transaction() as db:
        assert tuple(
            db.execute(
                "SELECT version,checksum FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
        ) == (version, "0" * 64)


def test_sqlite_import_keeps_capabilities_money_bytes_and_sequence(
    tmp_path, postgres_store, merchant_client
):
    path = tmp_path / "original.sqlite3"
    settings = Settings(_env_file=None)
    with merchant_client(create_app(path, settings=settings)) as old:
        key = old.headers["Authorization"].split(" ", 1)[1]
        identity = old.get("/auth/me").json()
        case, _ = ready(old)
        second = refund_case(old, capture="SECONDCASE")
        prior = old.get(f"/cases/{case}/reconciliation").json()
        token = invite(old)
        assert issue(old, token).status_code == 200
        response = old.post(
            "/customer-portal/evidence",
            content=PDF,
            headers={
                **NO_AUTH,
                "X-Customer-Link": token,
                "X-File-Name": "proof.pdf",
                "Content-Type": "application/pdf",
            },
        )
        assert response.status_code == 201, response.text
        evidence_id = response.json()["id"]
        with old.app.state.store.transaction(write=True) as db:
            db.execute(
                "UPDATE sqlite_sequence SET seq=50 WHERE name='customer_portal_messages'"
            )
    original = sha256(path.read_bytes()).digest()
    counts = migrate(path, postgres_store)
    assert counts["customer_evidence"] == counts["refund_approvals"] == 1
    assert sha256(path.read_bytes()).digest() == original
    with pytest.raises(RuntimeError, match="target is not empty"):
        migrate(path, postgres_store)
    with merchant_client(
        create_app(settings=settings, store=postgres_store), key
    ) as new:
        assert new.get("/auth/me").json() == identity
        assert new.get(f"/cases/{case}/reconciliation").json() == prior
        assert [item["id"] for item in new.get("/cases").json()["items"]] == [
            second,
            case,
        ]
        third = refund_case(new, capture="THIRDCASE")
        assert [item["id"] for item in new.get("/cases").json()["items"]] == [
            third,
            second,
            case,
        ]
        assert buyer_view(new, token).json()["evidence"][0]["id"] == evidence_id
        assert (
            new.post(
                "/customer-portal/evidence/" + evidence_id,
                headers=NO_AUTH,
                json={"token": token},
            ).content
            == PDF
        )
        assert (
            new.post(
                "/customer-portal/messages",
                headers=NO_AUTH,
                json={
                    "token": token,
                    "request_id": str(uuid4()),
                    "body": "Follow-up after migration",
                },
            ).status_code
            == 201
        )
    with postgres_store.transaction() as db:
        assert (
            db.execute("SELECT max(sequence) FROM customer_portal_messages").fetchone()[
                0
            ]
            == 51
        )


def test_two_postgres_api_instances_cannot_submit_the_same_balance(
    postgres_store, merchant_client
):
    cfg = Settings(_env_file=None)
    with merchant_client(create_app(settings=cfg, store=postgres_store)) as first:
        provider = LocalProvider(first.get("/auth/me").json()["id"])
        first.app.state.paypal_client.close()
        first.app.state.paypal_client = provider
        case_id, request = ready(first)
        rival = {**request, "request_id": str(uuid4())}
        key = first.headers["Authorization"].split(" ", 1)[1]
        second_store = PostgresStore(
            SecretStr(os.environ["RESOLVE_TEST_DATABASE_URL"]),
            schema=postgres_store.schema,
        )
        provider.barrier = Barrier(2)
        with merchant_client(
            create_app(settings=cfg, store=second_store), key
        ) as second:
            second.app.state.paypal_client.close()
            second.app.state.paypal_client = provider
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        lambda item: refund(item[0], case_id, item[1]),
                        [(first, request), (second, rival)],
                    )
                )
        assert sorted(r.status_code for r in results) == [201, 409]
        assert len(provider.request_ids) == len(provider.refunds) == 1


def test_postgres_transactions_preserve_snapshot_and_time_out_contended_writer(
    postgres_store,
):
    other = PostgresStore(
        SecretStr(os.environ["RESOLVE_TEST_DATABASE_URL"]),
        schema=postgres_store.schema,
        timeout=0.05,
    )
    with postgres_store.transaction() as snapshot:
        before = snapshot.execute("SELECT count(*) FROM merchants").fetchone()[0]
        other.create_merchant("Concurrent merchant")
        assert (
            snapshot.execute("SELECT count(*) FROM merchants").fetchone()[0] == before
        )
    with postgres_store.transaction(write=True):
        with pytest.raises(StoreError, match="Database is busy") as failure:
            other.create_merchant("Contended merchant")
        assert failure.value.status_code == 503
    assert (
        other.create_merchant("Unblocked merchant").merchant.name
        == "Unblocked merchant"
    )
