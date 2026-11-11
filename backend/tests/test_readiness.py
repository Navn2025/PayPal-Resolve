from contextlib import contextmanager


def test_readiness_checks_database_without_credentials(client):
    client.headers.pop("Authorization")
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_readiness_hides_database_failure(client, monkeypatch):
    @contextmanager
    def unavailable(**kwargs):
        raise RuntimeError("private database connection details")
        yield

    monkeypatch.setattr(client.app.state.store, "transaction", unavailable)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "private database" not in response.text


def test_public_webhook_fails_closed_without_provider_configuration(client):
    client.headers.pop("Authorization")
    response = client.post("/webhooks/paypal/sandbox", json={
        "id": "WH-AUDIT-UNCONFIGURED", "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource_type": "refund", "resource": {"id": "AUDITREFUND"},
    })
    assert response.status_code == 503
    assert "detail" in response.json()
