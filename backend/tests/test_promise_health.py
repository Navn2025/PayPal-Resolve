"""Broken-promise detector. All data is synthetic; PayPal refunds are simulated through the
store's own provider-refund recorder, never a network call."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.paypal import PayPalRefundDetails
from app.promise_health import PromiseHealthCheck, classify, suggested_refund
from app.settings import Settings

D = Decimal
PAST = (datetime.now(UTC) - timedelta(days=1)).isoformat()


def payment_case(client, capture, goal="100.00", status="accepted"):
    response = client.post("/cases", json={
        "order_id": "ORDER" + capture, "complaint": "Promise health test",
        "payment": {"capture_id": capture, "captured_amount": "100.00"},
        "commitment": {"amount": goal, "status": status, "source_message": "Agreed refund"},
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def resolution(client, refund_case, amount="100.00", **fields):
    case = client.post("/resolution-cases", json={
        "title": "Refund " + amount, "order_reference": "ORD", "refund_case_id": refund_case})
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    promise = client.post(f"/resolution-cases/{case_id}/promises", json={
        "promise": f"Refund ${amount}", "source_note": "Support chat",
        "target": {"kind": "refund", "amount": amount}, **fields})
    assert promise.status_code == 201, promise.text
    return case_id


def paypal_refund(client, refund_case, refund_id, amount, status="COMPLETED"):
    """Simulated PayPal evidence, recorded the way a verified provider refund is stored."""
    store = client.app.state.store
    with store.transaction(write=True) as connection:
        merchant = connection.execute("SELECT merchant_id FROM cases WHERE id=?", (refund_case,)).fetchone()[0]
        case = store._require_case(connection, UUID(refund_case), UUID(str(merchant)))
        store._record_provider_refund(connection, case, PayPalRefundDetails(
            id=refund_id, amount={"value": amount, "currency_code": "USD"}, status=status, links=[]))


def health(client, case_id):
    response = client.get(f"/resolution-cases/{case_id}/promise-health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overdue_after_days"] == 3
    return body["items"]


# Pure rules

@pytest.mark.parametrize(("promised", "refunded", "overdue", "expected"), [
    ("100", "100", False, "kept"), ("100", "100", True, "kept"), ("100", "120", True, "kept"),
    ("100", "20", False, "partially_kept"), ("100", "0", False, "at_risk"),
    ("100", "20", True, "at_risk"), ("100", "0", True, "broken"),
])
def test_classification_rules(promised, refunded, overdue, expected):
    assert classify(D(promised), D(refunded), overdue) == expected


def test_suggestion_never_exceeds_promise_captured_or_pays_twice():
    assert suggested_refund(D("100"), D("20"), D("20"), D("0"), D("100")) == D("80")
    # A pending refund is not suggested again.
    assert suggested_refund(D("100"), D("20"), D("20"), D("30"), D("100")) == D("50")
    # A refund recorded outside PayPal confirmation still counts as paid.
    assert suggested_refund(D("100"), D("0"), D("90"), D("0"), D("100")) == D("10")
    # Never above what is left of the capture, even if the promise is larger.
    assert suggested_refund(D("150"), D("0"), D("0"), D("0"), D("100")) == D("100")
    assert suggested_refund(D("100"), D("120"), D("120"), D("0"), D("120")) == D("0")


def test_overdue_threshold_comes_from_the_environment(monkeypatch):
    assert Settings(_env_file=None).promise_overdue_days == 3
    monkeypatch.setenv("RESOLVE_PROMISE_OVERDUE_DAYS", "7")
    assert Settings(_env_file=None).promise_overdue_days == 7


# Through the API and the real reconciliation

def test_kept_promise(client):
    refund = payment_case(client, "PHKEPT")
    case_id = resolution(client, refund)
    paypal_refund(client, refund, "RKEPT1", "100.00")
    [item] = health(client, case_id)
    assert item["status"] == "kept"
    assert (item["refunded_amount"], item["remaining_amount"], item["suggested_refund_amount"]) == ("100.00", "0.00", "0.00")


def test_partial_refund_before_the_deadline(client):
    refund = payment_case(client, "PHPART")
    case_id = resolution(client, refund)
    paypal_refund(client, refund, "RPART1", "20.00")
    [item] = health(client, case_id)
    assert item["status"] == "partially_kept"
    assert item["overdue"] is False and item["days_since_promise"] == 0
    assert (item["promised_amount"], item["refunded_amount"], item["remaining_amount"]) == ("100.00", "20.00", "80.00")
    assert item["suggested_refund_amount"] == "80.00"
    # The suggestion matches the server's own cap: above it is refused, exactly it is accepted.
    state = client.get(f"/cases/{refund}/reconciliation").json()
    assert state["status"] == "refund_required" and state["recommended_refund_amount"] == "80.00"
    def approve(amount, request_id):
        return client.post(f"/cases/{refund}/refund-approvals", json={
            "request_id": request_id, "capture_id": "PHPART", "amount": amount,
            "decision_note": "Refund the rest", "state_fingerprint": state["state_fingerprint"]})
    assert approve("80.01", "22222222-2222-4222-8222-222222222222").status_code == 409
    assert approve("80.00", "33333333-3333-4333-8333-333333333333").status_code == 201


def test_partial_refund_past_the_threshold_is_at_risk(client):
    refund = payment_case(client, "PHLATE")
    case_id = resolution(client, refund)
    paypal_refund(client, refund, "RLATE1", "20.00")
    store = client.app.state.store
    with store.transaction() as connection:
        merchant = connection.execute("SELECT merchant_id FROM resolution_cases WHERE id=?", (case_id,)).fetchone()[0]
    later = datetime.now(UTC) + timedelta(days=4, minutes=1)
    [item] = PromiseHealthCheck(store, 3, now=later).for_case(UUID(case_id), UUID(str(merchant))).items
    assert item.status == "at_risk" and item.overdue and item.days_since_promise == 4
    assert item.remaining_amount == D("80.00")
    # One day under a longer configured threshold it is still only partially kept.
    [item] = PromiseHealthCheck(store, 5, now=later).for_case(UUID(case_id), UUID(str(merchant))).items
    assert item.status == "partially_kept"


def test_nothing_refunded_after_the_due_date_is_broken(client):
    refund = payment_case(client, "PHBROKE")
    case_id = resolution(client, refund, due_at=PAST)
    [item] = health(client, case_id)
    assert item["status"] == "broken" and item["overdue"] is True
    assert item["remaining_amount"] == "100.00" and item["suggested_refund_amount"] == "100.00"


def test_over_refund_is_never_suggested_and_the_approval_cap_still_holds(client):
    refund = payment_case(client, "PHOVER")
    case_id = resolution(client, refund)
    # 90.00 recorded outside PayPal confirmation: PayPal shows 0 refunded, but only 10.00 may be suggested.
    manual = client.post(f"/cases/{refund}/refunds", json={
        "refund_id": "MANUALOVER", "capture_id": "PHOVER", "amount": "90.00", "currency": "USD", "status": "completed"})
    assert manual.status_code == 201, manual.text
    [item] = health(client, case_id)
    assert item["refunded_amount"] == "0.00" and item["ledger_ahead_of_provider"] is True
    assert item["suggested_refund_amount"] == "10.00"
    state = client.get(f"/cases/{refund}/reconciliation").json()
    over = client.post(f"/cases/{refund}/refund-approvals", json={
        "request_id": "11111111-1111-4111-8111-111111111111", "capture_id": "PHOVER", "amount": "100.00",
        "decision_note": "Try to refund the whole promise", "state_fingerprint": state["state_fingerprint"]})
    assert over.status_code == 409


def test_unaccepted_or_unlinked_promises_are_not_assessed(client):
    refund = payment_case(client, "PHPROPOSED", status="proposed")
    assert health(client, resolution(client, refund)) == []
    unlinked = client.post("/resolution-cases", json={"title": "No payment"}).json()["id"]
    assert health(client, unlinked) == []
    assert client.get("/resolution-cases/00000000-0000-4000-8000-000000000000/promise-health").status_code == 404


def test_merchant_list_shows_only_at_risk_and_broken_largest_amount_first(client):
    kept = payment_case(client, "PHLKEPT")
    resolution(client, kept)
    paypal_refund(client, kept, "RLKEPT", "100.00")
    partial = payment_case(client, "PHLPART")
    partial_case = resolution(client, partial)
    paypal_refund(client, partial, "RLPART", "60.00")  # partially kept: not listed
    risky = payment_case(client, "PHLRISK", goal="30.00")
    risky_case = resolution(client, risky, amount="30.00")  # nothing yet, within the window
    broken = payment_case(client, "PHLBROKE")
    broken_case = resolution(client, broken, due_at=PAST)

    page = client.get("/resolution-cases/promise-health")
    assert page.status_code == 200, page.text
    body = page.json()
    assert [(i["case_id"], i["status"], i["remaining_amount"]) for i in body["items"]] == [
        (broken_case, "broken", "100.00"), (risky_case, "at_risk", "30.00")]
    assert body["total"] == 2 and body["cases_checked"] == 4
    assert partial_case not in {i["case_id"] for i in body["items"]}
    assert len(client.get("/resolution-cases/promise-health?limit=1").json()["items"]) == 1
