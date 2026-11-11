from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from threading import Barrier
from uuid import uuid4

import httpx
import pytest

from app.errors import StoreError
from app.evidence_models import EvidenceInput
from app.evidence_workspace import EvidenceWorkspace
from app.inference import (
    Budget,
    GroqProvider,
    InferenceUnavailable,
    InvestigationSettings,
    OpenRouterProvider,
)
from app.investigations import Investigations
from app.investigation_models import ReadSelection, Triage
from app.investigation_refresh import refresh_linked
from app.investigation_worker import run_once
from app.paypal import PayPalSandboxClient, PayPalCaptureDetails, PayPalRefundDetails
from app.settings import Settings
from app.synthetic_investigations import INJECTION, LABELS, seed, simulated_providers


LABEL_DATA = json.loads(LABELS.read_text())


def identity(client):
    return client.get("/auth/me").json()["id"]


def latest(client, case):
    response = client.get(f"/resolution-cases/{case.id}/investigations")
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def add_note(store, case, merchant, text="Synthetic new evidence"):
    return EvidenceWorkspace(store).add(
        case.id,
        merchant,
        EvidenceInput(
            source="synthetic",
            source_event_id=str(uuid4()),
            evidence_type="support_note",
            occurred_at=datetime.now(timezone.utc),
            summary=text,
        ),
    )


@pytest.mark.parametrize("label", LABEL_DATA["cases"], ids=lambda c: c["name"])
def test_labeled_http_simulations_and_hard_gates(client, label):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, label)
    queued = latest(client, case)
    assert queued["state"] == "queued"
    with simulated_providers(label) as (cfg, groq, deep, requests):
        assert run_once(store, settings=cfg, groq=groq, openrouter=deep) == {
            "processed": 1
        }
        result = latest(client, case)
        assert result["state"] == label.get("expected_state", "finished")
        assert result["result"]["status"] == label["expected_status"]
        assert result["result"]["next_step"] == label["expected_next"]
        assert 1 <= len(requests) <= 4
        for request in requests:
            raw = json.dumps(request["messages"])
            assert (
                INJECTION not in raw
                and "secret@example.test" not in raw
                and "SYNTHETICCAPTURE" not in raw
            )
            assert "tools" not in request
            if request["model"] == cfg.openrouter_model:
                assert request["provider"] == {
                    "only": ["phala"],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                    "data_collection": "deny",
                    "zdr": True,
                    "max_price": {"completion": 0.74},
                }
            else:
                assert request["reasoning_effort"] == "low"
    with store.transaction() as db:
        evidence_ids = {
            r[0]
            for r in db.execute(
                "SELECT id FROM resolution_events WHERE resolution_id=? AND merchant_id=?",
                (str(case.id), merchant),
            )
        }
        assert all(
            f["evidence_id"] in evidence_ids for f in result["result"]["findings"]
        )
        assert db.execute("SELECT count(*) FROM refund_approvals").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0
        audit_types = {
            r[0]
            for r in db.execute(
                "SELECT event_type FROM investigation_audit WHERE resolution_id=? AND merchant_id=?",
                (str(case.id), merchant),
            )
        }
        assert "investigation_enqueued" in audit_types
        assert "investigation_started" in audit_types
        assert "investigation_" + result["state"] in audit_types
    if label.get("cross_tenant"):
        other = store.create_merchant("Other synthetic tenant")
        headers = {"Authorization": "Bearer " + other.api_key}
        assert (
            client.get(
                f"/resolution-cases/{case.id}/investigations", headers=headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/resolution-cases/{case.id}/investigations/{result['id']}/review",
                headers=headers,
                json={
                    "expected_revision": result["case_revision"],
                    "evidence_snapshot": result["result"]["evidence_snapshot"],
                    "decision": "approve",
                },
            ).status_code
            == 404
        )


