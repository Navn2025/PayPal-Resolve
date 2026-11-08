from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

from app.settings import Settings

SYNC = "/commerce/orders/sync"
ORDER = {
    "source": "test-checkout",
    "order_reference": "ORDER-2042",
    "revision": 1,
    "order_status": "shipped",
    "customer_reference": "CUS-2042",
    "payment": {
        "paypal_order_id": "SIMORDERSIMHSDK2042",
        "paypal_capture_id": "SIMHSDK2042",
        "currency": "USD",
        "status": "completed",
        "captured_amount": "100",
        "refunded_amount": "0",
    },
    "items": [
        {
            "product_id": "ITEM-42",
            "name": "Sample product",
            "quantity": 2,
            "unit_amount": "50",
        }
    ],
}
CONTACT = {
    "name": "Buyer Test",
    "email": "buyer-2042@example.test",
    "phone": "+15550102042",
}


def access(key):
    return {"Authorization": f"Bearer {key.api_key}"}


def test_commerce_sync_retries_and_refuses_stale_or_conflicting_updates(client):
    start = Barrier(2)

    def sync(_):
        start.wait(timeout=5)
        return client.post(SYNC, json=ORDER)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, retry = pool.map(sync, range(2))
    assert first.status_code == retry.status_code == 200, (first.text, retry.text)
    assert first.json() == retry.json()
    base = f"/resolution-cases/{first.json()['case_id']}"
    assert (
        client.post(SYNC, json={**ORDER, "order_status": "cancelled"}).status_code
        == 409
    )
    assert (
        client.post(
            SYNC,
            json={
                **ORDER,
                "revision": 2,
                "payment": {**ORDER["payment"], "paypal_capture_id": "BAD"},
            },
        ).status_code
        == 409
    )
    assert client.get(base + "/commerce").json()["app"]["revision"] == 1
    updated = client.post(
        SYNC, json={**ORDER, "revision": 2, "order_status": "delivered"}
    )
    assert updated.status_code == 200
    assert updated.json()["case_id"] == first.json()["case_id"]
    assert client.post(SYNC, json=ORDER).status_code == 409
    bundle = client.get(base + "/evidence-bundle").json()
    assert bundle["commerce"]["app"]["order_status"] == "delivered"
    assert [
        item["data"]["revision"]
        for item in bundle["timeline"]["items"]
        if item["data"].get("evidence_type") == "commerce_snapshot"
    ] == [2, 1]
    assert len(bundle["linked_records"]) == 2


def test_commerce_key_contacts_tenant_scope_and_validation(client):
    store = client.app.state.store
    merchant = UUID(client.get("/auth/me").json()["id"])
    key = store.issue_key(merchant, scope="commerce")
    other = store.create_merchant("Other merchant")
    headers = access(key)
    private = {**ORDER, "contact": CONTACT}
    result = client.post(SYNC, headers=headers, json=private)
    assert result.status_code == 200, result.text
    path = f"/resolution-cases/{result.json()['case_id']}"
    for denied in (
        "/auth/me",
        path,
        path + "/commerce/contact",
        path + "/evidence-bundle",
    ):
        assert client.get(denied, headers=headers).status_code == 401
    assert (
        client.post("/merchant-auth/session/key", json={"key": key.api_key}).status_code
        == 401
    )
    for denied in (
        path + "/customer-link",
        path + "/evidence/refresh",
        "/cases/11111111-1111-4111-8111-111111111111/refund-executions",
    ):
        assert client.post(denied, headers=headers, json={}).status_code == 401
    result = client.get(path + "/commerce", headers=headers)
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "private, no-store"
    assert result.json()["status"] == "incomplete"
    assert CONTACT["email"] not in result.text
    assert CONTACT["email"] not in client.get(path + "/evidence-bundle").text
    assert CONTACT["email"] not in client.get(path + "/timeline").text
    assert client.get(path + "/commerce/contact").json() == CONTACT
    for method, route in (
        ("GET", "/commerce"),
        ("GET", "/commerce/contact"),
        ("POST", "/commerce/refresh"),
    ):
        assert (
            client.request(method, path + route, headers=access(other)).status_code
            == 404
        )
    assert (
        client.post(
            SYNC,
            headers=access(other),
            json={**ORDER, "case_id": path.rsplit("/", 1)[1]},
        ).status_code
        == 404
    )
    assert (
        client.post(SYNC, headers=access(other), json=ORDER).json()["case_id"]
        != path.rsplit("/", 1)[1]
    )

    issued = client.post(path + "/customer-link", json={}).json()
    buyer = client.post("/customer-portal/view", json={"token": issued["token"]})
    assert buyer.status_code == 200
    for private_value in (
        CONTACT["email"],
        CONTACT["phone"],
        "CUS-2042",
        "ITEM-42",
        "SIMHSDK2042",
    ):
        assert private_value not in buyer.text
    bad = client.post(
        SYNC,
        headers=headers,
        json={**ORDER, "contact": {**CONTACT, "password_hash": "never-echo-or-store"}},
    )
    assert bad.status_code == 422 and "never-echo-or-store" not in bad.text
    oversized = client.post(
        SYNC,
        headers={**headers, "Content-Type": "application/json"},
        content=" " * (32 * 1024 + 1),
    )
    assert oversized.status_code == 413

    # Contacts are latest-only. Omitting them on a higher revision removes them.
    assert (
        client.post(SYNC, headers=headers, json={**ORDER, "revision": 2}).status_code
        == 200
    )
    assert client.get(path + "/commerce/contact").status_code == 404
    store.revoke_key(key.key_id)
    assert client.get(path + "/commerce", headers=headers).status_code == 401


