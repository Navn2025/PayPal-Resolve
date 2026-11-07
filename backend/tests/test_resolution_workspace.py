from uuid import uuid4


def refund_case(client, capture="TESTRESOLUTION", order="TESTORDER", goal="30.00"):
    response = client.post(
        "/cases",
        json={
            "order_id": order,
            "complaint": "Resolution workflow test",
            "payment": {"capture_id": capture, "captured_amount": "100.00"},
            "commitment": {
                "amount": goal,
                "status": "accepted",
                "source_message": "Test agreement",
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def workspace(client, *, linked=None, order="STOREORDER1"):
    response = client.post(
        "/resolution-cases",
        json={
            "title": "Track the agreement",
            "order_reference": order,
            "refund_case_id": linked,
        },
    )
    assert response.status_code == 201, response.text
    return "/resolution-cases/" + response.json()["id"]


def record(client, url, target, **fields):
    response = client.post(
        url + "/promises",
        json={
            "promise": "Do the agreed remedy",
            "source_note": "Confirmed by customer support",
            "target": target,
            **fields,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def approval(client, refund, capture, amount="30.00"):
    state = client.get(f"/cases/{refund}/reconciliation").json()
    return client.post(
        f"/cases/{refund}/refund-approvals",
        json={
            "request_id": str(uuid4()),
            "capture_id": capture,
            "amount": amount,
            "decision_note": "Approve for test",
            "state_fingerprint": state["state_fingerprint"],
        },
    )


def finding(client, url, promise, state, revision=1):
    return client.post(
        f"{url}/promises/{promise['id']}/evidence",
        json={
            "expected_revision": revision,
            "finding": state,
            "note": "Warehouse operator's finding",
            "reference": "WAREHOUSE-1",
        },
    )


def test_return_attestation_gates_refund_and_later_correction_invalidates_approval(
    client,
):
    capture = "TESTRESOLUTION"
    refund = refund_case(client, capture)
    url = workspace(client, linked=refund)
    returned = record(
        client,
        url,
        {
            "kind": "return",
            "milestone": "inspection_passed",
            "return_reference": "RMA1",
        },
    )
    cash = record(
        client, url, {"kind": "refund", "amount": "30.00"}, requires=[returned["id"]]
    )
    assert cash["outcome"] == "waiting"
    basis_url = f"/cases/{refund}/reconciliation"
    assert client.get(basis_url).json()["status"] == "awaiting_prerequisite"
    assert approval(client, refund, capture).status_code == 409

    assert finding(client, url, returned, "note").status_code == 201
    assert approval(client, refund, capture).status_code == 409
    accepted = finding(client, url, returned, "confirmed")
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["outcome"] == "fulfilled"
    assert accepted.json()["evidence_source"] == "merchant_recorded"
    approved = approval(client, refund, capture)
    assert approved.status_code == 201, approved.text

    assert (
        finding(client, url, returned, "not_confirmed").json()["outcome"]
        == "needs_review"
    )
    assert client.get(basis_url).json()["status"] == "promise_review"
    approval_url = f"/cases/{refund}/refund-approvals/{approved.json()['id']}"
    assert client.get(approval_url).json()["status"] == "invalidated"
    bundle = client.get(url + "/evidence-bundle").json()
    assert bundle["case"]["outcome"] == "needs_review"
    assert any(e["source"] == "approval" for e in bundle["timeline"]["refund_items"])
    assert {e["source"] for e in bundle["timeline"]["items"]} == {"merchant_recorded"}


def test_revision_ignores_old_proof_preserves_audit_and_rejects_future_dependency(
    client,
):
    url = workspace(client)
    first = record(
        client,
        url,
        {
            "kind": "return",
            "milestone": "warehouse_received",
            "return_reference": "RMA1",
        },
    )
    second = record(
        client,
        url,
        {
            "kind": "return",
            "milestone": "inspection_passed",
            "return_reference": "RMA1",
        },
        requires=[first["id"]],
    )
    assert finding(client, url, first, "confirmed").status_code == 201
    assert finding(client, url, second, "confirmed").json()["outcome"] == "fulfilled"
    uri = f"{url}/promises/{first['id']}"
    revision = {**first["terms"], "expected_revision": 1, "requires": [second["id"]]}
    assert client.put(uri, json=revision).status_code == 409
    revision.update(requires=[], promise="Check a corrected return reference")
    revision["target"]["return_reference"] = "RMA2"
    changed = client.put(uri, json=revision)
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 2 and changed.json()["outcome"] == "waiting"
    assert client.put(uri, json=revision).status_code == 409
    assert finding(client, url, first, "confirmed").status_code == 409
    assert client.get(url).json()["promises"][1]["outcome"] == "waiting"
    events = client.get(url + "/timeline").json()["items"]
    assert any(
        e["event_type"] == "merchant_evidence" and e["revision"] == 1 for e in events
    )
    assert any(
        e["event_type"] == "promise_revised" and e["revision"] == 2 for e in events
    )


def test_captureless_cases_tenant_boundaries_and_no_fake_provider_confirmation(client):
    url = workspace(client, order=None)
    promise = record(
        client,
        url,
        {
            "kind": "subscription",
            "action": "cancel",
            "paypal_subscription_id": "I-TEST",
        },
        due_at="2020-01-01T00:00:00Z",
    )
    assert promise["overdue"] and promise["evidence_source"] == "merchant_recorded"
    assert finding(client, url, promise, "confirmed").status_code == 409
    other = client.app.state.store.create_merchant("Other merchant")
    headers = {"Authorization": "Bearer " + other.api_key}
    for suffix in ("", "/timeline", "/evidence-bundle"):
        assert client.get(url + suffix, headers=headers).status_code == 404
    assert client.get("/resolution-cases", headers=headers).json()["total"] == 0
    endpoint = f"{url}/promises/{promise['id']}/refresh"
    assert (
        client.post(
            endpoint, headers=headers, json={"expected_revision": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            url + "/promises",
            json={
                **promise["terms"],
                "evidence_source": "provider_confirmed",
            },
        ).status_code
        == 422
    )


def test_manual_refund_ledger_does_not_fulfill_a_provider_verified_promise(client):
    refund = refund_case(client)
    url = workspace(client, linked=refund)
    promise = record(client, url, {"kind": "refund", "amount": "30.00"})
    assert promise["outcome"] == "waiting"
    manual = client.post(
        f"/cases/{refund}/refunds",
        json={
            "refund_id": "MANUAL1",
            "capture_id": "TESTRESOLUTION",
            "amount": "30.00",
            "currency": "USD",
            "status": "completed",
        },
    )
    assert manual.status_code == 201, manual.text
    state = client.get(url).json()["promises"][0]
    assert state["outcome"] == "needs_review"
    assert state["refund_progress"]["provider_completed_amount"] == "0.00"
    assert state["refund_progress"]["outstanding_amount"] == "30.00"
