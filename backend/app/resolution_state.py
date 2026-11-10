"""Derive promise status and the refund approval gate from recorded evidence."""

import hashlib
import json
from dataclasses import dataclass

from .resolution_models import PromiseTerms


@dataclass(frozen=True)
class PromiseGate:
    fingerprint: str
    outcome: str


def terms_for(row):
    return PromiseTerms.model_validate_json(row["promise_json"])


def promises_for(connection, resolution_id):
    return connection.execute(
        "SELECT * FROM resolution_promises WHERE resolution_id=? ORDER BY sequence",
        (str(resolution_id),),
    ).fetchall()


def latest_proof(connection, row):
    return connection.execute(
        """SELECT * FROM resolution_events WHERE promise_id=? AND revision=?
           AND event_type IN ('provider_observation','verification_failed')
           ORDER BY sequence DESC LIMIT 1""",
        (row["id"], row["revision"]),
    ).fetchone()


def latest_finding(connection, row):
    return connection.execute(
        """SELECT * FROM resolution_events WHERE promise_id=? AND revision=?
           AND event_type='merchant_evidence' AND json_extract(data_json, '$.finding')!='note'
           ORDER BY sequence DESC LIMIT 1""",
        (row["id"], row["revision"]),
    ).fetchone()


def manual_return(terms):
    return (
        terms.target.kind == "return" and terms.target.milestone != "carrier_delivered"
    )


def observed_state(connection, row, terms):
    provider = latest_proof(connection, row)
    data = json.loads(provider["data_json"]) if provider else {}
    proofs = data.get("proofs", [])
    for proof in proofs:
        connection_state = connection.execute(
            "SELECT enabled,updated_at FROM platform_connections WHERE merchant_id=? AND provider=?",
            (row["merchant_id"], proof.get("provider")),
        ).fetchone()
        if connection_state and (not connection_state["enabled"] or provider["recorded_at"] < connection_state["updated_at"]):
            return "needs_review", "system", "Refresh provider evidence after the connection change", provider["recorded_at"], []
    if manual_return(terms):
        finding = latest_finding(connection, row)
        if finding:
            confirmed = json.loads(finding["data_json"])["finding"] == "confirmed"
            return (
                "fulfilled" if confirmed else "needs_review",
                "merchant_recorded",
                "Merchant confirmed the internal return milestone"
                if confirmed
                else "Merchant did not confirm the milestone",
                finding["recorded_at"],
                proofs,
            )
        return (
            "waiting",
            "merchant_recorded",
            "An internal warehouse or inspection check is required",
            provider["recorded_at"] if provider else None,
            proofs,
        )
    if provider:
        if provider["event_type"] == "verification_failed":
            return "needs_review", "system", data["detail"], provider["recorded_at"], []
        outcomes = {proof["outcome"] for proof in proofs}
        outcome = (
            "needs_review"
            if "needs_review" in outcomes
            else ("fulfilled" if outcomes == {"fulfilled"} else "pending")
        )
        reasons = {
            "needs_review": "The provider reported a state that requires review",
            "fulfilled": "The required provider evidence was confirmed",
            "pending": "The provider has not yet confirmed the promised result",
        }
        return (
            outcome,
            "provider_confirmed",
            reasons[outcome],
            provider["recorded_at"],
            proofs,
        )
    return (
        "waiting",
        "merchant_recorded",
        "Provider evidence has not been checked",
        None,
        [],
    )


def dependency_state(terms, earlier_outcomes):
    states = [earlier_outcomes[str(dependency)] for dependency in terms.requires]
    if "needs_review" in states:
        return "needs_review"
    return "waiting" if any(status != "fulfilled" for status in states) else "fulfilled"


def refund_promise_gate(connection, case):
    workspace = connection.execute(
        "SELECT id FROM resolution_cases WHERE merchant_id=? AND refund_case_id=?",
        (str(case.merchant_id), str(case.id)),
    ).fetchone()
    if not workspace:
        return None
    rows = promises_for(connection, workspace["id"])
    target = next((row for row in rows if row["kind"] == "refund"), None)
    if target is None:
        return None
    prior, revisions, dependencies = {}, {}, {}
    for row in rows:
        if row["id"] == target["id"]:
            break
        terms = terms_for(row)
        outcome = observed_state(connection, row, terms)[0]
        before = dependency_state(terms, prior)
        prior[row["id"]] = (
            before if outcome != "needs_review" and before != "fulfilled" else outcome
        )
        revisions[row["id"]] = [row["revision"], prior[row["id"]]]
        dependencies[row["id"]] = terms.requires
    terms = terms_for(target)
    relevant = set()
    stack = list(terms.requires)
    while stack:
        reference = str(stack.pop())
        if reference not in relevant:
            relevant.add(reference)
            stack.extend(dependencies[reference])
    outcome = dependency_state(terms, prior)
    offer = None
    for candidate in connection.execute(
        "SELECT * FROM platform_offers WHERE case_id=? ORDER BY revision DESC",
        (workspace["id"],),
    ):
        if any(c["promise_id"] == target["id"] for c in json.loads(candidate["choices_json"])):
            offer = candidate
            break
    offer_state = None
    if offer:
        choices = json.loads(offer["choices_json"])
        # A buyer offer is a separate agreement gate; it never creates an approval.
        refund_choices = [c for c in choices if c["promise_id"] == target["id"]]
        if refund_choices:
            selected = next((c for c in refund_choices if c["id"] == offer["selected_choice"]), None)
            offer_state = [offer["id"], offer["revision"], offer["status"], offer["selected_choice"]]
            if offer["status"] != "accepted" or not selected or selected["promise_revision"] != target["revision"]:
                outcome = "waiting"
    if (
        case.commitment is None
        or case.commitment.status != "accepted"
        or case.commitment.amount != terms.target.amount
        or case.commitment.currency != terms.target.currency
    ):
        outcome = "needs_review"
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                target["id"],
                target["revision"],
                outcome,
                offer_state,
                {key: revisions[key] for key in relevant},
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return PromiseGate(fingerprint, outcome)
