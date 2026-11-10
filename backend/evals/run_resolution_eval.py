"""Time to verified resolution on SYNTHETIC cases.

Every case, amount and delay is generated here from a fixed seed. PayPal refunds are simulated
through the store's own provider-refund recorder (no network), and their timestamps are then set
to the seeded delays. Nothing here describes real merchants or real refund times.

    uv run python evals/run_resolution_eval.py [--cases 40] [--seed 7]
"""

import argparse
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app
from app.paypal import PayPalRefundDetails
from app.resolution_metrics import summarize_hours, time_to_verified_resolution
from app.resolution_models import ResolutionTimeline

RESULTS = Path(__file__).resolve().parent / "results"
SCENARIOS = ("one_refund", "two_refunds", "partial_only", "no_refund", "pending_then_completed")
BASE = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def _plan(rng: random.Random, index: int) -> dict:
    scenario = SCENARIOS[index % len(SCENARIOS)]
    promised = Decimal(rng.randrange(1000, 10000)) / 100
    first = rng.uniform(2, 120)  # hours after the promise
    refunds = {
        "one_refund": [(promised, "COMPLETED", first)],
        "two_refunds": [((promised / 2).quantize(Decimal("0.01")), "COMPLETED", first),
                        (promised - (promised / 2).quantize(Decimal("0.01")), "COMPLETED", first + rng.uniform(4, 96))],
        "partial_only": [((promised * Decimal("0.4")).quantize(Decimal("0.01")), "COMPLETED", first)],
        "no_refund": [],
        "pending_then_completed": [(promised, "PENDING", first), (promised, "COMPLETED", first + rng.uniform(1, 48))],
    }[scenario]
    return {"scenario": scenario, "promised": promised, "refunds": refunds}


def run(cases: int = 40, seed: int = 7) -> dict:
    rng = random.Random(seed)
    rows = []
    with TemporaryDirectory() as folder:
        app = create_app(Path(folder) / "synthetic.sqlite3")
        store = app.state.store
        with TestClient(app) as client:
            merchant_key = store.create_merchant("Synthetic eval merchant").api_key
            client.headers["Authorization"] = f"Bearer {merchant_key}"
            for index in range(cases):
                plan = _plan(rng, index)
                capture = f"SYNTHEVAL{seed}N{index}"
                amount = f"{plan['promised']:.2f}"
                payment = client.post("/cases", json={
                    "order_id": "SYNTH" + capture, "complaint": "Synthetic eval case",
                    "payment": {"capture_id": capture, "captured_amount": "100.00"},
                    "commitment": {"amount": amount, "status": "accepted", "source_message": "Synthetic"},
                }).json()["id"]
                case_id = client.post("/resolution-cases", json={"title": f"Synthetic {index}", "refund_case_id": payment}).json()["id"]
                promise = client.post(f"/resolution-cases/{case_id}/promises", json={
                    "promise": "Synthetic refund", "source_note": "Synthetic",
                    "target": {"kind": "refund", "amount": amount}}).json()
                start = BASE + timedelta(days=index)
                with store.transaction(write=True) as connection:
                    connection.execute("UPDATE resolution_events SET recorded_at=? WHERE promise_id=?",
                                       (start.isoformat(timespec="microseconds"), promise["id"]))
                    merchant = connection.execute("SELECT merchant_id FROM cases WHERE id=?", (payment,)).fetchone()[0]
                    legacy = store._require_case(connection, UUID(payment), UUID(str(merchant)))
                    for number, (value, status, hours) in enumerate(plan["refunds"]):
                        refund_id = f"SR{index}N{0 if plan['scenario'] == 'pending_then_completed' else number}"
                        store._record_provider_refund(connection, legacy, PayPalRefundDetails(
                            id=refund_id, amount={"value": f"{value:.2f}", "currency_code": "USD"}, status=status, links=[]))
                        connection.execute(
                            "UPDATE paypal_refund_verifications SET checked_at=? WHERE refund_id=? AND provider_status=?",
                            ((start + timedelta(hours=hours)).isoformat(timespec="microseconds"), refund_id, status))
                timeline = ResolutionTimeline.model_validate(
                    client.get(f"/resolution-cases/{case_id}/timeline?limit=100").json())
                assert timeline.total <= 100 and timeline.refund_total <= 100
                duration = time_to_verified_resolution(timeline, promise["id"], plan["promised"])
                rows.append({"case": index, "scenario": plan["scenario"], "promised": amount,
                             "hours": round(duration.total_seconds() / 3600, 2) if duration else None})
    by_scenario = {name: summarize_hours([timedelta(hours=r["hours"]) if r["hours"] is not None else None
                                          for r in rows if r["scenario"] == name]) for name in SCENARIOS}
    overall = summarize_hours([timedelta(hours=r["hours"]) if r["hours"] is not None else None for r in rows])
    return {"data": "synthetic", "seed": seed, "metric": "time_to_verified_resolution",
            "definition": "first promise_recorded event -> first PayPal-verified COMPLETED refunds covering the promise",
            "overall": overall, "by_scenario": by_scenario, "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    report = run(args.cases, args.seed)
    RESULTS.mkdir(exist_ok=True)
    stem = RESULTS / f"resolution_time_{datetime.now(UTC).date().isoformat()}"
    stem.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Time to verified resolution (SYNTHETIC data)", "",
             "All cases, amounts and delays are generated from a fixed seed; PayPal refunds are simulated.",
             "These numbers describe the generator, not real merchants.", "",
             f"Seed {report['seed']}, {report['overall']['cases']} cases. Definition: {report['definition']}.", "",
             "| Scenario | Cases | Resolved | Median (h) | p90 (h) |", "|---|---|---|---|---|"]
    for name, row in [("all", report["overall"]), *report["by_scenario"].items()]:
        lines.append(f"| {name} | {row['cases']} | {row['resolved']} | {row['median_hours']} | {row['p90_hours']} |")
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
