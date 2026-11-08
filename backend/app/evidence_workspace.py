"""Merchant-scoped idempotent evidence, kept separate from execution state."""

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import uuid4

from pydantic import BaseModel

from .case_workspace import CaseWorkspace, now_text
from .commerce_compare import commerce_report
from .errors import StoreError
from .evidence_models import (
    EvidenceBundle,
    EvidenceCaseView,
    EvidenceReceipt,
    EvidenceRefreshResult,
    EvidenceSummary,
    LinkedEvidenceRecord,
    PayPalEvidenceFact,
)
from .evidence_paypal import collect_paypal, issue
from .resolution_models import ResolutionCreate
from .resolution_workspace import ResolutionWorkspace


ZERO = Decimal("0.00")
PRIMARY = ("paypal_order", "paypal_capture")


class _State(BaseModel):
    check: EvidenceRefreshResult
    facts: list[PayPalEvidenceFact]


def _hash(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _state(db, case):
    row = db.execute(
        "SELECT * FROM resolution_evidence_state WHERE resolution_id=? AND merchant_id=?",
        (case["id"], case["merchant_id"]),
    ).fetchone()
    return (
        (row["started_at"], _State.model_validate_json(row["data_json"]))
        if row
        else (None, None)
    )


def _approval(db, case):
    row = db.execute(
        """SELECT e.id,e.recorded_at,e.data_json FROM resolution_evidence_events k
           JOIN resolution_events e ON e.id=k.event_id AND e.resolution_id=k.resolution_id AND e.merchant_id=k.merchant_id
           WHERE k.resolution_id=? AND k.merchant_id=? AND k.origin='merchant'
           AND json_extract(e.data_json,'$.evidence_type')='refund_approved'
           ORDER BY json_extract(e.data_json,'$.occurred_at') DESC,e.sequence DESC LIMIT 1""",
        (case["id"], case["merchant_id"]),
    ).fetchone()
    if not row:
        return None
    return EvidenceReceipt(
        id=row["id"], recorded_at=row["recorded_at"], **json.loads(row["data_json"])
    )


def _totals(facts):
    capture = next(
        (fact.amount for fact in facts if fact.kind == "paypal_capture"), None
    )
    refunds = [fact for fact in facts if fact.kind == "paypal_refund"]
    completed = sum(
        (fact.amount for fact in refunds if fact.status == "COMPLETED"), ZERO
    )
    pending = sum((fact.amount for fact in refunds if fact.status == "PENDING"), ZERO)
    return capture, completed, pending


def evidence_summary(db, case):
    started, current = _state(db, case)
    facts = current.facts if current else []
    approval = _approval(db, case)
    capture, completed, pending = _totals(facts)
    issues = (
        [item for item in current.check.issues if item.kind != "refund_confirmation"]
        if current
        else [
            issue(
                "provider_refresh",
                "The SDK has not checked the linked PayPal records yet.",
            )
        ]
    )
    if approval and completed < approval.amount:
        issues.append(
            issue(
                "refund_confirmation",
                "PayPal has not confirmed refunds totaling the recorded approval amount.",
            )
        )
    return EvidenceSummary(
        last_check_started_at=started,
        last_checked_at=current.check.checked_at if current else None,
        last_verified_at=max((fact.checked_at for fact in facts), default=None),
        order_history_verified=bool(current and current.check.order_history_verified),
        verified=facts,
        issues=issues,
        last_merchant_approval=approval,
        captured_amount=capture,
        provider_completed_amount=completed,
        provider_pending_amount=pending,
        refund_status="refunded"
        if capture and completed == capture
        else "partially_refunded"
        if completed
        else "pending"
        if pending
        else "unconfirmed",
    )


class EvidenceWorkspace:
    def __init__(self, store):
        self.store = store
        self.workspace = ResolutionWorkspace(store)

    def _view(self, db, case, view=None):
        ref = db.execute(
            "SELECT external_reference FROM resolution_evidence_refs WHERE resolution_id=? AND merchant_id=?",
            (case["id"], case["merchant_id"]),
        ).fetchone()
        view = view or self.workspace._view(db, case)
        return EvidenceCaseView(
            **view.model_dump(),
            external_reference=ref["external_reference"] if ref else None,
            evidence_summary=evidence_summary(db, case),
        )

    def get(self, case_id, merchant_id):
        with self.store.transaction() as db:
            return self._view(db, self.workspace._case(db, case_id, merchant_id))

    def upsert(self, merchant_id, payload):
        key = (str(merchant_id), payload.external_reference)
        case_payload = ResolutionCreate.model_validate(
            payload.model_dump(exclude={"external_reference"})
        )
        digest = _hash(case_payload.model_dump(mode="json"))
        with self.store.transaction(write=True) as db:
            existing = db.execute(
                "SELECT resolution_id,request_hash FROM resolution_evidence_refs WHERE merchant_id=? AND external_reference=?",
                key,
            ).fetchone()
            if existing:
                if existing["request_hash"] != digest:
                    raise StoreError(
                        409,
                        "The external case reference already has different case data",
                    )
                return self._view(
                    db, self.workspace._case(db, existing["resolution_id"], merchant_id)
                )
            case = self.workspace._create(db, merchant_id, case_payload)
            db.execute(
                """INSERT INTO resolution_evidence_refs (merchant_id,external_reference,resolution_id,request_hash)
                   VALUES (?,?,?,?)""",
                (*key, case["id"], digest),
            )
            return self._view(db, case)

    @staticmethod
    def _links(db, case):
        return [
            LinkedEvidenceRecord.model_validate(dict(row))
            for row in db.execute(
                """SELECT id,kind,reference,source,linked_at FROM resolution_evidence_links
                   WHERE resolution_id=? AND merchant_id=? ORDER BY linked_at,id""",
                (case["id"], case["merchant_id"]),
            )
        ]

    def link(self, case_id, merchant_id, payload):
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant_id)
            return self._link(db, case, payload)

    def _link(self, db, case, payload, *, reuse_association=False):
        links = self._links(db, case)
        for link in links:
            if link.kind == payload.kind and link.reference == payload.reference:
                if link.source != payload.source and not reuse_association:
                    raise StoreError(
                        409, "The linked record already has a different source"
                    )
                return link
        if payload.kind in PRIMARY and any(link.kind == payload.kind for link in links):
            raise StoreError(
                409, "The case already has a different PayPal order or capture"
            )
        if len(links) >= 32 or (
            payload.kind == "paypal_refund"
            and sum(link.kind == "paypal_refund" for link in links) >= 10
        ):
            raise StoreError(409, "The case has reached its linked record limit")
        legacy = self.workspace._legacy(db, case)
        if legacy and (
            (
                payload.kind == "paypal_capture"
                and payload.reference != legacy.payment.capture_id
            )
            or (payload.kind == "paypal_order" and payload.reference != legacy.order_id)
        ):
            raise StoreError(
                409, "The reference conflicts with the existing Resolve payment"
            )
        _, current = _state(db, case)
        if (
            payload.kind in PRIMARY
            and current
            and any(
                fact.kind == payload.kind and fact.reference != payload.reference
                for fact in current.facts
            )
        ):
            raise StoreError(
                409, "The reference conflicts with already verified PayPal evidence"
            )
        identifier, now = str(uuid4()), now_text()
        db.execute(
            """INSERT INTO resolution_evidence_links (id,resolution_id,merchant_id,kind,reference,source,linked_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                identifier,
                case["id"],
                case["merchant_id"],
                payload.kind,
                payload.reference,
                payload.source,
                now,
            ),
        )
        return LinkedEvidenceRecord(
            **payload.model_dump(), id=identifier, linked_at=now
        )

    def _event(self, db, case, origin, source, key, digest, data):
        identity = (case["id"], case["merchant_id"], origin, source, key)
        existing = db.execute(
            """SELECT k.payload_hash,e.id,e.recorded_at FROM resolution_evidence_events k
               JOIN resolution_events e ON e.id=k.event_id
               WHERE k.resolution_id=? AND k.merchant_id=? AND k.origin=? AND k.source=? AND k.event_key=?""",
            identity,
        ).fetchone()
        if existing:
            if existing["payload_hash"] != digest:
                raise StoreError(
                    409, "The source event ID already has different evidence"
                )
            return existing["id"], existing["recorded_at"]
        event_id = self.workspace._event(
            db,
            case,
            "merchant_evidence" if origin == "merchant" else "provider_observation",
            "merchant_recorded" if origin == "merchant" else "provider_confirmed",
            data,
        )
        db.execute(
            """INSERT INTO resolution_evidence_events
               (resolution_id,merchant_id,origin,source,event_key,payload_hash,event_id) VALUES (?,?,?,?,?,?,?)""",
            (*identity, digest, event_id),
        )
        return event_id, db.execute(
            "SELECT recorded_at FROM resolution_events WHERE id=?", (event_id,)
        ).fetchone()[0]

    def add(self, case_id, merchant_id, payload):
        data = payload.model_dump(mode="json")
        data["occurred_at"] = payload.occurred_at.isoformat(timespec="microseconds")
        data["verification"] = "merchant_reported"
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant_id)
            event_id, recorded_at = self._event(
                db,
                case,
                "merchant",
                payload.source,
                payload.source_event_id,
                _hash(data),
                data,
            )
            return EvidenceReceipt(**data, id=event_id, recorded_at=recorded_at)

    def _snapshot(self, db, case):
        links = self._links(db, case)
        legacy = self.workspace._legacy(db, case)
        return (
            links,
            legacy.payment if legacy else None,
            legacy.order_id if legacy else None,
        )

    def refresh(self, case_id, merchant_id, client):
        started = now_text()
        with self.store.transaction() as db:
            case = self.workspace._case(db, case_id, merchant_id)
            snapshot = self._snapshot(db, case)
        links, payment, prior_order = snapshot
        refs = {link.kind: link.reference for link in links if link.kind in PRIMARY}
        capture = refs.get("paypal_capture") or (
            payment.capture_id if payment else None
        )
        order = refs.get("paypal_order") or prior_order
        refunds = [link.reference for link in links if link.kind == "paypal_refund"]
        if payment and (capture != payment.capture_id or order != prior_order):
            found, issues, complete = (
                [],
                [
                    issue(
                        "paypal_connection",
                        "The linked references conflict with the existing Resolve payment.",
                        status="mismatch",
                    )
                ],
                False,
            )
        else:
            found, issues, complete = collect_paypal(
                client,
                merchant_id,
                order,
                capture,
                refunds,
                payment.captured_amount if payment else None,
            )
        issues.extend(
            issue(
                link.kind,
                "This reference is recorded only; there is no verification adapter in this SDK.",
                reference=link.reference,
                status="unsupported",
            )
            for link in links
            if not link.kind.startswith("paypal_")
        )
        checked = datetime.now(timezone.utc)
        verified = [PayPalEvidenceFact(**fact, checked_at=checked) for fact in found]
        with self.store.transaction(write=True) as db:
            case = self.workspace._case(db, case_id, merchant_id)
            if self._snapshot(db, case) != snapshot:
                raise StoreError(
                    409, "Linked payment records changed during refresh; try again"
                )
            previous_started, previous = _state(db, case)
            if previous_started and previous_started > started:
                return previous.check
            anchored = (
                {
                    fact.kind: fact.reference
                    for fact in previous.facts
                    if fact.kind in PRIMARY
                }
                if previous
                else {}
            )
            if any(
                fact.kind in anchored and fact.reference != anchored[fact.kind]
                for fact in verified
            ):
                verified, complete = [], False
                issues.append(
                    issue(
                        "paypal_connection",
                        "The newly returned payment differs from the verified payment on this case.",
                        status="mismatch",
                    )
                )
            facts = (
                {(fact.kind, fact.reference): fact for fact in previous.facts}
                if previous
                else {}
            )
            if complete:
                # A reconciled order defines the current refund set. Older facts
                # remain in the append-only timeline even if no longer listed.
                facts = {
                    key: fact
                    for key, fact in facts.items()
                    if fact.kind != "paypal_refund"
                }
            for fact in verified:
                stable = fact.model_dump(mode="json", exclude={"checked_at"})
                digest = _hash(stable)
                self._event(
                    db,
                    case,
                    "paypal",
                    "paypal_sandbox",
                    digest,
                    digest,
                    fact.model_dump(mode="json"),
                )
                facts[(fact.kind, fact.reference)] = fact
            _, completed, _ = _totals(facts.values())
            approval = _approval(db, case)
            refresh_issues = list(issues)
            if approval and completed < approval.amount:
                refresh_issues.append(
                    issue(
                        "refund_confirmation",
                        "PayPal has not confirmed refunds totaling the recorded approval amount.",
                    )
                )
            result = EvidenceRefreshResult(
                checked_at=checked,
                verified=verified,
                issues=refresh_issues,
                order_history_verified=complete,
            )
            state = _State(check=result, facts=list(facts.values()))
            db.execute(
                """INSERT INTO resolution_evidence_state (resolution_id,merchant_id,started_at,data_json) VALUES (?,?,?,?)
                   ON CONFLICT(resolution_id) DO UPDATE SET started_at=excluded.started_at,data_json=excluded.data_json""",
                (case["id"], case["merchant_id"], started, state.model_dump_json()),
            )
            return result

    def bundle(self, case_id, merchant_id, limit, offset):
        with self.store.transaction() as db:
            case = self.workspace._case(db, case_id, merchant_id)
            view = self._view(db, case)
            links = self._links(db, case)
            commerce = commerce_report(db, case, view.evidence_summary)
            timeline = self.workspace._timeline(db, case, limit, offset)
        timeline = self.workspace._refund_timeline(
            timeline, view.refund_case_id, merchant_id, limit, offset
        )
        return EvidenceBundle(
            case=view,
            linked_records=links,
            commerce=commerce,
            timeline=timeline,
            refund_attachments=CaseWorkspace(self.store).attachments(
                view.refund_case_id, merchant_id
            )
            if view.refund_case_id
            else [],
        )


def buyer_evidence_milestones(db, case):
    """Fixed labels only. Never return notes, amounts or provider identifiers."""
    approval = _approval(db, case)
    _, current = _state(db, case)
    milestones = []
    if approval:
        milestones.append(
            (
                "Merchant recorded a refund approval",
                approval.occurred_at,
                "merchant_recorded",
            )
        )
    if current:
        capture, completed, pending = _totals(current.facts)
        if completed:
            checks = [
                fact.checked_at
                for fact in current.facts
                if fact.kind == "paypal_refund" and fact.status == "COMPLETED"
            ]
            label = (
                "PayPal confirmed a refund"
                if capture == completed
                else "PayPal confirmed a partial refund"
            )
            milestones.append((label, max(checks), "provider_confirmed"))
        if pending:
            checks = [
                fact.checked_at
                for fact in current.facts
                if fact.kind == "paypal_refund" and fact.status == "PENDING"
            ]
            milestones.append(
                ("PayPal reports a refund pending", max(checks), "provider_confirmed")
            )
    return milestones