def test_disabled_is_reviewable_and_review_is_not_refund_approval(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "disabled"})
    assert run_once(store)["processed"] == 1
    item = latest(client, case)
    assert item["state"] == "blocked"
    assert item["result"]["validation_failures"] == ["inference_disabled"]
    path = f"/resolution-cases/{case.id}/investigations/{item['id']}/review"
    payload = {
        "expected_revision": item["case_revision"],
        "evidence_snapshot": item["result"]["evidence_snapshot"],
        "decision": "approve",
    }
    start = Barrier(2)

    def review(_):
        start.wait(timeout=5)
        return client.post(path, json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(review, range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["authorizes_payment"] is False
    assert client.post(path, json={**payload, "decision": "reject"}).status_code == 409
    with store.transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM investigation_reviews").fetchone()[0] == 1
        )
        assert db.execute("SELECT count(*) FROM refund_approvals").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0
    add_note(store, case, merchant)
    assert client.post(path, json=payload).status_code == 409
    assert latest(client, case)["state"] == "queued"


def test_duplicate_evidence_does_not_requeue_and_workers_claim_once(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "retries"})
    payload = EvidenceInput(
        source="synthetic",
        source_event_id="same",
        evidence_type="support_note",
        occurred_at=datetime.now(timezone.utc),
        summary="Same retry",
    )
    workspace = EvidenceWorkspace(store)
    workspace.add(case.id, merchant, payload)
    revision = latest(client, case)["case_revision"]
    workspace.add(case.id, merchant, payload)
    assert latest(client, case)["case_revision"] == revision
    start = Barrier(2)

    def work(_):
        start.wait(timeout=5)
        return run_once(store)["processed"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(work, range(2))) == [0, 1]
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM investigations").fetchone()[0] == 1


def test_concurrent_different_reviews_have_one_winner(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "different-reviews"})
    run_once(store)
    item = latest(client, case)
    start = Barrier(2)

    def decide(decision):
        start.wait(timeout=5)
        return client.post(
            f"/resolution-cases/{case.id}/investigations/{item['id']}/review",
            json={
                "expected_revision": item["case_revision"],
                "evidence_snapshot": item["result"]["evidence_snapshot"],
                "decision": decision,
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decide, ["approve", "reject"])) == [200, 409]


def test_changed_evidence_during_inference_cannot_publish(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "race"})

    class ChangingProvider:
        def complete(self, schema, evidence, budget):
            add_note(store, case, merchant)
            return Triage(issue_type="refund", escalate=False, reads=[]), {
                "provider": "simulated"
            }

    cfg = InvestigationSettings(enabled=True)
    assert Investigations(store, cfg).run_one(groq=ChangingProvider())
    assert latest(client, case)["state"] == "queued"
    run_once(store)
    assert latest(client, case)["state"] == "blocked"


@pytest.mark.parametrize("provider", [GroqProvider, OpenRouterProvider])
def test_bounded_timeouts_route_policy_and_malformed_outputs(provider):
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout")

    cfg = InvestigationSettings(
        enabled=True,
        data_policy="minimized_standard_retention",
        groq_key="synthetic",
        openrouter_key="synthetic",
    )
    with httpx.Client(transport=httpx.MockTransport(timeout), trust_env=False) as http:
        adapter = provider(cfg, http)
        with pytest.raises(InferenceUnavailable, match="timeout"):
            adapter.complete(Triage, {}, Budget())
        assert len(calls) == 2
        cfg.data_policy = "zdr_required"
        with pytest.raises(InferenceUnavailable, match="policy"):
            adapter.complete(Triage, {}, Budget())
        assert len(calls) == 2
    for response in (
        {"choices": []},
        {
            "provider": "Wrong",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"issue_type":"refund","escalate":false,"reads":[]}'
                    },
                }
            ],
        },
    ):
        cfg.data_policy = "minimized_standard_retention"
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
        ) as http:
            if provider == GroqProvider and response.get("provider") == "Wrong":
                continue
            with pytest.raises(InferenceUnavailable):
                provider(cfg, http).complete(Triage, {}, Budget())


