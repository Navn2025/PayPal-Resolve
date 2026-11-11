"""Suggested remedies. All data is synthetic; PayPal refunds are simulated through the store's
own provider-refund recorder and every AI provider is a fake, never a network call."""

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from test_promise_health import paypal_refund

from app.ai_extraction import GROQ_DATA_POLICY, ExtractionSettings
from app.ai_routes import get_ai_client, get_ai_settings, get_data_policy
from app.ai_usage import ExtractionUsage
from app.main import create_app
from app.remedies import RemedyOption, guard, rank
from app.settings import Settings

D = Decimal


class FakeClient:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))],
                               usage=SimpleNamespace(total_tokens=91))


def payment_case(client, capture, captured="100.00"):
    response = client.post("/cases", json={
        "order_id": "ORDER" + capture, "complaint": "Remedy test",
        "payment": {"capture_id": capture, "captured_amount": captured},
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def resolution(client, refund_case=None, reference="ORD-REMEDY"):
    response = client.post("/resolution-cases", json={
        "title": "Broken lamp", "order_reference": reference, **({"refund_case_id": refund_case} if refund_case else {})})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def remedies(client, case_id):
    response = client.get(f"/resolution-cases/{case_id}/remedies")
    assert response.status_code == 200, response.text
    return response.json()


def options(body):
    return {item["id"]: item for item in body["options"]}


def set_policy(client, **policy):
    store = client.app.state.store
    with store.transaction(write=True) as connection:
        merchant = connection.execute("SELECT merchant_id FROM resolution_cases LIMIT 1").fetchone()[0]
        connection.execute("INSERT INTO assurance_policies VALUES (?,?,?,?)",
                           (str(merchant), 1, json.dumps({"window_days": 30, **policy}), datetime.now(UTC).isoformat()))


# Options from the reconciliation and the return policy (code only)

def test_options_use_captured_minus_completed_minus_pending(client):
    refund = payment_case(client, "REMBAL")
    case_id = resolution(client, refund)
    paypal_refund(client, refund, "RFDONE", "20.00")
    paypal_refund(client, refund, "RFPEND", "10.00", status="PENDING")
    body = remedies(client, case_id)
    facts = body["facts"]
    assert (facts["captured_amount"], facts["completed_refund_amount"], facts["pending_refund_amount"],
            facts["refundable_amount"]) == ("100.00", "20.00", "10.00", "70.00")
    found = options(body)
    assert list(found) == ["refund_after_return", "partial_refund"]
    assert found["refund_after_return"]["amount"] == "70.00"
    assert found["refund_after_return"]["return_milestone"] == "warehouse_received"
    # The default remedy policy: 20% of the refundable balance, rounded down to the cent.
    assert found["partial_refund"]["amount"] == "14.00" and found["partial_refund"]["requires_return"] is False
    assert {item["kind"] for item in body["unavailable"]} == {"store_credit", "replacement"}


def test_return_policy_fee_and_inspection_shape_the_return_option(client):
    refund = payment_case(client, "REMPOL")
    case_id = resolution(client, refund)
    set_policy(client, enabled=True, restocking_fee="5.00", inspection_required=True, window_days=14)
    body = remedies(client, case_id)
    option = options(body)["refund_after_return"]
    assert option["amount"] == "95.00" and option["return_milestone"] == "inspection_passed"
    assert "14 days" in option["description"] and "$5.00 restocking fee" in option["reason"]
    assert body["facts"]["restocking_fee"] == "5.00" and body["facts"]["return_window_days"] == 14


def test_partial_percent_comes_from_the_environment(monkeypatch):
    assert Settings(_env_file=None).remedy_partial_refund_percent == 20
    monkeypatch.setenv("RESOLVE_REMEDY_PARTIAL_REFUND_PERCENT", "35")
    assert Settings(_env_file=None).remedy_partial_refund_percent == 35


@pytest.mark.parametrize("state", ["unlinked", "open_refund", "fully_refunded", "hold"])
def test_no_refund_options_when_they_are_not_valid(client, monkeypatch, state):
    refund = None if state == "unlinked" else payment_case(client, "REMNO" + state.upper()[:6])
    case_id = resolution(client, refund)
    if state == "open_refund":
        assert client.post(f"/resolution-cases/{case_id}/promises", json={
            "promise": "Refund $10", "source_note": "Chat", "target": {"kind": "refund", "amount": "10.00"}}).status_code == 201
    if state == "fully_refunded":
        paypal_refund(client, refund, "RFALL", "100.00")
    if state == "hold":
        monkeypatch.setattr("app.remedies.provider_hold", lambda *args, **kwargs: True)
    body = remedies(client, case_id)
    assert body["options"] == []
    reasons = {item["kind"]: item["reason"] for item in body["unavailable"]}
    assert set(reasons) == {"refund_after_return", "partial_refund", "store_credit", "replacement"}
    expected = {"unlinked": "Link the payment", "open_refund": "already open", "fully_refunded": "Nothing is left",
                "hold": "hold blocks"}[state]
    assert expected in reasons["partial_refund"]


# Creating promises: merchant-requested, re-checked against the current balance

def test_refund_after_return_creates_a_return_and_a_dependent_refund(client):
    refund = payment_case(client, "REMCRT")
    case_id = resolution(client, refund)
    due = (datetime.now(UTC) + timedelta(days=5)).replace(microsecond=0).isoformat()
    response = client.post(f"/resolution-cases/{case_id}/remedies/promises",
                           json={"option_id": "refund_after_return", "expected_amount": "100.00", "due_at": due})
    assert response.status_code == 201, response.text
    body = response.json()
    returned, refund_promise = body["promises"]
    assert returned["terms"]["target"] == {"kind": "return", "milestone": "warehouse_received",
                                           "return_reference": "ORD-REMEDY", "tracking": None}
    assert refund_promise["terms"]["target"]["amount"] == "100.00"
    assert refund_promise["terms"]["requires"] == [returned["id"]]
    assert body["offer_choice"] == {"promise_id": refund_promise["id"], "expected_revision": 1}
    # Nothing was published: offers are a separate, explicit merchant step.
    store = client.app.state.store
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM platform_offers").fetchone()[0] == 0
    # The open refund promise now blocks further refund suggestions.
    assert remedies(client, case_id)["options"] == []


def test_partial_refund_creates_one_refund_promise(client):
    refund = payment_case(client, "REMPRT")
    case_id = resolution(client, refund)
    response = client.post(f"/resolution-cases/{case_id}/remedies/promises",
                           json={"option_id": "partial_refund", "expected_amount": "20.00"})
    assert response.status_code == 201, response.text
    [only] = response.json()["promises"]
    assert only["terms"]["target"]["amount"] == "20.00" and only["terms"]["requires"] == []
    assert "keeps the item" in only["terms"]["promise"]


def test_create_rechecks_the_balance_and_availability(client):
    refund = payment_case(client, "REMCHK")
    case_id = resolution(client, refund)
    url = f"/resolution-cases/{case_id}/remedies"
    assert options(remedies(client, case_id))["refund_after_return"]["amount"] == "100.00"
    paypal_refund(client, refund, "RFLATE", "30.00")
    stale = client.post(url + "/promises", json={"option_id": "refund_after_return", "expected_amount": "100.00"})
    assert stale.status_code == 409 and "balance changed" in stale.json()["detail"]
    assert client.get(f"/resolution-cases/{case_id}").json()["promises"] == []
    unknown = client.post(url + "/promises", json={"option_id": "store_credit", "expected_amount": "10.00"})
    assert unknown.status_code == 422
    paypal_refund(client, refund, "RFREST", "70.00")
    gone = client.post(url + "/promises", json={"option_id": "partial_refund", "expected_amount": "14.00"})
    assert gone.status_code == 409 and "Nothing is left" in gone.json()["detail"]


def test_one_refund_option_per_case_keeps_the_cumulative_refund_rule(client):
    refund = payment_case(client, "REMONE")
    case_id = resolution(client, refund)
    url = f"/resolution-cases/{case_id}/remedies/promises"
    assert client.post(url, json={"option_id": "partial_refund", "expected_amount": "20.00"}).status_code == 201
    second = client.post(url, json={"option_id": "refund_after_return", "expected_amount": "100.00"})
    assert second.status_code == 409 and "already open" in second.json()["detail"]
    assert len(client.get(f"/resolution-cases/{case_id}").json()["promises"]) == 1


# AI ranking: masked, fact-guarded, cached as raw output

OPTIONS = [
    RemedyOption(id="refund_after_return", title="Refund $70.00 after the return", description="d", amount=D("70.00"),
                 currency="USD", requires_return=True, return_milestone="warehouse_received", reason="Balance."),
    RemedyOption(id="partial_refund", title="Partial refund of $14.00", description="d", amount=D("14.00"),
                 currency="USD", requires_return=False, reason="20%."),
]
GOOD = {"issue": "damaged", "buyer_preference": "keep_item",
        "ranking": [{"option_id": "partial_refund", "reason": "The buyer wants to keep the lamp."},
                    {"option_id": "refund_after_return", "reason": "Full $70.00 back once it is returned."}],
        "buyer_message": "Sorry about the lamp. You can keep it with a $14.00 refund, or return it for $70.00."}
MESSAGES = [SimpleNamespace(sender="buyer", text="It arrived cracked. I'd rather keep it. Card 4111 1111 1111 1111.")]


def suggestions(items=OPTIONS):
    from app.remedies import RemedyFacts, RemedySuggestions
    facts = RemedyFacts(payment_linked=True, return_policy_enabled=False, return_policy_revision=0, restocking_fee=D("0"),
                        return_window_days=None, inspection_required=False, partial_refund_percent=20)
    return RemedySuggestions(case_id=uuid4(), facts=facts, options=items, unavailable=[])


def ranked(reply, *, usage=None, merchant="m1", settings=None, policy=GROQ_DATA_POLICY, client=...):
    fake = FakeClient(*(reply if isinstance(reply, list) else [reply])) if client is ... else client
    found = suggestions()
    result = rank(found.case_id, found, MESSAGES, fake, settings or ExtractionSettings(enabled=True, model="test-model"),
                  data_policy=policy, usage=usage, merchant_id=merchant)
    return result, fake


def test_ai_ranks_the_listed_options_and_drafts_a_message():
    result, fake = ranked(json.dumps(GOOD))
    assert result.source == "ai" and result.label == "AI suggestion – verify before acting"
    assert (result.issue, result.buyer_preference) == ("damaged", "keep_item")
    assert [item.option_id for item in result.ranking] == ["partial_refund", "refund_after_return"]
    sent = json.loads(fake.calls[0]["messages"][1]["content"].split("\n", 1)[1])
    # Masked before it leaves: the card number never reaches the provider.
    assert "4111" not in json.dumps(sent) and [o["id"] for o in sent["options"]] == ["refund_after_return", "partial_refund"]


@pytest.mark.parametrize(("change", "violation"), [
    ({"buyer_message": "We can refund $50.00 today."}, "amount $50.00"),
    ({"buyer_message": "We can send a replacement instead."}, "replacement"),
    ({"buyer_message": "Please reply within 3 days."}, "number 3"),
    ({"ranking": [{"option_id": "store_credit", "reason": "x"}, {"option_id": "partial_refund", "reason": "y"}]},
     "exactly once"),
    ({"ranking": [{"option_id": "partial_refund", "reason": "Only this."}]}, "exactly once"),
    ({"issue": "fraud"}, "issue"),
])
def test_fact_guard_falls_back_to_code_order_and_template(change, violation):
    result, _ = ranked(json.dumps({**GOOD, **change}))
    assert result.source == "code" and result.fallback_reason == "fact_guard"
    assert any(violation in item for item in result.guard_violations)
    assert [item.option_id for item in result.ranking] == ["refund_after_return", "partial_refund"]
    assert "$70.00" in result.buyer_message and "$14.00" in result.buyer_message


def test_guard_accepts_only_listed_amounts():
    violations, checked = guard(GOOD, OPTIONS)
    assert violations == [] and checked["ranking"][0]["option_id"] == "partial_refund"


@pytest.mark.parametrize(("case", "reason"), [("disabled", "extraction_disabled"), ("no_client", "not_configured"),
                                              ("policy", "data_policy_blocked"), ("budget", "budget_exceeded"),
                                              ("bad_json", "invalid_json")])
def test_ranking_falls_back_without_calling_when_not_allowed(case, reason):
    usage = ExtractionUsage()
    if case == "budget":
        usage.record("m1", case_id=uuid4(), tokens=10, cache_hit=False, skipped_reason=None, status="ok", model_called=True)
    result, fake = ranked("not json", usage=usage,
                          settings=ExtractionSettings(enabled=case != "disabled", daily_token_limit=10 if case == "budget" else 100_000),
                          policy="blocked" if case == "policy" else GROQ_DATA_POLICY,
                          client=None if case == "no_client" else ...)
    assert (result.source, result.fallback_reason) == ("code", reason)
    if case != "bad_json":
        assert fake is None or fake.calls == []


def test_ranking_cache_stores_raw_output_and_revalidates_on_every_hit():
    usage = ExtractionUsage()
    first, fake = ranked(json.dumps(GOOD), usage=usage)
    second, _ = ranked([], usage=usage, client=fake)
    assert (first.cache_hit, first.tokens, second.cache_hit, second.tokens) == (False, 91, True, 0)
    assert len(fake.calls) == 1 and second.source == "ai"
    assert all(isinstance(value, str) for value in usage._cache.values())
    # A cached answer that no longer passes the guard is not trusted.
    key = next(iter(usage._cache))
    usage._cache[key] = json.dumps({**GOOD, "buyer_message": "Refund $99.00 now."})
    third, _ = ranked([], usage=usage, client=fake)
    assert (third.source, third.fallback_reason, third.cache_hit) == ("code", "fact_guard", True)


def test_rank_route_uses_the_ai_dependencies_and_changes_nothing(client):
    refund = payment_case(client, "REMAI")
    case_id = resolution(client, refund)
    token = client.post(f"/resolution-cases/{case_id}/customer-link", json={}).json()["token"]
    assert client.post("/customer-portal/messages", headers={"Authorization": ""}, json={
        "token": token, "request_id": str(uuid4()), "body": "It arrived cracked, I'd like my money back."}).status_code == 201
    fake = FakeClient(json.dumps({**GOOD, "buyer_preference": "full_refund",
                                  "ranking": [{"option_id": "refund_after_return", "reason": "The buyer asks for their money back."},
                                              {"option_id": "partial_refund", "reason": "Keeps the item with $20.00 back."}],
                                  "buyer_message": "Return it for $100.00 or keep it with $20.00 back."}))
    client.app.dependency_overrides.update({get_ai_settings: lambda: ExtractionSettings(enabled=True, model="test-model"),
                                            get_ai_client: lambda: fake, get_data_policy: lambda: GROQ_DATA_POLICY})
    try:
        body = client.post(f"/resolution-cases/{case_id}/ai/rank-remedies").json()
    finally:
        client.app.dependency_overrides.clear()
    assert body["source"] == "ai", body
    assert [item["option_id"] for item in body["ranking"]] == ["refund_after_return", "partial_refund"]
    assert "cracked" in fake.calls[0]["messages"][1]["content"]
    assert client.get(f"/resolution-cases/{case_id}").json()["promises"] == []
    # Off by default: code order and template, no provider call.
    off = client.post(f"/resolution-cases/{case_id}/ai/rank-remedies").json()
    assert (off["source"], off["fallback_reason"]) == ("code", "extraction_disabled")


# Publishing through the existing offer endpoint re-checks the balance

@pytest.fixture
def platform_api(tmp_path, request):
    cfg = Settings(_env_file=None, platform_encryption_key=Fernet.generate_key().decode())
    store = request.getfixturevalue("postgres_store") if os.environ.get("RESOLVE_TEST_STORAGE") == "postgres" else None
    with TestClient(create_app(tmp_path / "remedies.sqlite3", settings=cfg, store=store)) as http:
        account = http.post("/platform/account/signup", json={
            "workspace": "Synthetic remedy store", "name": "Owner", "email": "remedy-owner@example.test",
            "password": "synthetic-password-123"}).json()
        http.headers["Authorization"] = "Bearer " + account["token"]
        yield http


def test_offer_publishing_rechecks_the_refundable_balance(platform_api):
    http = platform_api
    refund = payment_case(http, "REMPUB")
    case_id = resolution(http, refund)
    created = http.post(f"/resolution-cases/{case_id}/remedies/promises",
                        json={"option_id": "refund_after_return", "expected_amount": "100.00"})
    assert created.status_code == 201, created.text
    choice = created.json()["offer_choice"]
    expiry = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    paypal_refund(http, refund, "RFPUB", "40.00")
    blocked = http.post(f"/platform/cases/{case_id}/offers", json={"choices": [choice], "expires_at": expiry})
    assert blocked.status_code == 409 and "refundable balance" in blocked.json()["detail"]
    fresh = http.post(f"/resolution-cases/{case_id}/remedies/promises",
                      json={"option_id": "partial_refund", "expected_amount": "12.00"})
    assert fresh.status_code == 409  # the open refund promise blocks another suggestion
    store = http.app.state.store
    with store.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM platform_offers").fetchone()[0] == 0


def test_offer_within_the_balance_publishes(platform_api):
    http = platform_api
    refund = payment_case(http, "REMOK")
    case_id = resolution(http, refund)
    created = http.post(f"/resolution-cases/{case_id}/remedies/promises",
                        json={"option_id": "partial_refund", "expected_amount": "20.00"})
    assert created.status_code == 201, created.text
    choice = created.json()["offer_choice"]
    published = http.post(f"/platform/cases/{case_id}/offers", json={
        "choices": [choice], "expires_at": (datetime.now(UTC) + timedelta(days=3)).isoformat()})
    assert published.status_code == 201, published.text
    assert published.json()["choices"][0]["promise_id"] == choice["promise_id"]
    assert UUID(published.json()["id"])
