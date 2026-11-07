from uuid import UUID, uuid4

import pytest


@pytest.fixture
def payload():
    return {
        "order_id": "ORDER-001",
        "complaint": "My refund is incomplete.",
        "payment": {
            "capture_id": "DEMO-CAPTURE-001",
            "captured_amount": "100.00",
            "currency": "USD",
        },
        "commitment": {
            "amount": "100.00",
            "currency": "USD",
            "source_message": (
                "We will refund the full $100 after receiving your return."
            ),
            "condition": "Return must be received",
            "status": "accepted",
        },
    }


def test_create_and_retrieve_case_with_agreement(client, payload):
    response = client.post("/cases", json=payload)

    assert response.status_code == 201
    created = response.json()
    UUID(created["id"])
    assert created["status"] == "open"
    for key, value in payload.items():
        assert created[key] == value

    retrieved = client.get(f"/cases/{created['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json() == created


@pytest.mark.parametrize("omit_commitment", [True, False])
def test_case_can_exist_before_a_remedy_is_agreed(client, payload, omit_commitment):
    if omit_commitment:
        payload.pop("commitment")
    else:
        payload["commitment"] = None

    response = client.post("/cases", json=payload)
    assert response.status_code == 201
    assert response.json()["commitment"] is None


def test_agreement_is_proposed_unless_explicitly_accepted(client, payload):
    payload["commitment"].pop("status")
    payload["commitment"].pop("condition")
    payload["commitment"].pop("currency")
    payload["payment"].pop("currency")

    response = client.post("/cases", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["commitment"]["status"] == "proposed"
    assert created["commitment"]["condition"] is None
    assert created["commitment"]["currency"] == "USD"
    assert created["payment"]["currency"] == "USD"


def test_cent_amounts_are_returned_as_exact_decimal_strings(client, payload):
    payload["payment"]["captured_amount"] = "0.30"
    payload["commitment"]["amount"] = "0.10"

    response = client.post("/cases", json=payload)
    assert response.status_code == 201
    assert response.json()["payment"]["captured_amount"] == "0.30"
    assert response.json()["commitment"]["amount"] == "0.10"


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    [
        (("payment", "captured_amount"), "0.00"),
        (("payment", "captured_amount"), "-1.00"),
        (("payment", "captured_amount"), "1.001"),
        (("payment", "captured_amount"), "NaN"),
        (("payment", "captured_amount"), "Infinity"),
        (("payment", "captured_amount"), "1000000000000.01"),
        (("commitment", "amount"), "120.00"),
        (("commitment", "amount"), "0.00"),
        (("commitment", "amount"), "-1.00"),
        (("commitment", "amount"), "1.001"),
        (("commitment", "amount"), "NaN"),
        (("payment", "currency"), "EUR"),
        (("commitment", "currency"), "EUR"),
        (("payment", "capture_id"), "   "),
        (("order_id",), "   "),
        (("complaint",), "   "),
        (("commitment", "source_message"), "   "),
        (("commitment", "condition"), "   "),
        (("commitment", "status"), "completed"),
    ],
)
def test_invalid_financial_or_case_data_is_rejected_without_storage(
    client, payload, path, invalid_value, case_count
):
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = invalid_value

    response = client.post("/cases", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]
    assert case_count() == 0


@pytest.mark.parametrize("scope", [None, "payment", "commitment"])
def test_unexpected_fields_are_rejected_at_every_level(client, payload, scope, case_count):
    target = payload if scope is None else payload[scope]
    target["unexpected"] = "value"

    response = client.post("/cases", json=payload)
    assert response.status_code == 422
    assert case_count() == 0


def test_payment_is_required(client, payload, case_count):
    payload.pop("payment")
    assert client.post("/cases", json=payload).status_code == 422
    assert case_count() == 0


def test_unknown_case_returns_not_found(client):
    response = client.get(f"/cases/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Case not found"}


def test_invalid_case_identifier_is_rejected(client):
    assert client.get("/cases/not-a-uuid").status_code == 422


def test_existing_health_endpoint_still_works(client):
    response = client.post("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