def test_failed_refresh_preserves_verified_time_and_prevents_queue_loop(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "refresh-failed", "refunds": [], "old": True})
    with store.transaction() as db:
        link = db.execute(
            "SELECT id FROM resolution_evidence_links WHERE resolution_id=?",
            (str(case.id),),
        ).fetchone()[0]
    selection = ReadSelection(operation="refresh_linked_capture", evidence_id=link)

    class FailedPayPal:
        def _merchant_configuration(self, merchant_id):
            raise StoreError(503, "Synthetic unavailable")

    before = (
        EvidenceWorkspace(store)
        .get(case.id, merchant)
        .evidence_summary.last_verified_at
    )
    result = refresh_linked(store, FailedPayPal(), case.id, merchant, selection)
    assert result.verified == []
    assert (
        EvidenceWorkspace(store)
        .get(case.id, merchant)
        .evidence_summary.last_verified_at
        == before
    )

    class RefreshingProvider:
        def complete(self, schema, evidence, budget):
            return Triage(issue_type="refund", escalate=False, reads=[selection]), {}

    cfg = InvestigationSettings(enabled=True, allow_sandbox_refresh=True)

    def forbidden(*args):
        pytest.fail("Recent refresh must never repeat")

    run_once(store, settings=cfg, groq=RefreshingProvider(), refresh=forbidden)
    assert latest(client, case)["result"]["validation_failures"] == [
        "evidence_refresh_unavailable_or_recent"
    ]
    assert run_once(store)["processed"] == 0
    with pytest.raises(StoreError):
        refresh_linked(
            store,
            FailedPayPal(),
            case.id,
            merchant,
            ReadSelection(operation="refresh_linked_capture", evidence_id=uuid4()),
        )


def test_model_cannot_select_another_cases_read(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "unauthorized"})

    class ForgedRead:
        def complete(self, *args):
            return Triage(
                issue_type="refund",
                escalate=False,
                reads=[
                    ReadSelection(
                        operation="refresh_linked_capture", evidence_id=uuid4()
                    )
                ],
            ), {}

    run_once(store, settings=InvestigationSettings(enabled=True), groq=ForgedRead())
    assert latest(client, case)["result"]["validation_failures"] == [
        "unauthorized_evidence_read"
    ]


@pytest.mark.parametrize("provider_refresh_enabled", [False, True])
def test_current_owned_fact_satisfies_model_read_without_provider_or_money(client, provider_refresh_enabled):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "current-owned-read", "refunds": [["25.00", "COMPLETED"]], "capture_status": "REFUNDED"})
    with store.transaction() as db:
        link = db.execute("SELECT id FROM resolution_evidence_links WHERE resolution_id=? AND kind='paypal_capture'", (str(case.id),)).fetchone()[0]

    class ReadCurrent:
        def complete(self, *args):
            return Triage(issue_type="refund", escalate=False, reads=[ReadSelection(operation="refresh_linked_capture", evidence_id=link)]), {}

    def forbidden(*args):
        pytest.fail("An already verified current fact must not repeat a provider request")

    run_once(store, settings=InvestigationSettings(enabled=True, allow_sandbox_refresh=provider_refresh_enabled), groq=ReadCurrent(), refresh=forbidden)
    item = latest(client, case)
    assert item["state"] == "finished"
    assert item["result"]["status"] == "confirmed_full_refund"
    assert item["result"]["next_step"] == "no_action"
    assert item["result"]["validation_failures"] == []
    with store.transaction() as db:
        event = db.execute("SELECT data_json FROM investigation_audit WHERE resolution_id=? AND event_type='investigation_read_cache_hit'", (str(case.id),)).fetchone()
        assert json.loads(event[0])["evidence_id"] == link
        assert db.execute("SELECT count(*) FROM refund_approvals").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0


