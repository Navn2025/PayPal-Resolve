from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

import pytest


@pytest.fixture
def case_payload():
    return {
        "order_id": "ORDER-001",
        "complaint": "Only part of my agreed refund arrived.",
        "payment": {
            "capture_id": "DEMO-CAPTURE-001",
            "captured_amount": "100.00",
        },
        "commitment": {
            "amount": "100.00",
            "source_message": "We agree to refund the full $100.",
            "status": "accepted",
        },
    }


@pytest.fixture
def case_id(client, case_payload):
    response = client.post("/cases", json=case_payload)
    assert response.status_code == 201
    return response.json()["id"]


def refund_body(amount="20.00", status="completed", refund_id="REFUND-001"):
    return {
        "refund_id": refund_id,
        "capture_id": "DEMO-CAPTURE-001",
        "amount": amount,
        "currency": "USD",
        "status": status,
    }


def record(client, case_id, **kwargs):
    return client.post(f"/cases/{case_id}/refunds", json=refund_body(**kwargs))


def summary(client, case_id):
    response = client.get(f"/cases/{case_id}/reconciliation")
    assert response.status_code == 200
    return response.json()


def test_partial_refund_recommends_only_the_outstanding_amount(client, case_id):
    assert record(client, case_id).status_code == 201
    result = summary(client, case_id)

    assert result["committed_amount"] == "100.00"
    assert result["completed_refund_amount"] == "20.00"
    assert result["pending_refund_amount"] == "0.00"
    assert result["outstanding_commitment_amount"] == "80.00"
    assert result["uncovered_commitment_amount"] == "80.00"
    assert result["remaining_refundable_amount"] == "80.00"
    assert result["recommended_refund_amount"] == "80.00"
    assert result["status"] == "refund_required"
    assert result["next_action"] == "request_merchant_approval"
    assert result["verified_with_paypal"] is False


def test_pending_refund_blocks_another_recommendation_until_it_fails(client, case_id):
    record(client, case_id)
    assert record(
        client, case_id, amount="80.00", status="pending", refund_id="REFUND-002"
    ).status_code == 201

    result = summary(client, case_id)
    assert result["status"] == "refund_pending"
    assert result["outstanding_commitment_amount"] == "80.00"
    assert result["uncovered_commitment_amount"] == "0.00"
    assert result["remaining_refundable_amount"] == "0.00"
    assert result["recommended_refund_amount"] == "0.00"

    updated = client.patch(
        f"/cases/{case_id}/refunds/REFUND-002", json={"status": "failed"}
    )
    assert updated.status_code == 200
    result = summary(client, case_id)
    assert result["failed_refund_amount"] == "80.00"
    assert result["remaining_refundable_amount"] == "80.00"
    assert result["recommended_refund_amount"] == "80.00"

    assert record(
        client, case_id, amount="80.00", refund_id="REFUND-003"
    ).status_code == 201
    result = summary(client, case_id)
    assert result["status"] == "fulfilled"
    assert result["outstanding_commitment_amount"] == "0.00"
    assert result["recommended_refund_amount"] == "0.00"
    assert result["next_action"] == "none"
    # Reconciliation reports an outcome; it does not close a case or change its agreement.
    stored = client.get(f"/cases/{case_id}").json()
    assert stored["status"] == "open"
    assert stored["commitment"]["status"] == "accepted"


def test_partial_pending_amount_still_blocks_a_new_recommendation(client, case_id):
    record(client, case_id)
    record(client, case_id, amount="40.00", status="pending", refund_id="REFUND-002")

    result = summary(client, case_id)
    assert result["outstanding_commitment_amount"] == "80.00"
    assert result["uncovered_commitment_amount"] == "40.00"
    assert result["remaining_refundable_amount"] == "40.00"
    assert result["recommended_refund_amount"] == "0.00"
    assert result["next_action"] == "monitor_pending_refund"


def test_pending_completion_fulfills_without_double_counting(client, case_id):
    record(client, case_id, amount="100.00", status="pending")
    response = client.patch(
        f"/cases/{case_id}/refunds/REFUND-001", json={"status": "completed"}
    )
    assert response.status_code == 200

    result = summary(client, case_id)
    assert result["completed_refund_amount"] == "100.00"
    assert result["pending_refund_amount"] == "0.00"
    assert result["remaining_refundable_amount"] == "0.00"
    assert result["status"] == "fulfilled"
    assert len(client.get(f"/cases/{case_id}/refunds").json()) == 1


