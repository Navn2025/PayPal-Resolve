"""Transactional promises, evidence and read-only provider reconciliation."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from .approvals import invalidate_approvals
from .case_workspace import CaseWorkspace, now_text, provider_hold
from .errors import StoreError
from .paypal_history import PayPalHistoryService
from .resolution_models import (
    PromiseView,
    ProviderProof,
    RefundProgress,
    ResolutionBundle,
    ResolutionEvent,
    ResolutionPage,
    ResolutionSummary,
    ResolutionTimeline,
    ResolutionView,
)
from .resolution_providers import ResolutionProviders
from .resolution_state import (
    dependency_state,
    latest_proof,
    manual_return,
    observed_state,
    promises_for,
    terms_for,
)


MAX_PROMISES = 30
ZERO = Decimal("0.00")


class ResolutionWorkspace:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _case(connection, case_id, merchant_id):
        row = connection.execute(
            "SELECT * FROM resolution_cases WHERE id=? AND merchant_id=?",
            (str(case_id), str(merchant_id)),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Resolution case not found")
        return row

    @staticmethod
    def _promise(connection, case, promise_id):
        row = connection.execute(
            "SELECT * FROM resolution_promises WHERE id=? AND resolution_id=? AND merchant_id=?",
            (str(promise_id), case["id"], case["merchant_id"]),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Resolution promise not found")
        return row

    def _legacy(self, connection, case):
        return (
            self.store._require_case(
                connection, case["refund_case_id"], case["merchant_id"]
            )
            if case["refund_case_id"]
            else None
        )

    @staticmethod
    def _event(connection, case, kind, source, data, row=None):
        connection.execute(
            """INSERT INTO resolution_events
               (id,resolution_id,merchant_id,promise_id,revision,event_type,source,recorded_at,data_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                case["id"],
                case["merchant_id"],
                row["id"] if row else None,
                row["revision"] if row else None,
                kind,
                source,
                now_text(),
                json.dumps(data, separators=(",", ":")),
            ),
        )

    def create(self, merchant_id, payload):
        with self.store.transaction(write=True) as connection:
            self.store._require_merchant(connection, merchant_id)
            identifier = uuid4()
            if payload.refund_case_id:
                self.store._require_case(
                    connection, payload.refund_case_id, merchant_id
                )
                if connection.execute(
                    "SELECT 1 FROM resolution_cases WHERE merchant_id=? AND refund_case_id=?",
                    (str(merchant_id), str(payload.refund_case_id)),
                ).fetchone():
                    raise StoreError(
                        409, "Refund case is already linked to a resolution case"
                    )
            connection.execute(
                "INSERT INTO resolution_cases VALUES (?,?,?,?,?,?)",
                (
                    str(identifier),
                    str(merchant_id),
                    str(payload.refund_case_id) if payload.refund_case_id else None,
                    payload.title,
                    payload.order_reference,
                    now_text(),
                ),
            )
            case = self._case(connection, identifier, merchant_id)
            self._event(
                connection,
                case,
                "case_created",
                "merchant_recorded",
                payload.model_dump(mode="json"),
            )
            return self._view(connection, case)

    def list(self, merchant_id, limit, offset):
        with self.store.transaction() as connection:
            parameters = (str(merchant_id),)
            total = connection.execute(
                "SELECT count(*) FROM resolution_cases WHERE merchant_id=?", parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM resolution_cases WHERE merchant_id=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
            return ResolutionPage(
                items=[ResolutionSummary.model_validate(dict(row)) for row in rows],
                total=total,
                limit=limit,
                offset=offset,
            )

    def get(self, case_id, merchant_id):
        with self.store.transaction() as connection:
            return self._view(connection, self._case(connection, case_id, merchant_id))

    def _validate_terms(self, connection, case, terms, current=None):
        rows = promises_for(connection, case["id"])
        prior = {
            row["id"]: row
            for row in rows
            if current is None or row["sequence"] < current["sequence"]
        }
        if any(str(identifier) not in prior for identifier in terms.requires):
            raise StoreError(
                409,
                "Prerequisites must be earlier promises in the same resolution case",
            )
        target = terms.target
        legacy = self._legacy(connection, case)
        if target.kind == "refund":
            if not legacy:
                raise StoreError(409, "A refund promise requires a linked refund case")
            if target.amount > legacy.payment.captured_amount:
                raise StoreError(409, "Refund promise exceeds the captured amount")
            if not current and any(row["kind"] == "refund" for row in rows):
                raise StoreError(
                    409, "Use the existing cumulative refund promise for this capture"
                )
        if target.kind in ("replacement", "return") and not (
            case["order_reference"] or legacy
        ):
            raise StoreError(
                409, "A shipment promise requires an original order reference"
            )
        if target.kind == "dispute_handoff" and not legacy:
            raise StoreError(409, "A PayPal dispute requires a linked capture case")
        if target.kind == "billing_correction" and target.action != "cancel_invoice":
            if not legacy or not any(
                prior[str(identifier)]["kind"] == "refund"
                for identifier in terms.requires
            ):
                raise StoreError(
                    409,
                    "Charge correction requires the linked refund promise as a prerequisite",
                )
            if target.original_capture_id == legacy.payment.capture_id:
                raise StoreError(
                    409, "The other capture must differ from the charged capture"
                )

    def _gate(self, connection, case):
        from .resolution_state import refund_promise_gate

        legacy = self._legacy(connection, case)
        return refund_promise_gate(connection, legacy) if legacy else None

    def _invalidate_if_changed(self, connection, case, before):
        after = self._gate(connection, case)
        if before != after:
            legacy = self._legacy(connection, case)
            invalidate_approvals(
                connection,
                legacy.merchant_id,
                legacy.payment.capture_id,
                "Resolution promise or prerequisite evidence changed",
            )

    def add_promise(self, case_id, merchant_id, terms):
        with self.store.transaction(write=True) as connection:
            case = self._case(connection, case_id, merchant_id)
            if len(promises_for(connection, case_id)) >= MAX_PROMISES:
                raise StoreError(
                    409, f"A resolution case can hold at most {MAX_PROMISES} promises"
                )
            self._validate_terms(connection, case, terms)
            before = self._gate(connection, case)
            identifier, stamp = uuid4(), now_text()
            connection.execute(
                """INSERT INTO resolution_promises
                   (id,resolution_id,merchant_id,kind,revision,promise_json,created_at,updated_at)
                   VALUES (?,?,?,?,1,?,?,?)""",
                (
                    str(identifier),
                    case["id"],
                    str(merchant_id),
                    terms.target.kind,
                    terms.model_dump_json(),
                    stamp,
                    stamp,
                ),
            )
            row = self._promise(connection, case, identifier)
            self._event(
                connection,
                case,
                "promise_recorded",
                "merchant_recorded",
                terms.model_dump(mode="json"),
                row,
            )
            self._invalidate_if_changed(connection, case, before)
            return self._selected(connection, case, identifier)

    def revise(self, case_id, promise_id, merchant_id, terms, expected_revision):
        with self.store.transaction(write=True) as connection:
            case = self._case(connection, case_id, merchant_id)
            row = self._promise(connection, case, promise_id)
            if row["revision"] != expected_revision:
                raise StoreError(409, "Promise revision has changed; reload the case")
            if row["kind"] != terms.target.kind:
                raise StoreError(409, "A revision cannot change the remedy type")
            self._validate_terms(connection, case, terms, row)
            if terms == terms_for(row):
                return self._selected(connection, case, promise_id)
            before = self._gate(connection, case)
            connection.execute(
                "UPDATE resolution_promises SET revision=revision+1,promise_json=?,updated_at=? WHERE id=?",
                (terms.model_dump_json(), now_text(), row["id"]),
            )
            self._event(
                connection,
                case,
                "promise_revised",
                "merchant_recorded",
                terms.model_dump(mode="json"),
                self._promise(connection, case, promise_id),
            )
            self._invalidate_if_changed(connection, case, before)
            return self._selected(connection, case, promise_id)

    def add_evidence(self, case_id, promise_id, merchant_id, payload):
        with self.store.transaction(write=True) as connection:
            case = self._case(connection, case_id, merchant_id)
            row = self._promise(connection, case, promise_id)
            if row["revision"] != payload.expected_revision:
                raise StoreError(409, "Promise revision has changed; reload the case")
            if payload.finding != "note" and not manual_return(terms_for(row)):
                raise StoreError(
                    409, "Only an internal return milestone can be manually confirmed"
                )
            before = self._gate(connection, case)
            self._event(
                connection,
                case,
                "merchant_evidence",
                "merchant_recorded",
                payload.model_dump(mode="json"),
                row,
            )
            self._invalidate_if_changed(connection, case, before)
            return self._selected(connection, case, promise_id)

    @staticmethod
    def _event_sequence(row):
        return row["sequence"] if row else None

    def refresh(self, case_id, promise_id, merchant_id, paypal, expected_revision):
        with self.store.transaction() as connection:
            case = self._case(connection, case_id, merchant_id)
            row = self._promise(connection, case, promise_id)
            terms = terms_for(row)
            if row["revision"] != expected_revision:
                raise StoreError(409, "Promise revision has changed; reload the case")
            legacy = self._legacy(connection, case)
            prior = self._event_sequence(latest_proof(connection, row))
        if manual_return(terms) and terms.target.tracking is None:
            raise StoreError(
                409, "Record a warehouse or inspection finding for this promise"
            )
        try:
            if terms.target.kind == "refund":
                history, _ = PayPalHistoryService(self.store, paypal).refresh(
                    legacy.id, merchant_id
                )
                proofs = [
                    ProviderProof(
                        provider="paypal",
                        resource_id=history.capture_id,
                        status=history.capture_status,
                        outcome="fulfilled"
                        if history.completed_amount == terms.target.amount
                        else "needs_review"
                        if history.completed_amount > terms.target.amount
                        else "pending",
                        amount=history.completed_amount,
                        currency="USD",
                        environment="sandbox",
                        detail="Completed refunds in the verified PayPal order history",
                    )
                ]
            else:
                proofs = ResolutionProviders(paypal).read(
                    merchant_id, terms.target, legacy
                )
        except StoreError as error:
            if error.status_code in (404, 409, 502, 503, 504):
                self._save_refresh(
                    case_id,
                    promise_id,
                    merchant_id,
                    expected_revision,
                    prior,
                    "verification_failed",
                    "system",
                    {"detail": error.detail, "http_status": error.status_code},
                )
            raise
        return self._save_refresh(
            case_id,
            promise_id,
            merchant_id,
            expected_revision,
            prior,
            "provider_observation",
            "provider_confirmed",
            {"proofs": [p.model_dump(mode="json") for p in proofs]},
        )

    def _save_refresh(
        self, case_id, promise_id, merchant_id, revision, prior, event, source, data
    ):
        with self.store.transaction(write=True) as connection:
            case = self._case(connection, case_id, merchant_id)
            row = self._promise(connection, case, promise_id)
            if (
                row["revision"] != revision
                or self._event_sequence(latest_proof(connection, row)) != prior
            ):
                raise StoreError(
                    409,
                    "Promise or evidence changed during verification; refresh again",
                )
            before = self._gate(connection, case)
            self._event(connection, case, event, source, data, row)
            self._invalidate_if_changed(connection, case, before)
            return self._selected(connection, case, promise_id)

    def _refund_state(self, connection, legacy, terms, row):
        basis = self.store._reconcile(connection, legacy)
        observations = basis.refund_verifications
        completed = sum(
            (
                item.amount
                for item in observations
                if item.provider_status == "COMPLETED"
            ),
            ZERO,
        )
        pending = sum(
            (item.amount for item in observations if item.provider_status == "PENDING"),
            ZERO,
        )
        goal = terms.target.amount
        progress = RefundProgress(
            refund_case_id=legacy.id,
            captured_amount=legacy.payment.captured_amount,
            promised_amount=goal,
            provider_completed_amount=completed,
            provider_pending_amount=pending,
            outstanding_amount=max(goal - completed, ZERO),
            history_current=basis.paypal_history_current,
            refund_ids=[item.refund_id for item in observations],
            verified_remaining_refundable_amount=basis.paypal_refund_history.remaining_amount
            if basis.paypal_history_current
            else None,
        )
        state, source, reason, checked, proofs = observed_state(connection, row, terms)
        if observations:
            checked = max(item.checked_at for item in observations)
        if (
            completed > goal
            or basis.completed_refund_amount > completed
            or basis.pending_refund_amount > pending
            or legacy.commitment is None
            or legacy.commitment.status != "accepted"
            or legacy.commitment.amount != goal
            or provider_hold(connection, legacy.merchant_id, legacy.payment.capture_id)
            or basis.status in ("execution_failed", "promise_review")
            or state == "needs_review"
        ):
            return (
                "needs_review",
                "system",
                "Refund evidence or agreement requires review",
                checked,
                proofs,
                progress,
            )
        if basis.active_refund_execution_id or pending:
            return (
                "pending",
                "provider_confirmed" if observations else "system",
                "Waiting for the refund outcome",
                checked,
                proofs,
                progress,
            )
        if completed == goal:
            return (
                "fulfilled",
                "provider_confirmed",
                "PayPal confirmed the agreed refund amount",
                checked,
                proofs,
                progress,
            )
        return (
            "waiting",
            "provider_confirmed" if observations or proofs else source,
            "Part of the promised refund is still owed",
            checked,
            proofs,
            progress,
        )

    def _view(self, connection, case):
        earlier, views = {}, []
        legacy = self._legacy(connection, case)
        now = datetime.now(timezone.utc)
        for row in promises_for(connection, case["id"]):
            terms = terms_for(row)
            progress = None
            if row["kind"] == "refund":
                outcome, source, reason, checked, proofs, progress = self._refund_state(
                    connection, legacy, terms, row
                )
            else:
                outcome, source, reason, checked, proofs = observed_state(
                    connection, row, terms
                )
            prerequisite = dependency_state(terms, earlier)
            if prerequisite != "fulfilled" and outcome != "needs_review":
                outcome = (
                    "needs_review"
                    if progress and progress.provider_completed_amount > ZERO
                    else prerequisite
                )
                source, reason = "system", "A prerequisite promise is still unresolved"
            earlier[row["id"]] = outcome
            views.append(
                PromiseView(
                    id=row["id"],
                    revision=row["revision"],
                    terms=terms,
                    outcome=outcome,
                    evidence_source=source,
                    reason=reason,
                    checked_at=checked,
                    overdue=bool(
                        terms.due_at and terms.due_at < now and outcome != "fulfilled"
                    ),
                    provider_proofs=proofs,
                    refund_progress=progress,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )
        states = set(earlier.values())
        result = (
            "needs_review"
            if "needs_review" in states
            else "fulfilled"
            if states == {"fulfilled"}
            else ("pending" if "pending" in states else "waiting")
        )
        return ResolutionView(
            **ResolutionSummary.model_validate(dict(case)).model_dump(),
            outcome=result,
            promises=views,
        )

    def _selected(self, connection, case, promise_id):
        return next(
            item
            for item in self._view(connection, case).promises
            if str(item.id) == str(promise_id)
        )

    @staticmethod
    def _timeline(connection, case, limit, offset):
        total = connection.execute(
            "SELECT count(*) FROM resolution_events WHERE resolution_id=?",
            (case["id"],),
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM resolution_events WHERE resolution_id=? ORDER BY sequence DESC LIMIT ? OFFSET ?",
            (case["id"], limit, offset),
        )
        return ResolutionTimeline(
            items=[
                ResolutionEvent(
                    **dict(row),
                    actor_merchant_id=row["merchant_id"]
                    if row["source"] == "merchant_recorded"
                    else None,
                    data=json.loads(row["data_json"]),
                )
                for row in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    def timeline(self, case_id, merchant_id, limit, offset):
        with self.store.transaction() as connection:
            case = self._case(connection, case_id, merchant_id)
            result = self._timeline(connection, case, limit, offset)
        return self._refund_timeline(
            result, case["refund_case_id"], merchant_id, limit, offset
        )

    def _refund_timeline(self, timeline, refund_case_id, merchant_id, limit, offset):
        if refund_case_id:
            refund = self.store.timeline(
                refund_case_id, merchant_id, limit=limit, offset=offset
            )
            timeline.refund_items, timeline.refund_total = refund.items, refund.total
        return timeline

    def bundle(self, case_id, merchant_id, limit, offset):
        with self.store.transaction() as connection:
            case = self._case(connection, case_id, merchant_id)
            result = self._view(connection, case)
            timeline = self._timeline(connection, case, limit, offset)
        attachments = (
            CaseWorkspace(self.store).attachments(result.refund_case_id, merchant_id)
            if result.refund_case_id
            else []
        )
        timeline = self._refund_timeline(
            timeline, result.refund_case_id, merchant_id, limit, offset
        )
        return ResolutionBundle(
            case=result, timeline=timeline, refund_attachments=attachments
        )