def test_cached_read_respects_shorter_configured_freshness(client, monkeypatch):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "expired-owned-read", "refunds": [["25.00", "COMPLETED"]], "capture_status": "REFUNDED"})
    later = datetime.now(timezone.utc) + timedelta(minutes=2)
    monkeypatch.setattr("app.investigations.now", lambda: later)
    with store.transaction() as db:
        link = db.execute("SELECT id FROM resolution_evidence_links WHERE resolution_id=? AND kind='paypal_capture'", (str(case.id),)).fetchone()[0]

    class ReadExpired:
        def complete(self, *args):
            return Triage(issue_type="refund", escalate=False, reads=[ReadSelection(operation="refresh_linked_capture", evidence_id=link)]), {}

    run_once(store, settings=InvestigationSettings(enabled=True, freshness_seconds=60), groq=ReadExpired())
    assert latest(client, case)["state"] == "blocked"
    assert latest(client, case)["result"]["validation_failures"] == ["evidence_refresh_unavailable_or_recent"]
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM investigation_audit WHERE event_type='investigation_read_cache_hit'").fetchone()[0] == 0


def test_stale_freshness_blocks_approval_but_allows_request_evidence(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "stale-review", "old": True, "refunds": []})
    run_once(store)
    item = latest(client, case)
    path = f"/resolution-cases/{case.id}/investigations/{item['id']}/review"
    payload = {
        "expected_revision": item["case_revision"],
        "evidence_snapshot": item["result"]["evidence_snapshot"],
        "decision": "approve",
    }
    assert client.post(path, json=payload).status_code == 409
    assert (
        client.post(path, json={**payload, "decision": "request_evidence"}).status_code
        == 200
    )