def test_identical_refund_replay_is_idempotent(client, case_id):
    assert record(client, case_id).status_code == 201
    assert record(client, case_id).status_code == 200
    assert summary(client, case_id)["completed_refund_amount"] == "20.00"
    assert len(client.get(f"/cases/{case_id}/refunds").json()) == 1


@pytest.mark.parametrize(("field", "value"), [("amount", "30.00"), ("status", "pending")])
def test_conflicting_refund_id_cannot_overwrite_existing_data(client, case_id, field, value):
    record(client, case_id)
    body = refund_body()
    body[field] = value
    assert client.post(f"/cases/{case_id}/refunds", json=body).status_code == 409
    assert summary(client, case_id)["completed_refund_amount"] == "20.00"


@pytest.mark.parametrize("initial_status", ["completed", "failed"])
def test_terminal_refund_status_cannot_be_reopened(client, case_id, initial_status):
    record(client, case_id, status=initial_status)
    assert client.patch(
        f"/cases/{case_id}/refunds/REFUND-001", json={"status": "pending"}
    ).status_code == 409
    assert client.patch(
        f"/cases/{case_id}/refunds/REFUND-001", json={"status": initial_status}
    ).status_code == 200


@pytest.mark.parametrize("new_status", ["pending", "completed"])
def test_recorded_refunds_cannot_exceed_capture_balance(client, case_id, new_status):
    record(client, case_id, amount="60.00", status="pending")
    assert record(
        client, case_id, amount="50.00", status=new_status, refund_id="REFUND-002"
    ).status_code == 409
    assert len(client.get(f"/cases/{case_id}/refunds").json()) == 1


def test_condition_requires_evidence_and_history_is_preserved(client, case_payload):
    case_payload["commitment"]["condition"] = "Return must be received"
    case_id = client.post("/cases", json=case_payload).json()["id"]
    record(client, case_id)

    result = summary(client, case_id)
    assert result["status"] == "awaiting_condition"
    assert result["recommended_refund_amount"] == "0.00"
    assert result["condition_check"] is None

    url = f"/cases/{case_id}/condition-checks"
    assert client.post(url, json={"status": "met", "evidence_note": "  "}).status_code == 422
    assert client.get(url).json() == []
    assert client.post(
        url, json={"status": "not_met", "evidence_note": "Return has not arrived."}
    ).status_code == 201
    assert summary(client, case_id)["recommended_refund_amount"] == "0.00"

    response = client.post(
        url, json={"status": "met", "evidence_note": "Warehouse receipt RETURN-001."}
    )
    assert response.status_code == 201
    assert datetime.fromisoformat(response.json()["recorded_at"]).tzinfo is not None
    result = summary(client, case_id)
    assert result["status"] == "refund_required"
    assert result["recommended_refund_amount"] == "80.00"
    assert result["condition_check"]["evidence_note"] == "Warehouse receipt RETURN-001."
    assert [check["status"] for check in client.get(url).json()] == ["not_met", "met"]

    # A later negative check must block the recommendation again.
    client.post(url, json={"status": "not_met", "evidence_note": "Receipt was corrected."})
    assert summary(client, case_id)["recommended_refund_amount"] == "0.00"


@pytest.mark.parametrize("commitment", [None, "proposed"])
def test_missing_or_unaccepted_commitment_cannot_recommend_refund(
    client, case_payload, commitment
):
    if commitment is None:
        case_payload.pop("commitment")
    else:
        case_payload["commitment"]["status"] = "proposed"
    case_id = client.post("/cases", json=case_payload).json()["id"]

    result = summary(client, case_id)
    assert result["recommended_refund_amount"] == "0.00"
    assert result["status"] == (
        "no_commitment" if commitment is None else "awaiting_acceptance"
    )
    if commitment is None:
        assert result["committed_amount"] is None
        assert result["outstanding_commitment_amount"] is None
        assert result["uncovered_commitment_amount"] is None


