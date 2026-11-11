"""Exercise owner-facing HTTP surfaces, not only their service helpers."""
from test_platform_operations import api, case, buyer_link
from test_assurance import support
from uuid import uuid4


def test_owner_lists_and_case_sections_return_scoped_json(api):
    identifier = case(api)
    for path in ("/platform/team", "/platform/audit", "/platform/sdk-keys", "/platform/connections", "/platform/imports", "/platform/watchdog", f"/platform/cases/{identifier}/offers", f"/platform/cases/{identifier}/dispute-packages"):
        response = api.get(path)
        assert response.status_code == 200, path
        assert isinstance(response.json(), dict)
        assert "items" in response.json(), path
        assert "synthetic-password-123" not in response.text
        assert api.owner["token"] not in response.text
    assert api.get("/platform/return-policy").status_code == 200
    disputes = api.get(f"/platform/cases/{identifier}/disputes")
    assert disputes.status_code == 200 and disputes.json()["capture_held"] is False


def test_buyer_return_catalog_and_assurance_use_own_private_link(api):
    locator, headers, identifier = support(api)
    token = buyer_link(api, identifier)
    catalog = api.post("/platform/buyer/returns", json={"token": token})
    assert catalog.status_code == 200
    assert "SKU1" in catalog.text
    sdk_catalog = api.post("/aftercare/returns", json=locator, headers=headers)
    assert sdk_catalog.status_code == 200 and "SKU1" in sdk_catalog.text
    order_id = catalog.json()["orders"][0]["id"]
    requested = api.post("/platform/buyer/returns/request", json={"token": token, "request_id": str(uuid4()), "order_id": order_id, "items": [{"product_id": "SKU1", "quantity": 1}], "reason": "Actual API validation on disposable QA data"})
    assert requested.status_code == 201, requested.text
    assurance = api.post("/platform/buyer/assurance", json={"token": token})
    assert assurance.status_code == 200
    assert set(assurance.json()) == {"journey", "context"}
    assert api.owner["token"] not in assurance.text


def test_resolution_dispute_alias_preserves_capture_hold(api):
    payment = api.post("/cases", json={"order_id": "RECORDED-QA-ORDER", "complaint": "Disposable recorded payment", "payment": {"capture_id": "RECORDEDQACAPTURE", "captured_amount": "1.00"}})
    assert payment.status_code == 201
    workspace = api.post("/resolution-cases", json={"title": "Recorded dispute alias", "refund_case_id": payment.json()["id"]})
    assert workspace.status_code == 201
    root = "/platform/cases/" + workspace.json()["id"]
    recorded = api.post(root + "/disputes", json={"provider": "merchant", "reference": "QA-DISPUTE", "event_id": str(uuid4()), "version": 1, "state": "open", "note": "Explicitly merchant-recorded QA evidence; no external provider claim"})
    assert recorded.status_code == 200, recorded.text
    assert api.get(root + "/disputes").json()["capture_held"] is True


def test_existing_merchant_claim_keeps_the_original_workspace(client):
    merchant = client.get("/auth/me").json()["id"]
    claim = client.post("/platform/account/claim", json={"name": "Claimed owner", "email": "claim@example.test", "password": "isolated-claim-password"})
    assert claim.status_code == 201, claim.text
    assert claim.json()["merchant"]["id"] == merchant
    session = {"Authorization": "Bearer " + claim.json()["token"]}
    assert client.get("/platform/me", headers=session).json()["role"] == "owner"
    assert client.post("/platform/account/claim", json={"name": "Again", "email": "other@example.test", "password": "isolated-claim-password"}).status_code == 409