def test_attach_is_atomic_and_preserves_existing_case_links(client):
    client.app.state.paypal_client.settings = Settings(
        _env_file=None, paypal_sandbox_enabled=False
    )
    base = "/resolution-cases"
    case = client.post(
        base,
        json={
            "title": "Existing support issue",
            "order_reference": ORDER["order_reference"],
        },
    ).json()["id"]
    path = base + "/" + case
    linked = client.post(
        path + "/evidence/records",
        json={
            "kind": "paypal_capture",
            "reference": ORDER["payment"]["paypal_capture_id"],
            "source": "support",
        },
    )
    assert linked.status_code == 200
    wrong = {
        **ORDER,
        "case_id": case,
        "payment": {**ORDER["payment"], "paypal_capture_id": "WRONG"},
    }
    assert client.post(SYNC, json=wrong).status_code == 409
    assert client.get(path + "/commerce").status_code == 404
    assert len(client.get(path + "/evidence-bundle").json()["linked_records"]) == 1
    fixed = client.post(SYNC, json={**ORDER, "case_id": case})
    assert fixed.status_code == 200 and fixed.json()["case_id"] == case
    refresh = client.post(path + "/commerce/refresh").json()
    assert refresh["status"] == "incomplete"
    assert refresh["last_checked_at"]
    assert all(check["status"] == "unverified" for check in refresh["checks"])
    assert refresh["provider_issues"]


def test_refresh_started_before_new_revision_does_not_verify_it(client, monkeypatch):
    from app import evidence_workspace

    entered = Event()
    resume = Event()

    def provider(*args):
        entered.set()
        assert resume.wait(timeout=10)
        return (
            [
                {
                    "kind": "paypal_capture",
                    "reference": ORDER["payment"]["paypal_capture_id"],
                    "status": "COMPLETED",
                    "currency": "USD",
                    "amount": "100.00",
                }
            ],
            [],
            False,
        )

    monkeypatch.setattr(evidence_workspace, "collect_paypal", provider)
    case_id = client.post(SYNC, json=ORDER).json()["case_id"]
    path = f"/resolution-cases/{case_id}/commerce"
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(client.post, path + "/refresh")
        try:
            assert entered.wait(timeout=10)
            update = client.post(SYNC, json={**ORDER, "revision": 2})
            assert update.status_code == 200
        finally:
            resume.set()
        report = pending.result(timeout=10).json()
    assert report["app"]["revision"] == 2
    assert all(item["status"] == "unverified" for item in report["checks"])
    assert report["provider_issues"][0]["kind"] == "provider_refresh"
    retained = client.get(f"/resolution-cases/{case_id}").json()["evidence_summary"]
    assert retained["verified"][0]["reference"] == ORDER["payment"]["paypal_capture_id"]


