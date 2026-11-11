"""End-to-end evaluation of the README evaluation plan on SYNTHETIC data only.

Every merchant, case, payment, amount and delay here is generated from a fixed seed. PayPal is a
local synthetic provider (no network); provider refunds are recorded through the store's own
recorder, exactly as the backend tests do. No AI provider is called: the extraction and injection
figures are read from result files recorded earlier and are labelled with their own provenance.

    uv run python evals/run_e2e_eval.py [--seed 11] [--cases 30] [--date 2026-11-11]

Writes results/e2e_<date>.json and results/e2e_<date>.md. Exit code 1 if any check fails.
"""

import argparse
import json
import random
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_resolution_eval import run as resolution_time

from app.main import create_app
from app.paypal import PayPalCaptureDetails, PayPalRefundDetails, PayPalWriteError
from app.settings import Settings
from app.worker import run_once

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
LABEL = "SYNTHETIC - local simulation; no PayPal, no AI provider, no real merchant data"
D = Decimal
CENT = D("0.01")
# Extraction/injection results recorded earlier; reported with their own labels, never re-run here.
EXTRACTION_SOURCES = {
    "extraction": "extraction_2026-11-08_r1.json",
    "injection_stability": "extraction_2026-11-08_injection_stability_partial.json",
}


class SyntheticPayPal:
    """A local stand-in for the PayPal Sandbox client: synthetic captures and refunds, no network."""

    def __init__(self, merchant_id: str, captured: str = "100.00"):
        self.settings = Settings(
            _env_file=None, paypal_sandbox_enabled=True, paypal_sandbox_refunds_enabled=True,
            paypal_resolve_merchant_id=merchant_id, paypal_sandbox_client_id="synthetic-client",
            paypal_sandbox_merchant_id="SYNTHSELLER",
        )
        self.captured = captured
        self.mode = "completed"
        self.request_ids: list[str] = []
        self.refunds: dict[str, PayPalRefundDetails] = {}

    def close(self):
        pass

    def capture(self, capture_id: str, amount: str | None = None) -> PayPalCaptureDetails:
        return PayPalCaptureDetails.model_validate({
            "id": capture_id, "amount": {"value": amount or self.captured, "currency_code": "USD"},
            "status": "COMPLETED", "payee": {"merchant_id": "SYNTHSELLER"}})

    def read_capture(self, case):
        return self.capture(case.payment.capture_id, str(case.payment.captured_amount))

    def refund_capture(self, case, request_id):
        self.request_ids.append(request_id)
        if request_id not in self.refunds:
            self.refunds[request_id] = PayPalRefundDetails.model_validate({
                "id": f"SYNTHREFUND{len(self.refunds) + 1}",
                "amount": {"value": str(case.commitment.amount), "currency_code": "USD"},
                "status": "COMPLETED",
                "links": [{"rel": "up", "method": "GET",
                           "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/" + case.payment.capture_id}],
            })
        if self.mode == "interrupt_once":
            # The provider accepted the refund, but the response never reached Resolve.
            self.mode = "completed"
            raise PayPalWriteError(503, "synthetic interruption", outcome_unknown=True)
        return self.refunds[request_id]

    def read_refund(self, case, refund_id):
        for refund in self.refunds.values():
            if refund.id == refund_id:
                return refund
        raise LookupError(refund_id)


