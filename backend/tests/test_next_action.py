"""Missing-before-refund reasons, the fact-guarded explanation, and time to verified resolution.

All data is synthetic. PayPal refunds are simulated with the store's own recorder and the model
is a local fake: no network call is made."""

import json
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.ai_extraction import ExtractionSettings
from app.ai_routes import get_ai_client, get_ai_settings, get_data_policy
from app.ai_usage import ExtractionUsage
from app.next_action import (
    AI_LABEL,
    CaseFacts,
    Prerequisite,
    RefundFacts,
    collect,
    explain,
    guard,
    template,
)
from app.paypal import PayPalRefundDetails
from app.resolution_metrics import (
    percentile,
    summarize_hours,
    time_to_verified_resolution,
)
from app.resolution_models import ResolutionTimeline

D = Decimal
POLICY = "minimized_standard_retention"


# Helpers

def payment_case(client, capture, goal="100.00", status="accepted", commitment=True):
    body = {"order_id": "ORDER" + capture, "complaint": "Next action test",
            "payment": {"capture_id": capture, "captured_amount": "100.00"}}
    if commitment:
        body["commitment"] = {"amount": goal, "status": status, "source_message": "Agreed refund"}
    response = client.post("/cases", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def resolution(client, refund_case=None):
    response = client.post("/resolution-cases", json={
        "title": "Next action", "order_reference": "STOREORDER1", "refund_case_id": refund_case})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def promise(client, case_id, target, **fields):
    response = client.post(f"/resolution-cases/{case_id}/promises", json={
        "promise": "Promised in chat wording", "source_note": "Support chat note", "target": target, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def returned_and_refund(client, case_id, amount="100.00", **fields):
    back = promise(client, case_id, {"kind": "return", "milestone": "warehouse_received", "return_reference": "RMA1"})
    cash = promise(client, case_id, {"kind": "refund", "amount": amount}, requires=[back["id"]], **fields)
    return back, cash


def confirm(client, case_id, item):
    response = client.post(f"/resolution-cases/{case_id}/promises/{item['id']}/evidence", json={
        "expected_revision": 1, "finding": "confirmed", "note": "Warehouse received it", "reference": "W1"})
    assert response.status_code == 201, response.text


def paypal_refund(client, refund_case, refund_id, amount, status="COMPLETED"):
    store = client.app.state.store
    with store.transaction(write=True) as connection:
        merchant = connection.execute("SELECT merchant_id FROM cases WHERE id=?", (refund_case,)).fetchone()[0]
        case = store._require_case(connection, UUID(refund_case), UUID(str(merchant)))
        store._record_provider_refund(connection, case, PayPalRefundDetails(
            id=refund_id, amount={"value": amount, "currency_code": "USD"}, status=status, links=[]))


def next_action(client, case_id):
    response = client.get(f"/resolution-cases/{case_id}/next-action")
    assert response.status_code == 200, response.text
    return response.json()


def codes(body):
    return [item["code"] for item in body["missing"]]


class FakeClient:
    def __init__(self, *replies, error=None):
        self.replies, self.error, self.calls = list(replies), error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        content = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                               usage=SimpleNamespace(total_tokens=57))


def reply(text):
    return json.dumps({"summary": text})


FACTS = CaseFacts(payment_linked=True, captured_amount=D("100.00"), agreed_amount=D("100.00"), agreement_status="accepted",
                  reconciliation_status="refund_required", recommended_refund_amount=D("80.00"), refunds=[RefundFacts(
                      promise_id=uuid4(), promised_amount=D("100.00"), refunded_amount=D("20.00"), pending_amount=D("0.00"),
                      remaining_amount=D("80.00"), due_date=date(2026, 11, 14), days_since_promise=4,
                      prerequisites=[Prerequisite(name="return", done=True)])])


# 1. Missing before refund

def test_no_linked_payment(client):
    body = next_action(client, resolution(client))
    assert codes(body) == ["no_linked_payment", "no_refund_promise"]
    assert body["summary"] == "No payment is linked → link the payment before any refund."
    assert body["missing"][0]["text"] == "No payment is linked to this case."


def test_no_amount_and_not_accepted(client):
    assert "no_amount" in codes(next_action(client, resolution(client, payment_case(client, "NANOAMT", commitment=False))))
    proposed = next_action(client, resolution(client, payment_case(client, "NAPROP", status="proposed")))
    assert codes(proposed) == ["agreement_not_accepted", "no_refund_promise"]


def test_unmet_return_and_no_deadline(client):
    case_id = resolution(client, payment_case(client, "NAUNMET"))
    _, cash = returned_and_refund(client, case_id)
    body = next_action(client, case_id)
    assert codes(body) == ["no_deadline", "unmet_condition"]
    assert body["missing"][1] == {"code": "unmet_condition", "text": "The return is not confirmed yet.", "promise_id": cash["id"]}
    assert body["summary"] == ("Promised $100.00 after return; $0.00 refunded; $100.00 remaining; "
                               "return not confirmed → confirm the return before any refund.")


def test_pending_refund_is_flagged_and_deadline_counts(client):
    refund = payment_case(client, "NAPEND")
    case_id = resolution(client, refund)
    promise(client, case_id, {"kind": "refund", "amount": "100.00"}, due_at=(datetime.now(UTC) + timedelta(days=2)).isoformat())
    paypal_refund(client, refund, "NAPENDR1", "30.00", status="PENDING")
    body = next_action(client, case_id)
    assert codes(body) == ["pending_refund_unconfirmed"]
    assert body["missing"][0]["text"] == "$30.00 is pending and not yet confirmed by PayPal."
    assert "$30.00 pending" in body["summary"]


def test_example_summary_after_confirmed_return_and_partial_refund(client):
    refund = payment_case(client, "NAEXAMPLE")
    case_id = resolution(client, refund)
    back, _ = returned_and_refund(client, case_id)
    confirm(client, case_id, back)
    paypal_refund(client, refund, "NAEXR1", "20.00")
    body = next_action(client, case_id)
    assert body["summary"] == ("Promised $100.00 after return; $20.00 refunded; $80.00 remaining; "
                               "return confirmed → review a refund of $80.00.")
    assert body["facts"]["recommended_refund_amount"] == "80.00"


def test_unknown_case_is_404(client):
    assert client.get(f"/resolution-cases/{uuid4()}/next-action").status_code == 404


# 2. Fact guard

def test_template_text_always_passes_the_guard():
    assert guard(template(FACTS), FACTS) == []
    assert guard(template(CaseFacts(payment_linked=False)), CaseFacts(payment_linked=False)) == []


@pytest.mark.parametrize("text", [
    "Promised $100.00; $20.00 refunded; $80.00 remains, due Nov 14, 4 days after the promise.",
    "PayPal confirmed $20 of the $100.00 promise; review a refund of 80.00 USD by 2026-11-14.",
])
def test_guard_accepts_facts_in_other_formats(text):
    assert guard(text, FACTS) == []


@pytest.mark.parametrize(("text", "problem"), [
    ("Promised $100.00; refund $90.00 now.", "amount $90.00"),
    ("Refund 85 dollars after the return.", "amount 85 dollars"),
    ("Refund $80.00 by Nov 20.", "date Nov 20"),
    ("Refund $80.00 by 2026-12-01.", "date 2026-12-01"),
    ("Refund $80.00 within 7 days.", "number 7"),
    ("A refund of $80.00 was approved.", "claims an approval"),
])
def test_guard_rejects_invented_values_and_claims(text, problem):
    assert any(problem in violation for violation in guard(text, FACTS))


# 2. Explanation

def settings(**fields):
    return ExtractionSettings(enabled=True, model="test-model", **fields)


def action_for(client):
    refund = payment_case(client, "NAEXPLAIN")
    case_id = resolution(client, refund)
    back, _ = returned_and_refund(client, case_id)
    confirm(client, case_id, back)
    paypal_refund(client, refund, "NAEXPL1", "20.00")
    store = client.app.state.store
    with store.transaction() as connection:
        merchant = connection.execute("SELECT merchant_id FROM resolution_cases WHERE id=?", (case_id,)).fetchone()[0]
    return collect(UUID(case_id), UUID(str(merchant)), store), UUID(str(merchant))


def test_invented_amount_falls_back_to_the_template(client):
    action, merchant = action_for(client)
    fake = FakeClient(reply("Return received, so refund the remaining $90.00 now."))
    result = explain(action, fake, settings(), data_policy=POLICY, usage=ExtractionUsage(), merchant_id=merchant)
    assert result.source == "template" and result.fallback_reason == "fact_guard" and result.label is None
    assert result.text == action.summary
    assert result.guard_violations == ["amount $90.00 is not in the facts"]


def test_grounded_text_is_labelled_cached_and_sent_only_facts(client):
    action, merchant = action_for(client)
    text = "Promised $100.00 after the return; PayPal confirmed $20.00, so review a refund of the remaining $80.00."
    fake, usage = FakeClient(reply(text)), ExtractionUsage()
    first = explain(action, fake, settings(), data_policy=POLICY, usage=usage, merchant_id=merchant)
    assert (first.source, first.label, first.text, first.tokens) == ("ai", AI_LABEL, text, 57)
    assert first.authorizes == "nothing"
    sent = json.dumps(fake.calls[0]["messages"])
    assert "Promised in chat wording" not in sent and "Support chat note" not in sent and str(action.case_id) not in sent
    assert fake.calls[0]["max_tokens"] == 800
    again = explain(action, fake, settings(), data_policy=POLICY, usage=usage, merchant_id=merchant)
    assert again.cache_hit and again.tokens == 0 and again.text == text and len(fake.calls) == 1


@pytest.mark.parametrize(("case", "reason"), [
    ("disabled", "extraction_disabled"), ("no_client", "not_configured"), ("policy", "data_policy_blocked"),
    ("budget", "budget_exceeded"), ("error", "connection_error"), ("bad_json", "invalid_json"),
])
def test_every_skip_or_failure_returns_the_template(client, case, reason):
    import groq
    action, merchant = action_for(client)
    usage = ExtractionUsage()
    fake = FakeClient("not json") if case == "bad_json" else FakeClient(
        error=groq.APIConnectionError(request=SimpleNamespace(method="POST", url="x")) if case == "error" else None)
    if case == "budget":
        usage.record(merchant, case_id=action.case_id, tokens=10, cache_hit=False, skipped_reason=None,
                     status="ok", model_called=True)
    result = explain(action, None if case == "no_client" else fake,
                     ExtractionSettings(enabled=case != "disabled", daily_token_limit=10 if case == "budget" else 100_000),
                     data_policy="blocked" if case == "policy" else POLICY, usage=usage, merchant_id=merchant)
    assert (result.source, result.fallback_reason, result.text) == ("template", reason, action.summary)
    if case in ("disabled", "no_client", "policy", "budget"):
        assert fake.calls == []


def test_explain_route_uses_the_ai_dependencies(client):
    refund = payment_case(client, "NAROUTE")
    case_id = resolution(client, refund)
    promise(client, case_id, {"kind": "refund", "amount": "100.00"})
    fake = FakeClient(reply("Refund $1,000.00 today."))
    app = client.app
    app.dependency_overrides.update({get_ai_settings: lambda: settings(), get_ai_client: lambda: fake,
                                     get_data_policy: lambda: POLICY})
    try:
        body = client.post(f"/resolution-cases/{case_id}/ai/explain-next-action").json()
    finally:
        app.dependency_overrides.clear()
    assert body["source"] == "template" and body["fallback_reason"] == "fact_guard"
    assert body["text"] == "Promised $100.00; $0.00 refunded; $100.00 remaining → review a refund of $100.00."
    assert client.get("/ai/usage").json()["calls"][-1]["case_id"] == case_id
    # Off by default: no provider call, code template returned.
    assert client.post(f"/resolution-cases/{case_id}/ai/explain-next-action").json()["fallback_reason"] == "extraction_disabled"


# 3. Time to verified resolution

def event(promise_id, at):
    return {"sequence": 1, "id": str(uuid4()), "promise_id": promise_id, "revision": 1, "event_type": "promise_recorded",
            "source": "merchant_recorded", "actor_merchant_id": None, "recorded_at": at.isoformat(), "data": {}}


def verified(refund_id, amount, status, at):
    return {"id": f"refund:{refund_id}{status}", "source": "refund_verification", "case_id": str(uuid4()), "capture_id": "C",
            "event_type": "paypal.refund_verified", "actor_merchant_id": None, "actor_kind": "system",
            "occurred_at": at.isoformat(), "data": {"refund_id": refund_id, "amount": amount, "provider_status": status}}


def test_time_to_verified_resolution_counts_only_completed_refunds_covering_the_promise():
    start, pid = datetime(2026, 1, 1, tzinfo=UTC), str(uuid4())
    timeline = ResolutionTimeline.model_validate({"items": [event(pid, start)], "total": 1, "limit": 50, "offset": 0,
        "refund_items": [verified("A", "40.00", "COMPLETED", start + timedelta(hours=5)),
                         verified("B", "60.00", "PENDING", start + timedelta(hours=8)),
                         verified("B", "60.00", "COMPLETED", start + timedelta(hours=30))], "refund_total": 3})
    assert time_to_verified_resolution(timeline, pid, D("100.00")) == timedelta(hours=30)
    assert time_to_verified_resolution(timeline, pid, D("40.00")) == timedelta(hours=5)
    assert time_to_verified_resolution(timeline, pid, D("100.01")) is None
    assert time_to_verified_resolution(timeline, str(uuid4()), D("1.00")) is None


def test_percentiles_and_summary():
    assert percentile([], 0.9) is None
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
    assert summarize_hours([timedelta(hours=2), None, timedelta(hours=4)]) == {
        "cases": 3, "resolved": 2, "unresolved": 1, "median_hours": 3.0, "p90_hours": 4.0}


def test_synthetic_eval_matches_its_own_seeded_plan():
    from evals.run_resolution_eval import _plan, run
    report = run(cases=10, seed=3)
    assert report["data"] == "synthetic"
    rng = random.Random(3)
    for index, row in enumerate(report["cases"]):
        plan = _plan(rng, index)
        expected = {"partial_only": None, "no_refund": None}.get(plan["scenario"], plan["refunds"][-1][2]) \
            if plan["refunds"] else None
        assert row["hours"] == (round(expected, 2) if expected is not None else None), row
