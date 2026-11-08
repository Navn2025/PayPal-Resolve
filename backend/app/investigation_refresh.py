"""One server-authorized linked Sandbox resource read, never model-supplied URLs."""

from datetime import datetime, timezone
from uuid import UUID

from .case_workspace import now_text
from .errors import StoreError
from .evidence_models import EvidenceRefreshResult, PayPalEvidenceFact
from .evidence_paypal import _fact, issue
from .evidence_workspace import EvidenceWorkspace, _State, _hash, _state


def refresh_linked(store, paypal, case_id, merchant_id, selection):
    workspace = EvidenceWorkspace(store)
    with store.transaction() as db:
        case = workspace.workspace._case(db, case_id, merchant_id)
        links = workspace._links(db, case)
        linked = next((l for l in links if l.id == selection.evidence_id), None)
        expected = (
            "paypal_capture"
            if selection.operation == "refresh_linked_capture"
            else "paypal_refund"
        )
        if not linked or linked.kind != expected:
            raise StoreError(403, "The requested resource is not linked to this case")
        _, prior = _state(db, case)
        captures = [l.reference for l in links if l.kind == "paypal_capture"]
        capture = (
            next((f for f in prior.facts if f.kind == "paypal_capture"), None)
            if prior
            else None
        )
        if expected == "paypal_refund" and (
            not capture or captures != [capture.reference]
        ):
            raise StoreError(
                409, "A verified linked capture is required before reading a refund"
            )
    checked, found, issues = datetime.now(timezone.utc), [], []
    try:
        cfg = paypal._merchant_configuration(UUID(str(merchant_id)))
        token = paypal._access_token(cfg)
        resource = (
            paypal._capture_resource(linked.reference, token)[0]
            if expected == "paypal_capture"
            else paypal._refund_resource(
                capture.reference, capture.amount, linked.reference, token
            )
        )
        found = [
            PayPalEvidenceFact(
                **_fact(
                    expected,
                    resource,
                    linked.reference
                    if expected == "paypal_capture"
                    else capture.reference,
                ),
                checked_at=checked,
            )
        ]
        if (
            capture
            and expected == "paypal_capture"
            and (
                found[0].amount != capture.amount
                or found[0].currency != capture.currency
            )
        ):
            raise StoreError(409, "Capture amount changed")
    except StoreError:
        found = []
        issues = [
            issue(
                "provider_refresh",
                "The authorized Sandbox read failed; prior verified evidence is preserved.",
                status="unavailable",
            )
        ]
    with store.transaction(write=True) as db:
        case = workspace.workspace._case(db, case_id, merchant_id)
        if workspace._links(db, case) != links or _state(db, case)[1] != prior:
            raise StoreError(409, "Evidence changed during the authorized read")
        facts = {(f.kind, f.reference): f for f in prior.facts} if prior else {}
        for fact in found:
            digest = _hash(fact.model_dump(mode="json", exclude={"checked_at"}))
            workspace._event(
                db,
                case,
                "paypal",
                "paypal_sandbox",
                digest,
                digest,
                fact.model_dump(mode="json"),
            )
            facts[(fact.kind, fact.reference)] = fact
        # A single resource cannot re-establish the completeness of order history.
        check = EvidenceRefreshResult(
            checked_at=checked,
            verified=found,
            issues=issues,
            order_history_verified=False,
        )
        state = _State(check=check, facts=list(facts.values()))
        db.execute(
            """INSERT INTO resolution_evidence_state VALUES (?,?,?,?) ON CONFLICT(resolution_id)
            DO UPDATE SET started_at=excluded.started_at,data_json=excluded.data_json""",
            (str(case_id), str(merchant_id), now_text(), state.model_dump_json()),
        )
        return check
