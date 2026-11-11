"""Cost controls for promise extraction. Every provider here is a fake."""

from types import SimpleNamespace

import groq
import httpx
import pytest
from test_ai_extraction import KEY, MESSAGES, FakeCompletions, proposal

from app.ai_extraction import (
    GROQ_DATA_POLICY,
    MAX_COMPLETION_TOKENS,
    ChatMessage,
    ExtractionSettings,
    cache_key,
)
from app.ai_routes import get_ai_client, get_ai_settings, get_data_policy
from app.ai_usage import ExtractionUsage

BUYER_ONLY = [MESSAGES[0], {**MESSAGES[0], "id": "m2", "text": "Hello? Anyone there?"}]


@pytest.fixture
def ai(client):
    completions = FakeCompletions({"proposals": [proposal()]})
    completions.tokens = 400
    limit = {"tokens": 100_000}
    client.app.dependency_overrides[get_ai_settings] = lambda: ExtractionSettings(
        enabled=True, groq_key=KEY, daily_token_limit=limit["tokens"]
    )
    client.app.dependency_overrides[get_data_policy] = lambda: GROQ_DATA_POLICY
    client.app.dependency_overrides[get_ai_client] = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    def case(http=client):
        return http.post("/resolution-cases", json={"title": "Broken mug"}).json()["id"]

    def extract(messages=MESSAGES, case_id=None, http=client):
        return http.post(
            f"/resolution-cases/{case_id or case(http)}/ai/extract-promises",
            json={"messages": messages},
        ).json()

    extract.completions, extract.limit, extract.case = completions, limit, case
    yield extract
    client.app.dependency_overrides.clear()


def other_merchant(client, merchant_client):
    key = client.app.state.store.create_merchant("Other merchant").api_key
    return merchant_client(client.app, key)


def test_conversation_without_merchant_messages_skips_the_model(client, ai):
    body = ai(BUYER_ONLY)

    assert (body["status"], body["skipped_reason"], body["proposals"]) == (
        "ok", "no_merchant_messages", [],
    )
    assert ai.completions.calls == [] and body["tokens"] == 0
    usage = client.get("/ai/usage").json()
    assert usage["skipped"] == {"no_merchant_messages": 1} and usage["model_calls"] == 0


@pytest.mark.parametrize("text", ["ok", "k", "Will check.", "\U0001f44d"])
def test_any_merchant_message_is_sent_to_the_model(ai, text):
    ai.completions.outcome = {"proposals": []}

    body = ai([MESSAGES[0], {**MESSAGES[1], "text": text}])

    assert len(ai.completions.calls) == 1 and body["skipped_reason"] is None


def test_completion_is_capped_at_800_tokens(ai):
    ai()

    assert MAX_COMPLETION_TOKENS == 800
    assert ai.completions.calls[0]["max_tokens"] == 800


def test_identical_input_returns_the_stored_result_with_zero_tokens(client, ai):
    first = ai()
    second = ai()

    assert len(ai.completions.calls) == 1
    assert (first["cache_hit"], first["tokens"]) == (False, 400)
    assert (second["cache_hit"], second["tokens"]) == (True, 0)
    assert second["proposals"] == first["proposals"]
    assert second["case_id"] != first["case_id"]  # each request keeps its own case
    changed = [MESSAGES[0], {**MESSAGES[1], "text": MESSAGES[1]["text"] + " "}]
    ai(changed)
    assert len(ai.completions.calls) == 2
    usage = client.get("/ai/usage").json()
    assert (usage["tokens"], usage["model_calls"], usage["cache_hits"]) == (800, 2, 1)
    assert [c["cache_hit"] for c in usage["calls"]] == [False, True, False]


def test_cache_is_not_shared_between_merchants(client, ai, merchant_client):
    ai()
    with other_merchant(client, merchant_client) as other:
        body = ai(http=other)
        assert body["cache_hit"] is False
        assert other.get("/ai/usage").json()["tokens"] == 400
    assert len(ai.completions.calls) == 2


