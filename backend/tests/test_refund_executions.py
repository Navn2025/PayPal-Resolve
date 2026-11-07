"""Local lifecycle/transaction tests with synthetic provider DTOs, not HTTP proof."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from uuid import UUID, uuid4

import pytest

from app.main import create_app
from app.paypal import PayPalCaptureDetails, PayPalRefundDetails, PayPalWriteError
from app.settings import Settings


class LocalProvider:
    def __init__(self, merchant_id):
        self.settings = Settings(
            _env_file=None,
            paypal_sandbox_enabled=True,
            paypal_sandbox_refunds_enabled=True,
            paypal_resolve_merchant_id=merchant_id,
            paypal_sandbox_client_id="unit-client",
            paypal_sandbox_merchant_id="UNITSELLER",
        )
        self.mode = "completed"
        self.read_calls = 0
        self.request_ids = []
        self.refunds = {}
        self.barrier = None
        self.capture_status = "COMPLETED"
        self.lock = Lock()

    def close(self):
        pass

    def read_capture(self, case):
        self.read_calls += 1
        if self.barrier:
            self.barrier.wait(timeout=5)
        return capture(case.payment.capture_id, status=self.capture_status)

    def refund_capture(self, case, request_id):
        with self.lock:
            self.request_ids.append(request_id)
            if self.mode == "rejected":
                raise PayPalWriteError(
                    502, "DO-NOT-LEAK-UPSTREAM-BODY", outcome_unknown=False
                )
            if request_id not in self.refunds:
                self.refunds[request_id] = PayPalRefundDetails.model_validate(
                    {
                        "id": "UNITREFUND" + str(len(self.refunds) + 1),
                        "amount": {"value": "100.00", "currency_code": "USD"},
                        "status": "PENDING" if self.mode == "pending" else "COMPLETED",
                        "links": [
                            {
                                "rel": "up",
                                "method": "GET",
                                "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/"
                                + case.payment.capture_id,
                            }
                        ],
                    }
                )
            if self.mode == "unknown_once":
                self.mode = "completed"
                raise PayPalWriteError(
                    503, "DO-NOT-LEAK-UPSTREAM-BODY", outcome_unknown=True
                )
            return self.refunds[request_id]

    def read_refund(self, case, refund_id):
        for key, refund in self.refunds.items():
            if refund.id == refund_id:
                self.refunds[key] = refund.model_copy(update={"status": "COMPLETED"})
                return self.refunds[key]
        raise AssertionError("Unexpected synthetic refund lookup")


def capture(capture_id="EXECCAPTURE", status="COMPLETED"):
    return PayPalCaptureDetails.model_validate(
        {
            "id": capture_id,
            "amount": {"value": "100.00", "currency_code": "USD"},
            "status": status,
            "payee": {"merchant_id": "UNITSELLER"},
        }
    )


@pytest.fixture
def provider(client):
    local = LocalProvider(client.get("/auth/me").json()["id"])
    client.app.state.paypal_client.close()
    client.app.state.paypal_client = local
    return local


def ready(client, *, amount="100.00", verified=True):
    response = client.post(
        "/cases",
        json={
            "order_id": "EXECUTION-ORDER",
            "complaint": "Synthetic full-refund test",
            "payment": {"capture_id": "EXECCAPTURE", "captured_amount": "100.00"},
            "commitment": {
                "amount": amount,
                "status": "accepted",
                "source_message": "Synthetic test commitment.",
            },
        },
    )
    assert response.status_code == 201
    case = response.json()
    if verified:
        client.app.state.store.record_capture_verification(
            UUID(case["id"]), UUID(case["merchant_id"]), capture()
        )
    basis = client.get(f"/cases/{case['id']}/reconciliation").json()
    approved = client.post(
        f"/cases/{case['id']}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": "EXECCAPTURE",
            "amount": amount,
            "state_fingerprint": basis["state_fingerprint"],
            "decision_note": "Synthetic test consent.",
        },
    )
    assert approved.status_code == 201
    return case["id"], {
        "request_id": str(uuid4()),
        "approval_id": approved.json()["id"],
    }


def submit(client, case_id, body):
    return client.post(f"/cases/{case_id}/refund-executions", json=body)


def test_execution_projects_verified_refund_and_replays_without_resubmission(
    client, provider
):
    case_id, body = ready(client)
    response = submit(client, case_id, body)
    assert response.status_code == 201, response.text
    execution = response.json()
    assert execution["status"] == "completed"
    assert execution["attempt_count"] == 1
    assert execution["provider_refund"]["refund_details_verified"] is True
    assert execution["approval_snapshot"]["id"] == body["approval_id"]
    assert execution["final_capture_check"]["capture_status"] == "COMPLETED"
    assert len(provider.request_ids) == 1
    assert submit(client, case_id, body).status_code == 200
    assert len(provider.request_ids) == 1
    assert (
        submit(client, case_id, {**body, "request_id": str(uuid4())}).status_code == 409
    )
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    assert basis["status"] == "fulfilled"
    assert basis["completed_refund_amount"] == "100.00"
    assert basis["verified_with_paypal"] is False
    assert basis["refund_verifications"][0]["refund_details_verified"] is True
    prefix = f"/cases/{case_id}/refund-executions/{execution['id']}"
    assert [event["status"] for event in client.get(prefix + "/events").json()] == [
        "reserved",
        "submitting",
        "completed",
    ]
    provider.settings.paypal_sandbox_refunds_enabled = False
    assert submit(client, case_id, body).status_code == 200
    assert len(provider.request_ids) == 1


@pytest.mark.parametrize(
    "blocked", ["disabled", "partial", "unverified", "expired", "revoked", "stale"]
)
def test_ineligible_execution_makes_no_provider_call(client, provider, blocked):
    case_id, body = ready(
        client,
        amount="20.00" if blocked == "partial" else "100.00",
        verified=blocked != "unverified",
    )
    if blocked == "disabled":
        provider.settings.paypal_sandbox_refunds_enabled = False
    elif blocked == "expired":
        with sqlite3.connect(client.app.state.store.path) as connection:
            connection.execute(
                "UPDATE refund_approvals SET expires_at='2000-01-01T00:00:00+00:00'"
            )
    elif blocked == "revoked":
        assert (
            client.post(
                f"/cases/{case_id}/refund-approvals/{body['approval_id']}/revoke",
                json={"reason": "Changed decision"},
            ).status_code
            == 200
        )
    elif blocked == "stale":
        with sqlite3.connect(client.app.state.store.path) as connection:
            connection.execute(
                "UPDATE refund_approvals SET state_fingerprint=?", ("0" * 64,)
            )
    response = submit(client, case_id, body)
    assert response.status_code == (503 if blocked == "disabled" else 409)
    assert provider.read_calls == 0
    assert not provider.request_ids
    assert client.get(f"/cases/{case_id}/refund-executions").json() == []


def test_fresh_provider_status_rejects_previously_saved_capture(client, provider):
    case_id, body = ready(client)
    provider.capture_status = "PARTIALLY_REFUNDED"
    assert submit(client, case_id, body).status_code == 409
    assert provider.read_calls == 1 and not provider.request_ids


def test_unknown_holds_balance_and_recovers_with_same_identity_after_restart(
    client, provider, merchant_client
):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    response = submit(client, case_id, body)
    assert response.status_code == 201
    execution = response.json()
    assert execution["status"] == "unknown"
    assert "DO-NOT-LEAK" not in response.text
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    assert basis["status"] == "execution_pending"
    assert basis["completed_refund_amount"] == "0.00"
    assert basis["pending_refund_amount"] == "0.00"
    assert basis["recommended_refund_amount"] == "0.00"
    assert basis["active_refund_execution_id"] == execution["id"]
    commitment = client.get(f"/cases/{case_id}").json()["commitment"]
    assert (
        client.put(
            f"/cases/{case_id}/commitment",
            json={
                "state_fingerprint": basis["state_fingerprint"],
                "commitment": commitment | {"amount": "50.00"},
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/cases/{case_id}/refunds",
            json={
                "refund_id": "MANUAL",
                "capture_id": "EXECCAPTURE",
                "amount": "1.00",
                "status": "completed",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/cases/{case_id}/refund-approvals/{body['approval_id']}/revoke",
            json={"reason": "Too late"},
        ).status_code
        == 409
    )
    api_key = client.headers["Authorization"].split(" ", 1)[1]
    with merchant_client(create_app(client.app.state.store.path), api_key) as restarted:
        restarted.app.state.paypal_client.close()
        restarted.app.state.paypal_client = provider
        recovered = restarted.post(
            f"/cases/{case_id}/refund-executions/{execution['id']}/retry"
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == "completed"
        assert recovered.json()["attempt_count"] == 2
        assert (
            recovered.json()["provider_request_id"] == execution["provider_request_id"]
        )
    assert len(set(provider.request_ids)) == 1
    assert len(provider.refunds) == 1
    assert len(client.get(f"/cases/{case_id}/refunds").json()) == 1


def test_pending_refund_refreshes_without_another_financial_post(client, provider):
    case_id, body = ready(client)
    provider.mode = "pending"
    execution = submit(client, case_id, body).json()
    assert execution["status"] == "pending"
    prefix = f"/cases/{case_id}/refund-executions/{execution['id']}"
    assert client.post(prefix + "/retry").status_code == 409
    refreshed = client.post(prefix + "/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "completed"
    assert len(provider.request_ids) == 1
    refund_id = refreshed.json()["provider_refund"]["refund_id"]
    assert (
        client.patch(
            f"/cases/{case_id}/refunds/{refund_id}", json={"status": "completed"}
        ).status_code
        == 409
    )
    assert len(client.get(f"/cases/{case_id}/paypal-refund-verifications").json()) == 2


def test_definitive_provider_rejection_creates_no_refund_record(client, provider):
    case_id, body = ready(client)
    provider.mode = "rejected"
    response = submit(client, case_id, body)
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "provider_request_rejected"
    assert "DO-NOT-LEAK" not in response.text
    assert client.get(f"/cases/{case_id}/refunds").json() == []
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()[
            "active_refund_execution_id"
        ]
        is None
    )
    failed_basis = client.get(f"/cases/{case_id}/reconciliation").json()
    assert failed_basis["status"] == "execution_failed"
    assert failed_basis["next_action"] == "review_failed_execution"
    assert failed_basis["recommended_refund_amount"] == "0.00"


def test_later_verified_external_refund_can_fulfill_despite_failed_execution(
    client, provider
):
    case_id, body = ready(client)
    provider.mode = "rejected"
    execution = submit(client, case_id, body).json()
    external = PayPalRefundDetails.model_validate(
        {
            "id": "UNITEXTERNALREFUND",
            "amount": {"value": "100.00", "currency_code": "USD"},
            "status": "COMPLETED",
            "links": [
                {
                    "rel": "up",
                    "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/EXECCAPTURE",
                }
            ],
        }
    )
    provider.refunds[uuid4()] = external
    response = client.post(
        f"/cases/{case_id}/paypal-refund-verifications", json={"refund_id": external.id}
    )
    assert response.status_code == 201, response.text
    basis = client.get(f"/cases/{case_id}/reconciliation").json()
    assert basis["status"] == "fulfilled"
    assert basis["failed_refund_execution_id"] == execution["id"]
    assert basis["completed_refund_amount"] == "100.00"
    assert len(provider.request_ids) == 1


def test_reservation_and_event_are_atomic_before_provider_write(client, provider):
    case_id, body = ready(client)
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_execution_reservation BEFORE INSERT ON refund_execution_events
            WHEN NEW.status='reserved' BEGIN SELECT RAISE(ABORT, 'forced reservation audit failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="forced reservation"):
        submit(client, case_id, body)
    assert client.get(f"/cases/{case_id}/refund-executions").json() == []
    assert not provider.request_ids


def test_provider_success_with_local_audit_failure_remains_recoverable(
    client, provider
):
    case_id, body = ready(client)
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("""CREATE TRIGGER reject_execution_completion BEFORE INSERT ON refund_execution_events
            WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT, 'forced completion audit failure'); END""")
    response = submit(client, case_id, body)
    execution = response.json()
    assert execution["status"] == "unknown"
    assert execution["error_code"] == "provider_result_needs_local_recovery"
    assert client.get(f"/cases/{case_id}/refunds").json() == []
    assert client.get(f"/cases/{case_id}/paypal-refund-verifications").json() == []
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute("DROP TRIGGER reject_execution_completion")
    recovered = client.post(
        f"/cases/{case_id}/refund-executions/{execution['id']}/retry"
    )
    assert recovered.json()["status"] == "completed"
    assert len(provider.refunds) == 1 and len(set(provider.request_ids)) == 1


def test_older_unknown_outcome_can_be_read_reconciled_without_reposting(
    client, provider
):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    execution = submit(client, case_id, body).json()
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "UPDATE refund_executions SET created_at=?",
            ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),),
        )
    prefix = f"/cases/{case_id}/refund-executions/{execution['id']}"
    assert client.post(prefix + "/retry").status_code == 409
    refund_id = next(iter(provider.refunds.values())).id
    result = client.post(prefix + "/refresh", json={"refund_id": refund_id})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    assert len(provider.request_ids) == 1


def test_rejection_of_a_retry_does_not_erase_an_earlier_unknown_outcome(
    client, provider
):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    execution = submit(client, case_id, body).json()
    provider.mode = "rejected"
    result = client.post(f"/cases/{case_id}/refund-executions/{execution['id']}/retry")
    assert result.status_code == 200
    assert result.json()["status"] == "unknown"
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()["status"]
        == "execution_pending"
    )


@pytest.mark.parametrize("identity", ["client", "seller", "legacy_missing"])
def test_recovery_cannot_change_paypal_idempotency_scope(client, provider, identity):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    execution = submit(client, case_id, body).json()
    if identity == "client":
        from pydantic import SecretStr

        provider.settings.paypal_sandbox_client_id = SecretStr("another-app")
    elif identity == "seller":
        provider.settings.paypal_sandbox_merchant_id = "ANOTHERSELLER"
    else:
        with sqlite3.connect(client.app.state.store.path) as connection:
            connection.execute(
                "UPDATE refund_executions SET provider_identity_hash=NULL"
            )
    result = client.post(f"/cases/{case_id}/refund-executions/{execution['id']}/retry")
    assert result.status_code == 409
    assert len(provider.request_ids) == 1
    assert (
        client.get(f"/cases/{case_id}/reconciliation").json()[
            "active_refund_execution_id"
        ]
        == execution["id"]
    )


def test_active_submission_lease_blocks_parallel_retry_and_stale_worker_failure(
    client, provider
):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    execution = submit(client, case_id, body).json()
    prefix = f"/cases/{case_id}/refund-executions/{execution['id']}"
    entered, release = Event(), Event()
    original = provider.refund_capture

    def held_request(case, request_id):
        entered.set()
        assert release.wait(timeout=5)
        return original(case, request_id)

    provider.refund_capture = held_request
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.post, prefix + "/retry")
        try:
            assert entered.wait(timeout=3)
            assert client.post(prefix + "/retry").status_code == 409
            from app.executions import RefundExecutionService

            result = RefundExecutionService(client.app.state.store, provider)._failure(
                UUID(case_id),
                UUID(execution["id"]),
                UUID(execution["merchant_id"]),
                unknown=True,
                code="stale_worker",
                attempt=1,
            )
            assert result.status == "submitting" and result.attempt_count == 2
        finally:
            release.set()
        assert future.result().json()["status"] == "completed"
    assert len(provider.refunds) == 1


def test_stale_submitting_record_can_resume_using_original_request_identity(
    client, provider
):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    execution = submit(client, case_id, body).json()
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "UPDATE refund_executions SET status='submitting', lease_expires_at='2000-01-01T00:00:00+00:00'"
        )
    response = client.post(
        f"/cases/{case_id}/refund-executions/{execution['id']}/retry"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert len(set(provider.request_ids)) == 1


@pytest.mark.parametrize("same_request", [True, False])
def test_two_app_instances_cannot_reserve_two_refunds(
    client, provider, merchant_client, same_request
):
    case_id, body = ready(client)
    second_body = body if same_request else {**body, "request_id": str(uuid4())}
    provider.barrier = Barrier(2)
    key = client.headers["Authorization"].split(" ", 1)[1]
    with merchant_client(create_app(client.app.state.store.path), key) as second:
        second.app.state.paypal_client.close()
        second.app.state.paypal_client = provider
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda item: submit(item[0], case_id, item[1]),
                    [(client, body), (second, second_body)],
                )
            )
    assert sorted(response.status_code for response in responses) == (
        [200, 201] if same_request else [201, 409]
    )
    assert len(provider.refunds) == 1 and len(provider.request_ids) == 1


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        (
            "POST",
            "/refund-executions",
            {"request_id": str(uuid4()), "approval_id": str(uuid4())},
        ),
        ("GET", "/refund-executions", None),
        ("GET", "/refund-executions/{id}", None),
        ("POST", "/refund-executions/{id}/retry", None),
        ("POST", "/refund-executions/{id}/refresh", None),
        ("GET", "/refund-executions/{id}/events", None),
        ("POST", "/paypal-refund-verifications", {"refund_id": "SOMEREFUND"}),
        ("GET", "/paypal-refund-verifications", None),
    ],
)
def test_execution_routes_require_authentication_and_owner(
    client, provider, method, suffix, body
):
    case_id, _ = ready(client)
    url = f"/cases/{case_id}" + suffix.replace("{id}", str(uuid4()))
    assert (
        client.request(
            method, url, json=body, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    other = client.app.state.store.create_merchant("Another execution owner")
    assert (
        client.request(
            method, url, json=body, headers={"Authorization": f"Bearer {other.api_key}"}
        ).status_code
        == 404
    )
    assert not provider.request_ids and not provider.read_calls


@pytest.mark.parametrize(
    "extra",
    [
        {"amount": "1.00"},
        {"provider_request_id": str(uuid4())},
        {"merchant_id": str(uuid4())},
    ],
)
def test_execution_amount_actor_and_provider_identity_are_server_controlled(
    client, provider, extra
):
    case_id, body = ready(client)
    assert submit(client, case_id, body | extra).status_code == 422
    assert not provider.request_ids
