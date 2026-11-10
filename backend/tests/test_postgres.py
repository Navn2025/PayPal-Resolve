from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from psycopg import sql
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
        8: "39b5d2b196bec1d1b3a7e15462ed5725f2e0b47a007f932d5186e3b998c8f9b0",
        9: "1cb822a224f21af1f4ddd812c41d2fbed13bf65a330ffc2ed469a496946d0ef9",
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
    for table in ("assurance_events", "assurance_projections", "assurance_receipts", "assurance_refund_traces", "assurance_dispute_events", "assurance_disputes", "assurance_return_reviews", "assurance_return_labels", "assurance_return_guides", "assurance_policies", "aftercare_issues", "aftercare_apps", "platform_packages", "platform_returns", "platform_offers", "platform_alerts", "platform_ticket_messages", "platform_imports", "platform_webhook_jobs", "platform_connections", "platform_sessions", "platform_invites", "platform_staff", "platform_auth_limits", "platform_audit"):
        db.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table)))
    for row in list(db.execute("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname LIKE 'investigate_%'")):
        db.execute(sql.SQL("DROP FUNCTION {}() CASCADE").format(sql.Identifier(row[0])))
    for table in ("investigation_reviews", "investigation_audit", "investigations", "investigation_jobs"):
        db.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table)))
    db.execute("DROP TABLE commerce_orders")
    db.execute("ALTER TABLE merchant_api_keys DROP COLUMN scope")
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
            db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 19
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
            db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 19
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
        owner = old.post("/platform/account/claim", json={
            "email": "import-owner@example.test", "name": "Import owner",
            "password": "synthetic-import-password-123",
        })
        assert owner.status_code == 201, owner.text
        owner_token = owner.json()["token"]
        from test_platform_operations import case as operations_case, promise as operations_promise
        operation_id = operations_case(old, "IMPORT-OPERATIONS")
        commitment = operations_promise(old, operation_id)
        from datetime import datetime, timedelta, timezone
        offer = old.post(f"/platform/cases/{operation_id}/offers", json={
            "choices": [{"promise_id": commitment["id"], "expected_revision": 1}],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        })
        assert offer.status_code == 201, offer.text
        assert old.post("/platform/watchdog/scan").status_code == 200
        synced = old.post("/commerce/orders/sync", json={
            "source": "synthetic-import", "order_reference": "IMPORT-OPERATIONS",
            "revision": 1, "case_id": operation_id,
            "items": [{"product_id": "IMPORT-ITEM", "name": "Synthetic item", "quantity": 1}],
        })
        assert synced.status_code == 200, synced.text
        order = old.get(f"/platform/cases/{operation_id}/returns").json()["orders"][0]
        returned = old.post(f"/platform/cases/{operation_id}/returns", json={
            "request_id": str(uuid4()), "order_id": order["id"],
            "items": [{"product_id": "IMPORT-ITEM", "quantity": 1}], "reason": "Synthetic damage",
        })
        assert returned.status_code == 201, returned.text
        support = old.post("/platform/support-keys", json={"source": "synthetic-import"}).json()
        app_issue = old.post("/aftercare/issues", json={"source": "synthetic-import", "order_reference": "IMPORT-OPERATIONS", "request_id": str(uuid4()), "reason": "damaged_item", "message": "Synthetic imported app support"})
        assert app_issue.status_code == 201, app_issue.text
        guide_root=f"/platform/cases/{operation_id}/returns/{returned.json()['id']}"
        assert old.put(guide_root+"/guide",json={"expected_revision":0,"instructions":"Keep your drop-off receipt","return_address":"Synthetic warehouse","shipping_paid_by":"merchant"}).status_code==200
        import base64
        label_bytes=b"%PDF-1.4\nImported synthetic label\n%%EOF"
        saved_label=old.post(guide_root+"/labels",json={"filename":"import-label.pdf","content_base64":base64.b64encode(label_bytes).decode()})
        assert saved_label.status_code==200,saved_label.text
        journal=old.post("/aftercare/events",json={"source":"synthetic-import"})
        assert journal.status_code==200,journal.text


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
    assert counts["platform_staff"] == counts["platform_sessions"] == 1
    assert counts["aftercare_apps"] == counts["aftercare_issues"] == 1
    assert counts["assurance_return_labels"] == counts["assurance_projections"] == counts["assurance_events"] == 1
    assert counts["platform_returns"] == counts["platform_offers"] == counts["platform_alerts"] == 1
    assert sha256(path.read_bytes()).digest() == original
    with pytest.raises(RuntimeError, match="target is not empty"):
        migrate(path, postgres_store)
    with merchant_client(
        create_app(settings=settings, store=postgres_store), key
    ) as new:
        assert new.get("/auth/me").json() == identity
        imported_support = new.post("/aftercare/status", json={"source": "synthetic-import", "order_reference": "IMPORT-OPERATIONS"}, headers={"Authorization": "Bearer " + support["api_key"]})
        assert imported_support.status_code == 200, imported_support.text
        assert imported_support.json()["issue_count"] == 1
        imported_label=new.post("/aftercare/returns/label",json={"source":"synthetic-import","order_reference":"IMPORT-OPERATIONS","return_id":returned.json()["id"],"label_id":saved_label.json()["id"]},headers={"Authorization":"Bearer "+support["api_key"]})
        assert imported_label.status_code==200,imported_label.text
        assert base64.b64decode(imported_label.json()["content_base64"])==label_bytes
        events=new.post("/aftercare/events",json={"source":"synthetic-import","after_sequence":journal.json()["next_after_sequence"]},headers={"Authorization":"Bearer "+support["api_key"]})
        assert events.status_code==200,events.text


        assert new.get("/platform/me", headers={"Authorization": "Bearer " + owner_token}).json()["role"] == "owner"
        assert new.get(f"/platform/cases/{operation_id}/offers").json()["items"][0] == offer.json()
        assert new.get(f"/platform/cases/{operation_id}/returns").json()["items"][0] == returned.json()
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