def test_failures_are_not_cached(ai):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    ai.completions.outcome = groq.APITimeoutError(request=request)
    assert ai()["review_reasons"] == ["timeout"]
    ai.completions.outcome = {"proposals": [proposal()]}

    body = ai()

    assert body["status"] == "ok" and body["cache_hit"] is False
    assert len(ai.completions.calls) == 2


def test_daily_budget_blocks_further_calls_per_merchant(client, ai, merchant_client):
    ai.limit["tokens"] = 500
    assert ai()["tokens"] == 400
    assert ai([MESSAGES[0], {**MESSAGES[1], "text": "We will refund $25.00 by Friday."}])["tokens"] == 400

    blocked = ai([MESSAGES[0], {**MESSAGES[1], "text": "We will refund $25.00 on Friday."}])

    assert blocked["status"] == "needs_review"
    assert blocked["review_reasons"] == ["budget_exceeded"]
    assert blocked["skipped_reason"] == "budget_exceeded"
    assert len(ai.completions.calls) == 2
    # The stored result stays available without spending tokens.
    assert ai()["cache_hit"] is True
    usage = client.get("/ai/usage").json()
    assert (usage["tokens"], usage["remaining_tokens"], usage["daily_token_limit"]) == (800, 0, 500)
    assert usage["skipped"] == {"budget_exceeded": 1}
    with other_merchant(client, merchant_client) as other:
        assert ai(http=other)["status"] == "ok"


def test_budget_limit_is_read_from_the_environment_only(monkeypatch, tmp_path):
    monkeypatch.delenv("RESOLVE_EXTRACTION_DAILY_TOKEN_LIMIT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("RESOLVE_EXTRACTION_DAILY_TOKEN_LIMIT=5\n")
    assert ExtractionSettings().daily_token_limit == 100_000

    monkeypatch.setenv("RESOLVE_EXTRACTION_DAILY_TOKEN_LIMIT", "2500")
    assert ExtractionSettings().daily_token_limit == 2500


def test_usage_requires_merchant_credentials(client):
    client.headers.pop("Authorization")

    assert client.get("/ai/usage").status_code == 401


def test_usage_resets_on_a_new_utc_day():
    days = iter(["2026-11-09", "2026-11-09", "2026-11-10"])
    usage = ExtractionUsage(clock=lambda: next(days))
    usage.record("m", case_id="c", tokens=300, cache_hit=False, skipped_reason=None, status="ok", model_called=True)

    assert usage.tokens_today("m") == 300
    assert usage.summary("m")["tokens"] == 0


def test_cache_key_covers_model_prompt_and_every_message_field():
    messages = [ChatMessage(**message) for message in MESSAGES]
    base = cache_key("model-a", messages)

    assert base == cache_key("model-a", [ChatMessage(**m) for m in MESSAGES])
    assert base != cache_key("model-b", messages)
    for field, value in [("id", "m9"), ("sender", "buyer"), ("text", "x"), ("sent_at", "2026-11-08T09:06:00Z")]:
        changed = [messages[0], ChatMessage(**{**MESSAGES[1], field: value})]
        assert cache_key("model-a", changed) != base
    from app import ai_extraction

    original = ai_extraction.PROMPT_VERSION
    try:
        ai_extraction.PROMPT_VERSION = "other"
        assert cache_key("model-a", messages) != base
    finally:
        ai_extraction.PROMPT_VERSION = original


def test_cache_holds_raw_output_and_reruns_validators_on_every_hit(client, ai):
    import json

    ai()
    usage = client.app.state.extraction_usage
    [(key, raw)] = usage._cache.items()
    assert isinstance(raw, str) and json.loads(raw) == {"proposals": [proposal()]}
    # A cached answer that does not validate against the current conversation is not trusted.
    usage._cache[key] = json.dumps({"proposals": [proposal(exact_quote="we will refund $90.00 today")]})
    hit = ai()
    assert (hit["cache_hit"], hit["tokens"], hit["proposals"]) == (True, 0, [])
    assert hit["dropped"] and len(ai.completions.calls) == 1