def test_cases_sharing_capture_share_ledger_and_balance(client, case_id, case_payload):
    record(client, case_id, amount="80.00")
    second_id = client.post("/cases", json=case_payload).json()["id"]

    result = summary(client, second_id)
    assert result["completed_refund_amount"] == "80.00"
    assert result["remaining_refundable_amount"] == "20.00"
    assert record(
        client, second_id, amount="30.00", refund_id="REFUND-002"
    ).status_code == 409
    assert record(client, second_id, amount="80.00").status_code == 200
    assert len(client.get(f"/cases/{second_id}/refunds").json()) == 1


def test_capture_cannot_be_reintroduced_with_a_different_balance(client, case_id, case_payload):
    case_payload["payment"]["captured_amount"] = "200.00"
    assert client.post("/cases", json=case_payload).status_code == 409


def test_other_captures_are_isolated_and_refund_ids_cannot_be_reused(
    client, case_id, case_payload
):
    record(client, case_id)
    case_payload["payment"]["capture_id"] = "OTHER-CAPTURE"
    other_id = client.post("/cases", json=case_payload).json()["id"]
    assert client.get(f"/cases/{other_id}/refunds").json() == []
    assert summary(client, other_id)["completed_refund_amount"] == "0.00"
    assert client.patch(
        f"/cases/{other_id}/refunds/REFUND-001", json={"status": "failed"}
    ).status_code == 404

    body = refund_body()
    body["capture_id"] = "OTHER-CAPTURE"
    assert client.post(f"/cases/{other_id}/refunds", json=body).status_code == 409


@pytest.mark.parametrize(
    ("field", "value", "expected_status"),
    [
        ("capture_id", "WRONG-CAPTURE", 409),
        ("amount", "101.00", 409),
        ("amount", "0.00", 422),
        ("amount", "-1.00", 422),
        ("amount", "0.001", 422),
        ("amount", "NaN", 422),
        ("currency", "EUR", 422),
        ("refund_id", "   ", 422),
        ("status", "unknown", 422),
    ],
)
def test_invalid_refund_observation_leaves_ledger_unchanged(
    client, case_id, field, value, expected_status
):
    body = refund_body()
    body[field] = value
    assert client.post(f"/cases/{case_id}/refunds", json=body).status_code == expected_status
    assert client.get(f"/cases/{case_id}/refunds").json() == []


def test_status_update_cannot_change_refund_amount(client, case_id):
    record(client, case_id, status="pending")
    assert client.patch(
        f"/cases/{case_id}/refunds/REFUND-001",
        json={"status": "completed", "amount": "100.00"},
    ).status_code == 422
    assert summary(client, case_id)["pending_refund_amount"] == "20.00"


def test_condition_checks_require_an_existing_condition(client, case_id):
    assert client.post(
        f"/cases/{case_id}/condition-checks",
        json={"status": "met", "evidence_note": "No actual condition exists."},
    ).status_code == 409


def test_cent_reconciliation_is_exact_and_never_recommends_negative_amounts(client, case_payload):
    case_payload["payment"]["captured_amount"] = "0.30"
    case_payload["commitment"]["amount"] = "0.20"
    case_id = client.post("/cases", json=case_payload).json()["id"]
    record(client, case_id, amount="0.10")
    assert summary(client, case_id)["recommended_refund_amount"] == "0.10"
    record(client, case_id, amount="0.20", refund_id="REFUND-002")
    result = summary(client, case_id)
    assert result["completed_refund_amount"] == "0.30"
    assert result["outstanding_commitment_amount"] == "0.00"
    assert result["recommended_refund_amount"] == "0.00"


def test_concurrent_records_cannot_reserve_the_same_balance_twice(client, case_id):
    def submit(refund_id):
        return record(client, case_id, amount="60.00", status="pending", refund_id=refund_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, ["REFUND-001", "REFUND-002"]))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert summary(client, case_id)["pending_refund_amount"] == "60.00"


@pytest.mark.parametrize("path", ["refunds", "condition-checks", "reconciliation"])
def test_unknown_case_has_no_access_to_ledger_or_reconciliation(client, path):
    assert client.get(f"/cases/{uuid4()}/{path}").status_code == 404


def test_unknown_refund_cannot_be_updated(client, case_id):
    assert client.patch(
        f"/cases/{case_id}/refunds/UNKNOWN", json={"status": "completed"}
    ).status_code == 404
