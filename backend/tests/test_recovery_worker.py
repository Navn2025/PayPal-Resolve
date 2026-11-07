from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from app.settings import Settings
from app.worker import run_once
from test_refund_executions import LocalProvider, ready, submit


@pytest.fixture
def provider(client):
    result = LocalProvider(client.get("/auth/me").json()["id"])
    client.app.state.paypal_client.close()
    client.app.state.paypal_client = result
    return result


def test_worker_recovers_due_unknown_without_creating_new_consent(client, provider):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    execution = submit(client, case_id, body).json()
    report = run_once(
        client.app.state.store,
        provider,
        now=datetime.now(timezone.utc) + timedelta(seconds=10),
    )
    assert report["processed"] == report["completed"] == 1
    assert report["errors"] == 0
    assert len(provider.refunds) == 1 and len(set(provider.request_ids)) == 1
    assert (
        client.get(f"/cases/{case_id}/refund-executions/{execution['id']}").json()[
            "status"
        ]
        == "completed"
    )
    assert len(client.get(f"/cases/{case_id}/refund-approvals").json()) == 1


def test_worker_observes_backoff_and_does_not_race_active_lease(client, provider):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    assert submit(client, case_id, body).json()["status"] == "unknown"
    assert run_once(client.app.state.store, provider)["processed"] == 0
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "UPDATE refund_executions SET status='submitting',lease_expires_at=?",
            ((datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),),
        )
    assert run_once(client.app.state.store, provider)["processed"] == 0
    assert len(provider.request_ids) == 1


def test_worker_marks_old_unknown_for_reconciliation_without_financial_post(
    client, provider
):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    submit(client, case_id, body)
    report = run_once(
        client.app.state.store,
        provider,
        now=datetime.now(timezone.utc) + timedelta(hours=25),
    )
    assert report["processed"] == 0 and report["needs_reconciliation"] == 1
    assert len(provider.request_ids) == 1


def test_writes_disabled_worker_still_reads_pending_refund(client, provider):
    case_id, body = ready(client)
    provider.mode = "pending"
    submit(client, case_id, body)
    provider.settings.paypal_sandbox_refunds_enabled = False
    report = run_once(
        client.app.state.store,
        provider,
        now=datetime.now(timezone.utc) + timedelta(seconds=31),
    )
    assert report["completed"] == 1
    assert len(provider.request_ids) == 1


def test_worker_reports_blocked_unknown_when_writes_disabled(client, provider):
    case_id, body = ready(client)
    provider.mode = "unknown_once"
    submit(client, case_id, body)
    provider.settings.paypal_sandbox_refunds_enabled = False
    report = run_once(
        client.app.state.store,
        provider,
        now=datetime.now(timezone.utc) + timedelta(seconds=10),
    )
    assert report["processed"] == report["blocked"] == 1
    assert report["results"][0]["http_status"] == 503
    assert len(provider.request_ids) == 1


def test_worker_only_processes_configured_merchant(client, provider):
    first_case, first_body = ready(client)
    provider.mode = "unknown_once"
    submit(client, first_case, first_body)
    original_key = client.headers["Authorization"]
    other = client.app.state.store.create_merchant("Another worker tenant")
    other_provider = LocalProvider(other.merchant.id)
    try:
        client.headers["Authorization"] = "Bearer " + other.api_key
        client.app.state.paypal_client = other_provider
        other_case, other_body = ready(client)
        other_provider.mode = "unknown_once"
        other_execution = submit(client, other_case, other_body).json()
    finally:
        client.headers["Authorization"] = original_key
        client.app.state.paypal_client = provider
    report = run_once(
        client.app.state.store,
        provider,
        now=datetime.now(timezone.utc) + timedelta(seconds=10),
    )
    assert report["completed"] == 1
    assert len(other_provider.request_ids) == 1
    with client.app.state.store.transaction() as connection:
        assert (
            connection.execute(
                "SELECT status FROM refund_executions WHERE id=?",
                (other_execution["id"],),
            ).fetchone()[0]
            == "unknown"
        )


def test_worker_cli_one_pass_outputs_metadata_only(
    client, provider, monkeypatch, capsys
):
    from app import worker

    settings = Settings(
        _env_file=None,
        database_path=client.app.state.store.path,
        paypal_resolve_merchant_id=provider.settings.paypal_resolve_merchant_id,
    )
    monkeypatch.setattr(worker, "Settings", lambda: settings)
    monkeypatch.setattr(worker, "PayPalSandboxClient", lambda configuration: provider)
    assert worker.main(["--once"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["processed"] == 0
    assert "api_key" not in report and "access_token" not in report


@pytest.mark.parametrize("limit", [0, 101])
def test_worker_rejects_invalid_batch_size(client, provider, limit):
    with pytest.raises(ValueError):
        run_once(client.app.state.store, provider, limit=limit)
