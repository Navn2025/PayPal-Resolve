"""Concrete merchant/buyer/developer assurance flows on disposable real application storage."""

import base64
from uuid import uuid4

from test_aftercare import setup_order, support_key, report
from test_platform_operations import buyer_link, invite, promise

pytest_plugins = ("test_platform_operations",)


def support(api):
    locator = setup_order(api)
    _, headers = support_key(api)
    response = api.post("/aftercare/issues", json=report(locator), headers=headers)
    assert response.status_code == 201, response.text
    return locator, headers, response.json()["case_id"]


def test_policy_inspection_and_saved_label_flow(api):
    locator, headers, case = support(api)
    policy = {
        "expected_revision": 0,
        "enabled": True,
        "window_days": 30,
        "inspection_required": True,
        "restocking_fee": "2.50",
        "shipping_paid_by": "merchant",
    }
    token = buyer_link(api, case)
    public = api.post("/platform/buyer/return-policy", json={"token": token})
    assert public.status_code == 200
    assert public.json()["restocking_fee"] is None
    assert public.json()["policy_enabled"] is False
    assert "excluded_products" not in public.json()
    assert api.put("/platform/return-policy", json=policy).status_code == 200
    public = api.post("/platform/buyer/return-policy", json={"token": token})
    assert public.json()["restocking_fee"] == "2.50"
    assert public.json()["window_days"] == 30
    assert api.put("/platform/return-policy", json=policy).status_code == 409
    agent = invite(api, "agent")
    assert (
        api.put(
            "/platform/return-policy",
            json={**policy, "expected_revision": 1},
            headers={"Authorization": "Bearer " + agent["token"]},
        ).status_code
        == 403
    )
    request = {
        **locator,
        "request_id": str(uuid4()),
        "items": [{"product_id": "SKU1", "quantity": 1}],
        "reason": "Damaged",
    }
    check = api.post(
        "/aftercare/returns/eligibility",
        json={k: v for k, v in request.items() if k not in ("request_id", "reason")},
        headers=headers,
    )
    assert check.status_code == 200, check.text
    assert check.json()["decision"] == "needs_review"
    assert check.json()["restocking_fee"] == "2.50"
    result = api.post("/aftercare/returns/request", json=request, headers=headers)
    assert result.status_code == 201, result.text
    assert (
        api.post("/aftercare/returns/request", json=request, headers=headers).json()
        == result.json()
    )
    identifier = result.json()["id"]
    root = f"/platform/cases/{case}/returns/{identifier}"
    assert (
        api.put(
            root, json={"expected_revision": 1, "action": "approve", "note": "Review"}
        ).status_code
        == 409
    )
    inspection = {
        "expected_revision": 1,
        "request_id": str(uuid4()),
        "finding": "clear",
        "quantities_match": True,
        "override_policy": True,
        "note": "Authorized policy exception reviewed",
    }
    assert (
        api.post(
            root + "/inspection",
            json=inspection,
            headers={"Authorization": "Bearer " + agent["token"]},
        ).status_code
        == 403
    )
    assert api.post(root + "/inspection", json=inspection).status_code == 200
    assert (
        api.put(
            root, json={"expected_revision": 1, "action": "approve", "note": "Reviewed"}
        ).status_code
        == 200
    )
    instructions = {
        "expected_revision": 0,
        "instructions": "Use the saved label. Keep the drop-off receipt.",
        "return_address": "Synthetic returns warehouse",
        "shipping_paid_by": "merchant",
    }
    assert api.put(root + "/guide", json=instructions).status_code == 200
    assert api.get(root + "/guide").json()["instructions"] == instructions["instructions"]
    raw = b"%PDF-1.4\nSynthetic saved label\n%%EOF"
    uploaded = api.post(
        root + "/labels",
        json={
            "filename": "return-label.pdf",
            "content_base64": base64.b64encode(raw).decode(),
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    assert (
        api.post(
            root + "/labels",
            json={
                "filename": "return-label.pdf",
                "content_base64": base64.b64encode(raw).decode(),
            },
        ).json()["id"]
        == uploaded.json()["id"]
    )
    guide = api.post(
        "/aftercare/returns/guide",
        json={**locator, "return_id": identifier},
        headers=headers,
    )
    assert guide.status_code == 200, guide.text
    assert guide.json()["instructions"] == instructions["instructions"]
    assert "Authorized policy" not in guide.text
    label = api.post(
        "/aftercare/returns/label",
        json={**locator, "return_id": identifier, "label_id": uploaded.json()["id"]},
        headers=headers,
    )
    assert base64.b64decode(label.json()["content_base64"]) == raw
    token = buyer_link(api, case)
    public_guide = api.post("/platform/buyer/returns/guide", json={"token": token, "return_id": identifier})
    assert public_guide.status_code == 200
    assert public_guide.json()["instructions"] == instructions["instructions"]
    assert (
        api.post(
            "/platform/buyer/returns/label",
            json={
                "token": token,
                "return_id": identifier,
                "label_id": uploaded.json()["id"],
            },
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/platform/buyer/returns/label",
            json={
                "token": token,
                "return_id": str(uuid4()),
                "label_id": uploaded.json()["id"],
            },
        ).status_code
        == 404
    )
    api.delete(f"/resolution-cases/{case}/customer-link")
    assert (
        api.post(
            "/platform/buyer/returns/label",
            json={
                "token": token,
                "return_id": identifier,
                "label_id": uploaded.json()["id"],
            },
        ).status_code
        == 404
    )
    for revision, action in [(2, "ship_return"), (3, "receive")]:
        body = {
            "expected_revision": revision,
            "action": action,
            "note": "Physical return recorded",
        }
        if action == "ship_return":
            body["shipment"] = {
                "carrier": "Synthetic",
                "tracking_code": "TRACK1",
                "reference": "SHIP1",
            }
        assert api.put(root, json=body).status_code == 200
    assert (
        api.put(
            root,
            json={
                "expected_revision": 4,
                "action": "pass_inspection",
                "note": "Not inspected",
            },
        ).status_code
        == 409
    )
    inspection.update(
        expected_revision=4, request_id=str(uuid4()), override_policy=False
    )
    assert api.post(root + "/inspection", json=inspection).status_code == 200
    assert (
        api.put(
            root,
            json={
                "expected_revision": 4,
                "action": "pass_inspection",
                "note": "Current inspection",
            },
        ).status_code
        == 200
    )


def test_issue_lookup_context_and_resumable_events(api):
    locator = setup_order(api)
    _, headers = support_key(api)
    payload = report(locator)
    first = api.post("/aftercare/issues", json=payload, headers=headers).json()
    assert (
        api.post(
            "/aftercare/issues/lookup",
            json={**locator, "request_id": payload["request_id"]},
            headers=headers,
        ).json()
        == first
    )
    assert (
        api.post(
            "/aftercare/issues/lookup",
            json={**locator, "request_id": str(uuid4())},
            headers=headers,
        ).status_code
        == 404
    )
    promise(api, first["case_id"])
    context = api.post("/aftercare/context", json=locator, headers=headers)
    assert context.status_code == 200, context.text
    assert context.json()["messages"][0]["body"] == payload["message"]
    assert "PRIVATE SYNTHETIC SOURCE" not in context.text
    first_page = api.post(
        "/aftercare/events",
        json={"source": locator["source"], "limit": 1},
        headers=headers,
    )
    assert first_page.status_code == 200, first_page.text
    initial = first_page.json()
    assert initial["items"][0]["revision"] == 1
    assert "PRIVATE SYNTHETIC SOURCE" not in first_page.text
    assert (
        api.post(
            "/aftercare/events",
            json={
                "source": locator["source"],
                "after_sequence": initial["next_after_sequence"],
            },
            headers=headers,
        ).json()["items"]
        == []
    )
    api.post(
        f"/resolution-cases/{first['case_id']}/customer-messages",
        json={"request_id": str(uuid4()), "body": "We are reviewing your report."},
    )
    changed = api.post(
        "/aftercare/events",
        json={
            "source": locator["source"],
            "after_sequence": initial["next_after_sequence"],
        },
        headers=headers,
    ).json()
    assert changed["items"][0]["revision"] == 2
    assert changed["items"][0]["sequence"] > initial["next_after_sequence"]
    assert (
        api.post(
            "/aftercare/events", json={"source": "another-store"}, headers=headers
        ).status_code
        == 403
    )
    assert (
        api.post(
            "/aftercare/events",
            json={"source": locator["source"], "after_sequence": -1},
            headers=headers,
        ).status_code
        == 422
    )


def test_dispute_hold_blocks_shared_capture_approvals_and_uncertain_retries(api):
    from test_refund_executions import LocalProvider, ready, submit

    provider = LocalProvider(api.owner["merchant"]["id"])
    api.app.state.paypal_client.close()
    api.app.state.paypal_client = provider
    case, execution = ready(api)
    provider.mode = "unknown_once"
    pending_execution = submit(api, case, execution).json()
    assert pending_execution["status"] == "unknown"
    assert len(provider.request_ids) == 1
    event = {
        "provider": "paypal",
        "reference": "DISPUTE-TEST",
        "event_id": "EVENT-1",
        "version": 3,
        "state": "open",
        "note": "Merchant recorded provider case",
    }
    result = api.post(f"/cases/{case}/disputes", json=event)
    assert result.status_code == 200, result.text
    assert api.post(f"/cases/{case}/disputes", json=event).json()["duplicate"] is True
    assert (
        api.post(
            f"/cases/{case}/disputes", json={**event, "note": "Changed"}
        ).status_code
        == 409
    )
    stale = api.post(
        f"/cases/{case}/disputes",
        json={**event, "event_id": "OLD", "version": 2, "state": "resolved_no_refund"},
    )
    assert stale.json()["outcome"] == "stale_ignored"
    assert api.get(f"/cases/{case}/disputes").json()["capture_held"] is True
    # Direct recovery POST cannot repeat an uncertain write while the capture is disputed.
    from app.executions import RefundExecutionService
    from app.errors import StoreError
    import pytest

    with pytest.raises(StoreError):
        RefundExecutionService(api.app.state.store, provider).retry(
            case, pending_execution["id"], api.owner["merchant"]["id"]
        )
    replay = submit(api, case, execution)
    assert replay.status_code in (200, 201, 409)
    assert len(provider.request_ids) == 1
    shared = api.post(
        "/cases",
        json={
            "order_id": "SHARED-AFTERCARE",
            "complaint": "Other case",
            "payment": {"capture_id": "EXECCAPTURE", "captured_amount": "100.00"},
            "commitment": {
                "amount": "100.00",
                "status": "accepted",
                "source_message": "Synthetic same capture",
            },
        },
    ).json()["id"]
    basis = api.get(f"/cases/{shared}/reconciliation").json()
    assert basis["status"] != "refund_required"
    assert (
        api.post(
            f"/cases/{case}/disputes",
            json={
                **event,
                "event_id": "CLOSE",
                "version": 4,
                "state": "resolved_refunded",
            },
        ).status_code
        == 200
    )
    assert (
        api.post(
            f"/cases/{case}/disputes",
            json={
                **event,
                "event_id": "ERASE",
                "version": 5,
                "state": "resolved_no_refund",
            },
        ).status_code
        == 409
    )


def test_refund_journey_trace_is_not_bank_receipt_and_dispute_checklists_differ(api):
    locator, headers, case = support(api)
    legacy = api.post(
        "/cases",
        json={
            "order_id": "AFTERCARE-1",
            "complaint": "Refund issue",
            "payment": {"capture_id": "JOURNEYCAPTURE", "captured_amount": "25.00"},
            "commitment": {
                "amount": "25.00",
                "status": "accepted",
                "source_message": "PRIVATE original promise",
            },
        },
    ).json()["id"]
    assert (
        api.put(
            f"/resolution-cases/{case}/payment-link", json={"refund_case_id": legacy}
        ).status_code
        == 200
    )
    promise(api, case, kind="refund")
    api.post(
        f"/cases/{legacy}/refunds",
        json={
            "refund_id": "TRACEPAYMENT",
            "capture_id": "JOURNEYCAPTURE",
            "amount": "25.00",
            "status": "pending",
        },
    )
    trace = {
        "request_id": str(uuid4()),
        "refund_id": "TRACEPAYMENT",
        "reference_type": "ARN",
        "reference": "TRACE123456",
        "stage": "bank_processing",
        "note": "PRIVATE bank tracing note",
    }
    response = api.post(f"/platform/cases/{case}/refund-traces", json=trace)
    assert response.status_code == 200, response.text
    assert (
        api.post(f"/platform/cases/{case}/refund-traces", json=trace).json()
        == response.json()
    )
    journey = api.post("/aftercare/journey", json=locator, headers=headers)
    assert journey.status_code == 200, journey.text
    assert journey.json()["bank_receipt_verified"] is False
    assert journey.json()["traces"][0]["source"] == "merchant_recorded"
    assert "PRIVATE" not in journey.text
    acknowledged = api.post("/aftercare/received", json=locator, headers=headers)
    assert acknowledged.json()["stage"] == "buyer_reports_received"
    assert acknowledged.json()["bank_receipt_verified"] is False
    a = api.post(
        f"/platform/cases/{case}/dispute-packages",
        json={"dispute_id": "DIFFERENT-1", "reason": "item_not_received"},
    )
    b = api.post(
        f"/platform/cases/{case}/dispute-packages",
        json={"dispute_id": "DIFFERENT-2", "reason": "not_as_described"},
    )
    assert a.status_code == b.status_code == 201, (a.text, b.text)
    assert {x["item"] for x in a.json()["checklist"]} != {
        x["item"] for x in b.json()["checklist"]
    }
    doc = {
        "request_id": str(uuid4()),
        "requirement": "product_description",
        "note": "Merchant description at purchase",
        "evidence_ids": [],
    }
    added = api.post(f"/platform/cases/{case}/dispute-documents", json=doc)
    assert added.status_code == 200, added.text
    assert (
        api.post(f"/platform/cases/{case}/dispute-documents", json=doc).json()
        == added.json()
    )
    c = api.post(
        f"/platform/cases/{case}/dispute-packages",
        json={"dispute_id": "DIFFERENT-2", "reason": "not_as_described"},
    )
    assert any(
        x["present"] and x["source"] == "merchant_recorded_document"
        for x in c.json()["checklist"]
    )
    assert (
        api.post(
            f"/platform/cases/{case}/dispute-packages/{b.json()['id']}/review"
        ).status_code
        == 409
    )


def test_confirmed_open_provider_dispute_cannot_be_cleared_by_manual_status(api):
    legacy = api.post(
        "/cases",
        json={
            "order_id": "KNOWN-DISPUTE",
            "complaint": "Review",
            "payment": {"capture_id": "KNOWNDISPUTE", "captured_amount": "25.00"},
            "commitment": {
                "amount": "25.00",
                "status": "accepted",
                "source_message": "Synthetic",
            },
        },
    ).json()["id"]
    resolution = api.post(
        "/resolution-cases",
        json={
            "title": "Known provider dispute",
            "order_reference": "KNOWN-DISPUTE",
            "refund_case_id": legacy,
        },
    ).json()["id"]
    promise = api.post(
        f"/resolution-cases/{resolution}/promises",
        json={
            "promise": "Track the provider dispute",
            "source_note": "Synthetic merchant agreement",
            "target": {"kind": "dispute_handoff", "paypal_dispute_id": "KNOWN-D1"},
            "requires": [],
        },
    ).json()
    assert "id" in promise, promise
    from app.resolution_workspace import ResolutionWorkspace

    with api.app.state.store.transaction(write=True) as db:
        case = ResolutionWorkspace._case(db, resolution, api.owner["merchant"]["id"])
        row = ResolutionWorkspace._promise(db, case, promise["id"])
        ResolutionWorkspace._event(
            db,
            case,
            "provider_observation",
            "provider_confirmed",
            {
                "proofs": [
                    {
                        "provider": "paypal",
                        "resource_id": "KNOWN-D1",
                        "status": "WAITING_FOR_SELLER_RESPONSE",
                        "outcome": "needs_review",
                        "detail": "Synthetic authenticated provider DTO",
                        "environment": "sandbox",
                    }
                ]
            },
            row,
        )
    assert (
        api.post(
            f"/cases/{legacy}/disputes",
            json={
                "provider": "paypal",
                "reference": "KNOWN-D1",
                "event_id": "MANUAL-CLOSE",
                "version": 1,
                "state": "resolved_no_refund",
                "note": "Manual status does not override an active provider observation",
            },
        ).status_code
        == 200
    )
    assert api.get(f"/cases/{legacy}/disputes").json()["capture_held"] is True