def test_pool_reuses_connections_without_leaking_transactions_or_schema(postgres_store):
    from psycopg.errors import ReadOnlySqlTransaction

    store = postgres_store
    with store.transaction(write=True) as db:
        backend = db.execute("SELECT pg_backend_pid()").fetchone()[0]
        db.execute("CREATE TABLE pool_probe (value INTEGER)")
        db.execute("SET LOCAL application_name = 'resolve-synthetic-pool-probe'")
    with pytest.raises(ValueError):
        with store.transaction(write=True) as db:
            assert db.execute("SELECT pg_backend_pid()").fetchone()[0] == backend
            db.execute("INSERT INTO pool_probe VALUES (1)")
            raise ValueError("rollback synthetic update")
    with store.transaction() as db:
        assert db.execute("SELECT pg_backend_pid()").fetchone()[0] == backend
        assert db.execute("SELECT current_schema()").fetchone()[0] == store.schema
        assert db.execute("SELECT current_setting('transaction_read_only')").fetchone()[0] == "on"
        assert db.execute("SELECT current_setting('application_name')").fetchone()[0] != "resolve-synthetic-pool-probe"
        assert db.execute("SELECT count(*) FROM pool_probe").fetchone()[0] == 0
    with pytest.raises(ReadOnlySqlTransaction):
        with store.transaction() as db:
            db.execute("INSERT INTO pool_probe VALUES (2)")
    with store.transaction(write=True) as db:
        db.execute("INSERT INTO pool_probe VALUES (3)")
    with store.transaction() as db:
        assert db.execute("SELECT value FROM pool_probe").fetchone()[0] == 3


def test_pool_discards_a_broken_connection_and_reopens_after_close(postgres_store):
    store = postgres_store
    with pytest.raises(StoreError) as error:
        with store.transaction() as db:
            old_backend = db.execute("SELECT pg_backend_pid()").fetchone()[0]
            db.raw.close()
            db.execute("SELECT 1")
    assert error.value.status_code == 503
    with store.transaction() as db:
        assert db.execute("SELECT pg_backend_pid()").fetchone()[0] != old_backend
    store.close()
    with store.transaction() as db:
        assert db.execute("SELECT current_schema()").fetchone()[0] == store.schema