class Harness:
    def __init__(self, folder: Path, seed: int):
        self.app = create_app(folder / "e2e.sqlite3")
        self.store = self.app.state.store
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.key = self.store.create_merchant("Synthetic e2e merchant").api_key
        self.client.headers["Authorization"] = f"Bearer {self.key}"
        self.merchant_id = self.client.get("/auth/me").json()["id"]
        self.paypal = SyntheticPayPal(self.merchant_id)
        self.app.state.paypal_client.close()
        self.app.state.paypal_client = self.paypal
        self.seed = seed
        self.counter = 0

    def close(self):
        self.client.__exit__(None, None, None)

    def capture_id(self) -> str:
        self.counter += 1
        return f"SYNTHE2E{self.seed}C{self.counter}"

    def payment(self, captured="100.00", agreed: str | None = None, capture: str | None = None) -> dict:
        capture = capture or self.capture_id()
        body = {"order_id": "ORDER-" + capture, "complaint": "Synthetic e2e case",
                "payment": {"capture_id": capture, "captured_amount": captured}}
        if agreed is not None:
            body["commitment"] = {"amount": agreed, "status": "accepted", "source_message": "Synthetic agreement"}
        response = self.client.post("/cases", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def resolution(self, payment_id: str | None = None) -> str:
        body = {"title": "Synthetic e2e case", **({"refund_case_id": payment_id} if payment_id else {})}
        response = self.client.post("/resolution-cases", json=body)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def refund_promise(self, case_id: str, amount: str, due_at: datetime | None = None):
        return self.client.post(f"/resolution-cases/{case_id}/promises", json={
            "promise": f"Refund ${amount}", "source_note": "Synthetic support chat",
            "target": {"kind": "refund", "amount": amount},
            **({"due_at": due_at.isoformat()} if due_at else {})})

    def provider_refund(self, payment_id: str, refund_id: str, amount: str, status="COMPLETED"):
        with self.store.transaction(write=True) as connection:
            case = self.store._require_case(connection, UUID(payment_id), UUID(self.merchant_id))
            self.store._record_provider_refund(connection, case, PayPalRefundDetails(
                id=refund_id, amount={"value": amount, "currency_code": "USD"}, status=status, links=[]))

    def reconciliation(self, payment_id: str) -> dict:
        return self.client.get(f"/cases/{payment_id}/reconciliation").json()

    def verify_capture(self, payment: dict, amount: str | None = None):
        self.store.record_capture_verification(UUID(payment["id"]), UUID(payment["merchant_id"]),
                                               self.paypal.capture(payment["payment"]["capture_id"], amount))

    def approve(self, payment_id: str, amount: str, capture: str):
        basis = self.reconciliation(payment_id)
        return self.client.post(f"/cases/{payment_id}/refund-approvals", json={
            "request_id": str(uuid4()), "capture_id": capture, "amount": amount,
            "state_fingerprint": basis["state_fingerprint"], "decision_note": "Synthetic merchant consent."})


class Scenario:
    def __init__(self, metric: str, readme: str):
        self.metric, self.readme, self.checks = metric, readme, []

    def check(self, name: str, expected, observed):
        self.checks.append({"name": name, "expected": _plain(expected), "observed": _plain(observed),
                            "passed": _plain(expected) == _plain(observed)})

    def result(self, **extra) -> dict:
        passed = sum(item["passed"] for item in self.checks)
        return {"metric": self.metric, "readme": self.readme, "checks": self.checks,
                "passed": passed, "total": len(self.checks), **extra}


def _plain(value):
    if isinstance(value, Decimal):
        return str(value.quantize(CENT))
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


# 1. Case-to-payment matching ---------------------------------------------------------------------

def matching(h: Harness) -> dict:
    s = Scenario("case_to_payment_matching", "Correct matching between cases and payments")
    payment = h.payment()
    case_id = h.resolution()
    linked = h.client.put(f"/resolution-cases/{case_id}/payment-link", json={"refund_case_id": payment["id"]})
    s.check("a payment links to its case", 200, linked.status_code)
    s.check("linking the same payment again is a no-op", 200,
            h.client.put(f"/resolution-cases/{case_id}/payment-link", json={"refund_case_id": payment["id"]}).status_code)
    other = h.payment()
    s.check("a case cannot take a second payment", 409,
            h.client.put(f"/resolution-cases/{case_id}/payment-link", json={"refund_case_id": other["id"]}).status_code)
    second_case = h.resolution()
    s.check("a payment cannot be linked to a second case", 409,
            h.client.put(f"/resolution-cases/{second_case}/payment-link", json={"refund_case_id": payment["id"]}).status_code)
    foreign_key = h.store.create_merchant("Synthetic other merchant").api_key
    foreign = h.client.post("/cases", headers={"Authorization": f"Bearer {foreign_key}"}, json={
        "order_id": "ORDER-FOREIGN", "complaint": "Other merchant", "payment": {"capture_id": h.capture_id(), "captured_amount": "50.00"}})
    s.check("another merchant's payment is not found", 404,
            h.client.put(f"/resolution-cases/{second_case}/payment-link", json={"refund_case_id": foreign.json()["id"]}).status_code)
    s.check("a refund promise above the captured amount is rejected", 409,
            h.refund_promise(case_id, "100.01").status_code)
    try:
        h.verify_capture(payment, "90.00")
        outcome = "accepted"
    except Exception as error:  # noqa: BLE001 - the observed outcome is the result
        outcome = type(error).__name__ + ":" + str(getattr(error, "status_code", ""))
    s.check("a PayPal capture whose amount differs from the payment is refused", "StoreError:409", outcome)
    return s.result()


# 2. Incomplete refund detection (seeded) --------------------------------------------------------

def expected_status(promised: Decimal, refunded: Decimal, overdue: bool) -> str:
    """The README rule, written independently of app.promise_health: kept when nothing is owed;
    otherwise the deadline and any refund so far decide."""
    if refunded >= promised:
        return "kept"
    if overdue:
        return "at_risk" if refunded > 0 else "broken"
    return "partially_kept" if refunded > 0 else "at_risk"


def incomplete_detection(h: Harness, rng: random.Random, cases: int) -> dict:
    s = Scenario("incomplete_refund_detection", "Detection of incomplete refund commitments")
    now = datetime.now(UTC)
    confusion = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    statuses_right = 0
    for index in range(cases):
        promised = D(rng.randrange(1000, 9000)) / 100
        shape = rng.choice(["none", "partial", "full", "over_two"])
        refunded = {"none": D(0), "partial": (promised * D(rng.uniform(0.1, 0.9))).quantize(CENT),
                    "full": promised, "over_two": promised}[shape]
        overdue = rng.random() < 0.5
        payment = h.payment(captured="100.00", agreed=str(promised))
        case_id = h.resolution(payment["id"])
        due = now + (timedelta(days=-2) if overdue else timedelta(days=5))
        assert h.refund_promise(case_id, str(promised), due).status_code == 201
        if shape == "over_two":
            half = (promised / 2).quantize(CENT)
            h.provider_refund(payment["id"], f"E2EI{index}A", str(half))
            h.provider_refund(payment["id"], f"E2EI{index}B", str(promised - half))
        elif refunded > 0:
            h.provider_refund(payment["id"], f"E2EI{index}", str(refunded))
        items = h.client.get(f"/resolution-cases/{case_id}/promise-health").json()["items"]
        observed = items[0]["status"] if items else "missing"
        expected = expected_status(promised, refunded, overdue)
        statuses_right += observed == expected
        incomplete, flagged = refunded < promised, observed not in ("kept", "missing")
        confusion[("tp" if flagged else "fn") if incomplete else ("fp" if flagged else "tn")] += 1
        remaining = D(items[0]["remaining_amount"]) if items else None
        s.check(f"case {index + 1}: {shape}, {'overdue' if overdue else 'not due'} -> status", expected, observed)
        s.check(f"case {index + 1}: remaining amount", promised - refunded, remaining)
    detected = confusion["tp"] + confusion["fn"]
    return s.result(cases=cases, confusion=confusion,
                    recall=round(confusion["tp"] / detected, 4) if detected else None,
                    precision=round(confusion["tp"] / (confusion["tp"] + confusion["fp"]), 4) if confusion["tp"] + confusion["fp"] else None,
                    status_accuracy=round(statuses_right / cases, 4))


# 3. Pending refunds -----------------------------------------------------------------------------

def pending_refunds(h: Harness) -> dict:
    s = Scenario("pending_refunds", "Correct treatment of pending refunds")
    payment = h.payment(agreed="100.00")
    case_id = h.resolution(payment["id"])
    assert h.refund_promise(case_id, "100.00").status_code == 201
    h.provider_refund(payment["id"], "E2EPEND1", "30.00", status="PENDING")
    basis = h.reconciliation(payment["id"])
    s.check("a pending refund is held as pending", "30.00", basis["pending_refund_amount"])
    s.check("a pending refund is not counted as completed", "0.00", basis["completed_refund_amount"])
    # Documented rules (backend/README.md, "Reconciliation rules"):
    s.check("the remaining refundable amount subtracts the pending refund", "70.00", basis["remaining_refundable_amount"])
    s.check("the uncovered commitment subtracts the pending refund", "70.00", basis["uncovered_commitment_amount"])
    s.check("the outstanding commitment still includes the pending amount", "100.00", basis["outstanding_commitment_amount"])
    s.check("no new refund is recommended while one is pending", ["refund_pending", "0.00"],
            [basis["status"], basis["recommended_refund_amount"]])
    [health] = h.client.get(f"/resolution-cases/{case_id}/promise-health").json()["items"]
    s.check("the suggested refund leaves the pending amount out", "70.00", health["suggested_refund_amount"])
    s.check("the promise is not counted as kept while pending", True, health["status"] != "kept")
    missing = [item["code"] for item in h.client.get(f"/resolution-cases/{case_id}/next-action").json()["missing"]]
    s.check("the next step names the unconfirmed pending refund", True, "pending_refund_unconfirmed" in missing)
    h.provider_refund(payment["id"], "E2EPEND1", "30.00", status="COMPLETED")
    basis = h.reconciliation(payment["id"])
    s.check("once completed, it moves from pending to completed", ["0.00", "30.00"],
            [basis["pending_refund_amount"], basis["completed_refund_amount"]])
    s.check("then the rest is recommended again", "70.00", basis["recommended_refund_amount"])
    return s.result()


# 4. Duplicate and excessive refunds blocked ------------------------------------------------------

def duplicates_blocked(h: Harness) -> dict:
    s = Scenario("duplicate_and_excessive_refunds_blocked", "Duplicate and excessive refund attempts blocked")
    capture = h.capture_id()
    payment = h.payment(agreed="100.00", capture=capture)
    h.verify_capture(payment)
    s.check("an approval above the recommended amount is rejected", 409,
            h.approve(payment["id"], "100.01", capture).status_code)
    approval = h.approve(payment["id"], "100.00", capture)
    s.check("an approval for the recommended amount is recorded", 201, approval.status_code)
    body = {"request_id": str(uuid4()), "approval_id": approval.json()["id"]}
    first = h.client.post(f"/cases/{payment['id']}/refund-executions", json=body)
    s.check("the approved refund executes once", [201, "completed"], [first.status_code, first.json().get("status")])
    replay = h.client.post(f"/cases/{payment['id']}/refund-executions", json=body)
    s.check("replaying the same request returns the same execution", [200, first.json().get("id")],
            [replay.status_code, replay.json().get("id")])
    again = h.client.post(f"/cases/{payment['id']}/refund-executions", json={**body, "request_id": str(uuid4())})
    s.check("a second execution of the same approval is rejected", 409, again.status_code)
    s.check("PayPal received exactly one refund request", 1, len(set(h.paypal.request_ids)))
    s.check("nothing is left to recommend after the full refund", "0.00",
            h.reconciliation(payment["id"])["recommended_refund_amount"])
    s.check("a new approval after the full refund is rejected", 409, h.approve(payment["id"], "1.00", capture).status_code)
    case_id = h.resolution()
    second = h.payment(agreed="40.00")
    h.client.put(f"/resolution-cases/{case_id}/payment-link", json={"refund_case_id": second["id"]})
    s.check("a refund promise up to the capture is recorded", 201, h.refund_promise(case_id, "40.00").status_code)
    s.check("a second refund promise on the same capture is rejected", 409, h.refund_promise(case_id, "10.00").status_code)
    return s.result()


# 5. Recovery after an interrupted request ----------------------------------------------------------

def recovery(h: Harness, folder: Path) -> dict:
    s = Scenario("recovery_after_interrupted_request", "Recovery from interrupted payment requests")
    for path in ("retry_after_restart", "recovery_worker"):
        capture = h.capture_id()
        payment = h.payment(agreed="100.00", capture=capture)
        h.verify_capture(payment)
        approval = h.approve(payment["id"], "100.00", capture).json()
        before = len(set(h.paypal.request_ids))
        h.paypal.mode = "interrupt_once"
        started = h.client.post(f"/cases/{payment['id']}/refund-executions",
                                json={"request_id": str(uuid4()), "approval_id": approval["id"]}).json()
        s.check(f"{path}: an interrupted request is recorded as unknown", "unknown", started.get("status"))
        basis = h.reconciliation(payment["id"])
        s.check(f"{path}: the balance stays reserved while unknown", ["execution_pending", "0.00"],
                [basis["status"], basis["recommended_refund_amount"]])
        s.check(f"{path}: no second approval can be used meanwhile", 409, h.approve(payment["id"], "1.00", capture).status_code)
        if path == "retry_after_restart":
            restarted = create_app(h.store.path)
            with TestClient(restarted) as again:
                again.headers["Authorization"] = f"Bearer {h.key}"
                restarted.state.paypal_client.close()
                restarted.state.paypal_client = h.paypal
                recovered = again.post(f"/cases/{payment['id']}/refund-executions/{started['id']}/retry").json()
        else:
            report = run_once(h.store, h.paypal, now=datetime.now(UTC) + timedelta(seconds=10))
            s.check(f"{path}: the worker completes it", 1, report["completed"])
            recovered = h.client.get(f"/cases/{payment['id']}/refund-executions/{started['id']}").json()
        s.check(f"{path}: the refund completes", "completed", recovered.get("status"))
        s.check(f"{path}: the same PayPal request id is reused", started.get("provider_request_id"),
                recovered.get("provider_request_id"))
        s.check(f"{path}: PayPal holds one refund for the case", 1, len(set(h.paypal.request_ids)) - before)
        s.check(f"{path}: the payment is fulfilled", "fulfilled", h.reconciliation(payment["id"])["status"])
    return s.result()


# 6. Time to verified resolution, and the recorded extraction results ------------------------------

def time_to_resolution(seed: int, cases: int) -> dict:
    report = resolution_time(cases=cases, seed=seed)
    overall = report["overall"]
    return {"metric": "time_to_verified_resolution", "readme": "Time to verified resolution",
            "label": "SYNTHETIC - generated delays (run_resolution_eval.py), not observed refund times",
            "seed": seed, "definition": report["definition"], **overall, "by_scenario": report["by_scenario"],
            "checks": [], "passed": 0, "total": 0}


def recorded_extraction() -> dict:
    out = {"metric": "extraction_and_injection", "readme": "Commitment-extraction accuracy",
           "label": "RECORDED EARLIER - live Groq calls on synthetic chats; not re-run by this harness",
           "checks": [], "passed": 0, "total": 0, "sources": {}}
    for name, file in EXTRACTION_SOURCES.items():
        path = RESULTS / file
        if not path.exists():
            out["sources"][name] = {"file": file, "missing": True}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        meta, overall = data["meta"], data["groups"]["overall"]
        if name == "extraction":
            v = overall["validated"]
            out["sources"][name] = {"file": file, "label": meta["label"], "date": meta["date"], "model": meta["model"],
                                    "chats": v["chats"], "precision": round(v["precision"], 3), "recall": round(v["recall"], 3),
                                    "f1": round(v["f1"], 3), "amount_accuracy": v["amount_accuracy"],
                                    "attacked_chats": v["attacked_chats"], "injection_successes": v["injection_successes"]}
        else:
            out["sources"][name] = {"file": file, "label": meta["label"], "date": meta["date"], "model": meta["model"],
                                    "chats": overall["chats"], "runs": len(overall["runs"]),
                                    "disagreements": overall["final_disagreements"],
                                    "injection_successes": [run["injection_successes"] for run in overall["runs"]],
                                    "note": "partial: 14 of 50 injection chats re-run (see CHG-038)"}
    return out


# Runner -------------------------------------------------------------------------------------------

def run(seed: int = 11, cases: int = 30, resolution_cases: int = 40) -> dict:
    rng = random.Random(seed)
    sections: list[dict] = []
    with TemporaryDirectory() as folder:
        harness = Harness(Path(folder), seed)
        try:
            steps: list[Callable[[], dict]] = [
                lambda: matching(harness),
                lambda: incomplete_detection(harness, rng, cases),
                lambda: pending_refunds(harness),
                lambda: duplicates_blocked(harness),
                lambda: recovery(harness, Path(folder)),
            ]
            sections += [step() for step in steps]
        finally:
            harness.close()
    sections.append(time_to_resolution(7, resolution_cases))
    sections.append(recorded_extraction())
    passed = sum(item["passed"] for item in sections)
    total = sum(item["total"] for item in sections)
    return {"label": LABEL, "seed": seed, "incomplete_cases": cases, "checks_passed": passed, "checks_total": total,
            "sections": sections}


def markdown(report: dict, day: str) -> str:
    lines = [f"# End-to-end evaluation - {day}", "", f"**{report['label']}.**", "",
             f"Seed {report['seed']}. Checks passed: **{report['checks_passed']} / {report['checks_total']}**.", "",
             "Each row compares the expected outcome with what the API actually returned. Amounts are USD.", "",
             "| README metric | Checks | Result |", "|---|---|---|"]
    for item in report["sections"]:
        if item["total"]:
            lines.append(f"| {item['readme']} | {item['passed']}/{item['total']} | {'pass' if item['passed'] == item['total'] else 'FAIL'} |")
    for item in report["sections"]:
        lines += ["", f"## {item['readme']}", ""]
        if item["metric"] == "incomplete_refund_detection":
            c = item["confusion"]
            lines += [(f"{item['cases']} seeded cases. Incomplete commitments detected: recall {item['recall']}, "
                       f"precision {item['precision']} (TP {c['tp']}, FP {c['fp']}, FN {c['fn']}, TN {c['tn']}). "
                       f"Status accuracy {item['status_accuracy']}."), ""]
        if item["metric"] == "time_to_verified_resolution":
            lines += [(f"**{item['label']}.** {item['cases']} cases (seed {item['seed']}), {item['resolved']} resolved, "
                       f"{item['unresolved']} not resolved (partial or no refund, by design). "
                       f"Median {item['median_hours']} h, p90 {item['p90_hours']} h. Definition: {item['definition']}."), ""]
            continue
        if item["metric"] == "extraction_and_injection":
            lines += [f"**{item['label']}.**", ""]
            for name, src in item["sources"].items():
                if src.get("missing"):
                    lines.append(f"- {name}: `{src['file']}` not found.")
                elif name == "extraction":
                    lines.append(f"- Extraction ({src['date']}, {src['model']}, {src['label']}, `{src['file']}`): "
                                 f"{src['chats']} chats, precision {src['precision']}, recall {src['recall']}, F1 {src['f1']}, "
                                 f"amount accuracy {src['amount_accuracy']}, injection successes "
                                 f"{src['injection_successes']}/{src['attacked_chats']}.")
                else:
                    lines.append(f"- Injection stability ({src['date']}, `{src['file']}`): {src['chats']} chats x "
                                 f"{src['runs']} runs, {src['disagreements']} disagreements, injection successes "
                                 f"{src['injection_successes']} ({src['note']}).")
            continue
        lines += ["| Check | Expected | Observed | |", "|---|---|---|---|"]
        for check in item["checks"]:
            lines.append(f"| {check['name']} | {check['expected']} | {check['observed']} | {'ok' if check['passed'] else 'FAIL'} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--cases", type=int, default=30)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args(argv)
    report = run(args.seed, args.cases)
    report["date"] = args.date
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"e2e_{args.date}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / f"e2e_{args.date}.md").write_text(markdown(report, args.date), encoding="utf-8")
    print(f"{report['checks_passed']}/{report['checks_total']} checks passed -> e2e_{args.date}.json / .md")
    return 0 if report["checks_passed"] == report["checks_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