def test_authorized_capture_refresh_uses_real_http_and_stops_after_one_read(
    client, monkeypatch
):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "http-refresh", "refunds": [], "old": True})
    with store.transaction() as db:
        link = db.execute(
            "SELECT id FROM resolution_evidence_links WHERE resolution_id=?",
            (str(case.id),),
        ).fetchone()[0]
    selection = ReadSelection(operation="refresh_linked_capture", evidence_id=link)
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, payload):
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            paths.append(("POST", self.path))
            assert self.path == "/v1/oauth2/token"
            self.respond(
                {
                    "access_token": "synthetic-token",
                    "token_type": "Bearer",
                    "expires_in": 300,
                }
            )

        def do_GET(self):
            paths.append(("GET", self.path))
            assert self.path == "/v2/payments/captures/SYNTHETICCAPTURE"
            self.respond(
                {
                    "id": "SYNTHETICCAPTURE",
                    "status": "COMPLETED",
                    "amount": {"value": "25.00", "currency_code": "USD"},
                    "payee": {"merchant_id": "SYNTHETICSELLER"},
                }
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        "app.paypal.SANDBOX_BASE_URL", f"http://127.0.0.1:{server.server_port}"
    )
    cfg = Settings(
        _env_file=None,
        paypal_sandbox_enabled=True,
        paypal_resolve_merchant_id=merchant,
        paypal_sandbox_client_id="synthetic",
        paypal_sandbox_client_secret="synthetic",
        paypal_sandbox_merchant_id="SYNTHETICSELLER",
    )

    class Refreshing:
        def complete(self, *args):
            return Triage(issue_type="refund", escalate=False, reads=[selection]), {}

    try:
        with httpx.Client(trust_env=False, timeout=8) as http:
            paypal = PayPalSandboxClient(cfg, http)
            run_once(
                store,
                settings=InvestigationSettings(
                    enabled=True, allow_sandbox_refresh=True
                ),
                groq=Refreshing(),
                refresh=lambda c, m, s: refresh_linked(store, paypal, c, m, s),
            )
        assert paths == [
            ("POST", "/v1/oauth2/token"),
            ("GET", "/v2/payments/captures/SYNTHETICCAPTURE"),
        ]
        item = latest(client, case)
        assert item["result"]["validation_failures"] == [
            "model_or_credentials_unavailable"
        ]
        # The verified capture is reused, but a single capture read still does
        # not prove complete refund history. Missing deeper inference stays blocked.
        assert item["state"] == "blocked"
        assert "complete_provider_refund_history" in item["result"]["missing_evidence"]
        with store.transaction() as db:
            assert db.execute("SELECT count(*) FROM investigation_audit WHERE resolution_id=? AND event_type='investigation_read_cache_hit'", (str(case.id),)).fetchone()[0] == 1
        assert not item["stale"]
        assert run_once(store)["processed"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_shared_capture_evidence_requeues_both_owned_cases_and_never_promotes_manual_refunds(
    client,
):
    store, merchant = client.app.state.store, identity(client)
    resolutions, payments = [], []
    for index in range(2):
        response = client.post(
            "/cases",
            json={
                "order_id": "SYNTHETICORDER",
                "complaint": "Synthetic conditional refund",
                "payment": {
                    "capture_id": "SYNTHETICSHARED",
                    "captured_amount": "25.00",
                },
                "commitment": {
                    "amount": "25.00",
                    "status": "accepted",
                    "source_message": "Synthetic agreement",
                    "condition": "Return received",
                },
            },
        )
        assert response.status_code == 201
        payment = response.json()
        payments.append(payment["id"])
        resolutions.append(
            client.post(
                "/resolution-cases",
                json={
                    "title": "Shared synthetic capture",
                    "refund_case_id": payment["id"],
                },
            ).json()["id"]
        )
    run_once(store)
    before = [
        client.get(f"/resolution-cases/{r}/investigations").json()["items"][0][
            "case_revision"
        ]
        for r in resolutions
    ]
    store.record_capture_verification(
        payments[0],
        merchant,
        PayPalCaptureDetails(
            id="SYNTHETICSHARED",
            amount={"value": "25.00", "currency_code": "USD"},
            status="COMPLETED",
            payee={"merchant_id": "SYNTHETICSELLER"},
        ),
    )
    for r, revision in zip(resolutions, before):
        item = client.get(f"/resolution-cases/{r}/investigations").json()["items"][0]
        assert item["state"] == "queued" and item["case_revision"] > revision
    assert (
        client.post(
            f"/cases/{payments[0]}/refunds",
            json={
                "capture_id": "SYNTHETICSHARED",
                "refund_id": "SYNTHETICMANUAL",
                "amount": "6.25",
                "status": "completed",
            },
        ).status_code
        == 201
    )
    run_once(store)
    for r in resolutions:
        item = client.get(f"/resolution-cases/{r}/investigations").json()["items"][0]
        assert item["result"]["status"] == "missing"
        assert (
            "manual_refund_ledger_not_provider_confirmed"
            in item["result"]["missing_evidence"]
        )
        assert "linked_payment_awaiting_condition" in item["result"]["missing_evidence"]
        assert [f["kind"] for f in item["result"]["findings"]] == ["paypal_capture"]


def test_expired_lease_recovery_is_bounded_and_old_lease_cannot_overwrite(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "leased"})
    with store.transaction(write=True) as db:
        db.execute(
            "UPDATE investigation_jobs SET state='running',attempts=2,lease_token='old',lease_until=? WHERE resolution_id=?",
            (
                (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat(),
                str(case.id),
            ),
        )

    class Forbidden:
        def complete(self, *args):
            pytest.fail("A revision cannot exceed its worker attempt budget")

    run_once(store, settings=InvestigationSettings(enabled=True), groq=Forbidden())
    assert latest(client, case)["result"]["validation_failures"] == [
        "worker_attempt_budget_exceeded"
    ]


def test_scoped_key_and_buyer_cannot_read_or_review_investigations(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "private"})
    run_once(store)
    item = latest(client, case)
    scoped = store.issue_key(merchant, scope="commerce")
    headers = {"Authorization": "Bearer " + scoped.api_key}
    assert (
        client.get(
            f"/resolution-cases/{case.id}/investigations", headers=headers
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"/resolution-cases/{case.id}/investigations/{item['id']}/review",
            headers=headers,
            json={
                "expected_revision": item["case_revision"],
                "evidence_snapshot": item["result"]["evidence_snapshot"],
                "decision": "approve",
            },
        ).status_code
        == 401
    )
    link = client.post(f"/resolution-cases/{case.id}/customer-link", json={}).json()
    buyer = client.post(
        "/customer-portal/view",
        headers={"Authorization": ""},
        json={"token": link["token"]},
    )
    assert buyer.status_code == 200
    assert "investigation" not in buyer.text and "inference_disabled" not in buyer.text


