from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.settings import Settings


BASE = "/resolution-cases"
CASE = {
    "external_reference": "ORDER-1042",
    "title": "Refund inquiry",
    "order_reference": "ORDER-1042",
}
LINK = {"kind": "paypal_capture", "reference": "SIMHSDK1042"}
APPROVAL = {
    "source": "checkout",
    "source_event_id": "approved-1042",
    "evidence_type": "refund_approved",
    "occurred_at": "2026-11-07T11:00:00Z",
    "summary": "Private merchant record",
    "amount": "25.00",
    "currency": "USD",
}


def test_evidence_retries_serialize_and_keep_the_provider_check_read_only(client):
    client.app.state.paypal_client.settings = Settings(
        _env_file=None, paypal_sandbox_enabled=False
    )

    def pair(path, payload):
        start = Barrier(2)

        def send(_):
            start.wait(timeout=5)
            return client.post(path, json=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            left, right = pool.map(send, range(2))
        assert left.status_code == right.status_code == 200, (left.text, right.text)
        assert left.json()["id"] == right.json()["id"]
        return left.json()["id"]

    case = BASE + "/" + pair(BASE + "/upsert", CASE)
    pair(case + "/evidence/records", LINK)
    pair(case + "/evidence/events", APPROVAL)
    assert (
        client.post(
            case + "/evidence/events", json={**APPROVAL, "summary": "different"}
        ).status_code
        == 409
    )
    refresh = client.post(case + "/evidence/refresh").json()
    assert refresh["verified"] == []
    assert any(item["status"] == "unavailable" for item in refresh["issues"])
    bundle = client.get(case + "/evidence-bundle").json()
    assert len(bundle["linked_records"]) == 1
    assert [item["event_type"] for item in bundle["timeline"]["items"]] == [
        "merchant_evidence",
        "case_created",
    ]
    assert [
        item["kind"] for item in bundle["case"]["evidence_summary"]["issues"]
    ].count("refund_confirmation") == 1
    assert bundle["case"]["refund_case_id"] is None
    with client.app.state.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM refund_approvals").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"amount": "-25"},
        {"amount": "25.001"},
        {"currency": "EUR"},
        {"occurred_at": "2026-11-07T11:00:00"},
    ],
)
def test_approval_uses_existing_money_and_timezone_validation(client, bad):
    case = BASE + "/" + client.post(BASE + "/upsert", json=CASE).json()["id"]
    assert (
        client.post(case + "/evidence/events", json={**APPROVAL, **bad}).status_code
        == 422
    )