def test_order_catalog_is_separate_scoped_and_retry_safe(client):
    store = client.app.state.store
    merchant = UUID(client.get("/auth/me").json()["id"])
    key = store.issue_key(merchant, scope="commerce")
    other = store.create_merchant("Other catalog")
    register = "/commerce/orders/register"
    orders = "/commerce/orders"
    initial_cases = client.get("/resolution-cases").json()["total"]
    assert client.get(orders, headers=access(key)).status_code == 401
    first = client.post(
        register, headers=access(key), json={**ORDER, "contact": CONTACT}
    )
    assert first.status_code == 200, first.text
    imported = first.json()
    assert imported["case_id"] is None
    assert (
        client.post(
            register, headers=access(key), json={**ORDER, "contact": CONTACT}
        ).json()
        == imported
    )
    assert (
        client.post(
            register, headers=access(key), json={**ORDER, "order_status": "changed"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            register,
            headers=access(key),
            json={
                "source": "second-shop",
                "order_reference": "UNPAID-41",
                "revision": 1,
                "order_status": "created",
            },
        ).status_code
        == 200
    )
    assert client.get("/resolution-cases").json()["total"] == initial_cases
    page = client.get(orders, params={"limit": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    next_page = client.get(orders, params={"limit": 1, "offset": 1}).json()
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    assert (
        client.get(orders, params={"q": ORDER["payment"]["paypal_capture_id"]}).json()[
            "items"
        ][0]["id"]
        == imported["id"]
    )
    assert client.get(orders, params={"source": ORDER["source"]}).json()["total"] == 1
    assert client.get(orders, params={"q": "%"}).json()["total"] == 0
    detail = orders + "/" + imported["id"]
    assert (
        client.get(detail).json()["app"]["items"][0]["name"]
        == ORDER["items"][0]["name"]
    )
    assert CONTACT["email"] not in client.get(detail).text
    assert CONTACT["email"] not in client.get(orders).text
    assert client.get(orders, headers=access(other)).json()["total"] == 0
    assert client.get(detail, headers=access(other)).status_code == 404
    assert client.post(detail + "/case", headers=access(other)).status_code == 404
    assert client.post(detail + "/case", headers=access(key)).status_code == 401
    start = Barrier(2)

    def open_case(_):
        start.wait(timeout=5)
        return client.post(detail + "/case")

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = pool.map(open_case, range(2))
    assert left.status_code == right.status_code == 200
    case_id = left.json()["case_id"]
    assert case_id and case_id == right.json()["case_id"]
    legacy = client.post(SYNC, json={**ORDER, "contact": CONTACT}).json()
    assert legacy["case_id"] == case_id
    assert client.get("/resolution-cases").json()["total"] == initial_cases + 1
    bundle = client.get(f"/resolution-cases/{case_id}/evidence-bundle").json()
    assert bundle["commerce"]["app"]["order_reference"] == ORDER["order_reference"]
    assert (
        len(
            [
                event
                for event in bundle["timeline"]["items"]
                if event["data"].get("evidence_type") == "commerce_snapshot"
            ]
        )
        == 1
    )
    assert len(bundle["linked_records"]) == 2
    assert client.get(f"/resolution-cases/{case_id}/commerce/contact").json() == CONTACT


def test_legacy_snapshot_is_preserved_in_the_order_catalog(tmp_path, merchant_client):
    import json
    import sqlite3
    from hashlib import sha256
    from pathlib import Path
    from uuid import uuid4

    from app.main import create_app

    path = tmp_path / "orders-v19.sqlite3"
    merchant_id, case_id = str(uuid4()), str(uuid4())
    timestamp = "2026-11-07T10:00:00.000000+00:00"
    token = "rslv_" + "a" * 43
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    with sqlite3.connect(path) as db:
        for migration in sorted(migrations.glob("*.sql"))[:19]:
            db.executescript(migration.read_text(encoding="utf-8"))
        db.execute("PRAGMA user_version=19")
        db.execute(
            "INSERT INTO merchants VALUES (?,?,?)",
            (merchant_id, "Legacy store", timestamp),
        )
        db.execute(
            "INSERT INTO merchant_api_keys (id,merchant_id,token_hash,created_at) VALUES (?,?,?,?)",
            (str(uuid4()), merchant_id, sha256(token.encode()).hexdigest(), timestamp),
        )
        db.execute(
            "INSERT INTO resolution_cases VALUES (?,?,?,?,?,?)",
            (
                case_id,
                merchant_id,
                None,
                "Legacy case",
                ORDER["order_reference"],
                timestamp,
            ),
        )
        db.execute(
            "INSERT INTO commerce_order_snapshots VALUES (?,?,?,?,?,?,?,?)",
            (
                case_id,
                merchant_id,
                ORDER["source"],
                ORDER["order_reference"],
                1,
                json.dumps(ORDER),
                json.dumps(CONTACT),
                timestamp,
            ),
        )
    with merchant_client(create_app(path), token) as client:
        page = client.get("/commerce/orders").json()
        assert page["total"] == 1
        assert page["items"][0]["case_id"] == case_id
        assert page["items"][0]["id"] == case_id
        assert (
            client.get(f"/resolution-cases/{case_id}/commerce/contact").json()
            == CONTACT
        )