@pytest.mark.parametrize(
    "content,finish,message_extra",
    [
        (
            '{"issue_type":"refund","escalate":false,"reads":[],"execute_refund":true}',
            "stop",
            {},
        ),
        (
            '{"issue_type":"refund","issue_type":"unknown","escalate":false,"reads":[]}',
            "stop",
            {},
        ),
        ('{"issue_type":"refund","escalate":false,"reads":[]}', "length", {}),
        (
            '{"issue_type":"refund","escalate":false,"reads":[]}',
            "stop",
            {"tool_calls": [{"function": {"name": "execute_refund"}}]},
        ),
        (
            '{"issue_type":"refund","escalate":false,"reads":[]}',
            "stop",
            {"refusal": "Synthetic refusal"},
        ),
    ],
)
def test_untrusted_provider_outputs_never_grant_authority(
    content, finish, message_extra
):
    cfg = InvestigationSettings(
        enabled=True, data_policy="minimized_standard_retention", groq_key="synthetic"
    )
    response = {
        "choices": [
            {"finish_reason": finish, "message": {"content": content, **message_extra}}
        ]
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as http:
        with pytest.raises(InferenceUnavailable):
            GroqProvider(cfg, http).complete(Triage, {}, Budget())


def test_policy_model_route_and_call_budget_fail_closed_without_network():
    def forbidden(_):
        pytest.fail("A rejected policy/model/route/budget must never reach the network")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as http:
        base = dict(
            enabled=True,
            data_policy="minimized_standard_retention",
            groq_key="synthetic",
            openrouter_key="synthetic",
        )
        for cfg, adapter in [
            (InvestigationSettings(**base, groq_model="unapproved"), GroqProvider),
            (
                InvestigationSettings(**base, openrouter_model="google/gemini-3.8-flash"),
                OpenRouterProvider,
            ),
            (
                InvestigationSettings(
                    **base, openrouter_model="anthropic/claude-sonnet-5.5"
                ),
                OpenRouterProvider,
            ),
            (InvestigationSettings(**base, openrouter_routes=()), OpenRouterProvider),
        ]:
            with pytest.raises(InferenceUnavailable):
                adapter(cfg, http).complete(Triage, {}, Budget())
        with pytest.raises(InferenceUnavailable, match="budget"):
            GroqProvider(InvestigationSettings(**base), http).complete(
                Triage, {}, Budget(remaining=0)
            )


@pytest.mark.parametrize(
    "model,routes,expected_provider",
    [
        ("xingchen-agi/xing4.0-29b-a4b:free", ("phala",), "Phala"),
        ("openai/gpt-oss-120b", ("phala",), "Phala"),
    ],
)
@pytest.mark.parametrize("valid_provider", [True, False])
def test_budget_openrouter_models_keep_route_and_privacy_controls(
    model, routes, expected_provider, valid_provider
):
    cfg = InvestigationSettings(
        enabled=True,
        data_policy="minimized_standard_retention",
        openrouter_key="synthetic",
        openrouter_model=model,
        openrouter_routes=routes,
    )

    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == model
        assert payload["provider"] == {
            "only": list(routes),
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "zdr": True,
            "max_price": {"completion": 0.74},
        }
        assert payload["response_format"]["json_schema"]["strict"] is True
        if model == "openai/gpt-oss-120b":
            assert payload["reasoning_effort"] == "low"
        else:
            assert "reasoning_effort" not in payload
        wrong_provider = "Anthropic"
        return httpx.Response(
            200,
            json={
                "provider": expected_provider if valid_provider else wrong_provider,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"issue_type": "refund", "escalate": False, "reads": []}
                            )
                        },
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenRouterProvider(cfg, http)
        if valid_provider:
            result, metadata = adapter.complete(Triage, {}, Budget())
            assert result.issue_type == "refund"
            assert metadata["model"] == model
        else:
            with pytest.raises(InferenceUnavailable, match="unexpected_provider_route"):
                adapter.complete(Triage, {}, Budget())


def test_malformed_persisted_evidence_produces_a_reviewable_block(client):
    store, merchant = client.app.state.store, identity(client)
    case = seed(store, merchant, {"name": "invalid-source", "refunds": []})
    with store.transaction(write=True) as db:
        db.execute(
            "UPDATE resolution_evidence_state SET data_json=? WHERE resolution_id=?",
            ('{"facts":[{}]}', str(case.id)),
        )
    assert run_once(store)["processed"] == 1
    item = latest(client, case)
    assert item["state"] == "blocked"
    assert item["result"]["validation_failures"] == ["source_validation_failed"]
    assert item["result"]["next_step"] == "abstain"


def test_existing_verified_payment_history_is_usable_without_sdk_refresh(
    client, monkeypatch
):
    store, merchant = client.app.state.store, identity(client)
    payment = client.post(
        "/cases",
        json={
            "order_id": "SYNTHETICORDER",
            "complaint": "Synthetic refund confirmation",
            "payment": {"capture_id": "SYNTHETICLEGACY", "captured_amount": "100.00"},
            "commitment": {
                "amount": "100.00",
                "status": "accepted",
                "source_message": "Synthetic agreement",
            },
        },
    ).json()
    resolution = client.post(
        "/resolution-cases",
        json={"title": "Existing verified payment", "refund_case_id": payment["id"]},
    ).json()
    capture = store.record_capture_verification(
        payment["id"],
        merchant,
        PayPalCaptureDetails(
            id="SYNTHETICLEGACY",
            amount={"value": "100.00", "currency_code": "USD"},
            status="REFUNDED",
            payee={"merchant_id": "SYNTHETICSELLER"},
        ),
    )
    with store.transaction(write=True) as db:
        legacy = store._require_case(db, payment["id"], merchant)
        refund = store._record_provider_refund(
            db,
            legacy,
            PayPalRefundDetails(
                id="SYNTHETICREFUND",
                amount={"value": "100.00", "currency_code": "USD"},
                status="COMPLETED",
                links=[],
            ),
        )
        checked = datetime.now(timezone.utc).isoformat()
        history = {
            "order_id": "SYNTHETICORDER",
            "capture_id": "SYNTHETICLEGACY",
            "capture_status": "REFUNDED",
            "checked_at": checked,
            "digest": "0" * 64,
            "refund_ids": ["SYNTHETICREFUND"],
            "completed_amount": "100.00",
            "pending_amount": "0.00",
            "remaining_amount": "0.00",
            "ledger": {"SYNTHETICREFUND": ["100.00", "completed"]},
        }
        db.execute(
            "INSERT INTO paypal_refund_history VALUES (?,?,?,?,?,?,?,?)",
            (
                merchant,
                "SYNTHETICLEGACY",
                str(uuid4()),
                "0" * 64,
                "SYNTHETICORDER",
                "synthetic-identity",
                checked,
                json.dumps(history),
            ),
        )
    with simulated_providers() as (cfg, groq, deep, _):
        run_once(store, settings=cfg, groq=groq, openrouter=deep)
    item = client.get(f"/resolution-cases/{resolution['id']}/investigations").json()[
        "items"
    ][0]
    assert item["state"] == "finished"
    assert item["result"]["status"] == "confirmed_full_refund"
    assert item["result"]["next_step"] == "no_action"
    assert item["result"]["missing_evidence"] == []
    assert {f["evidence_id"] for f in item["result"]["findings"]} == {
        str(capture.id),
        str(refund.id),
    }
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    monkeypatch.setattr("app.investigations.now", lambda: later)
    expired = client.get(f"/resolution-cases/{resolution['id']}/investigations").json()[
        "items"
    ][0]
    assert expired["stale"]
    assert (
        client.post(
            f"/resolution-cases/{resolution['id']}/investigations/{item['id']}/review",
            json={
                "expected_revision": item["case_revision"],
                "evidence_snapshot": item["result"]["evidence_snapshot"],
                "decision": "approve",
            },
        ).status_code
        == 409
    )
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM refund_approvals").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM refund_executions").fetchone()[0] == 0
