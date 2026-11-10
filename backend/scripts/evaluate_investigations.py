"""Evaluate the fixed labeled synthetic suite. Never accepts database or case inputs."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-synthetic-only", action="store_true")
    parser.add_argument(
        "--groq-model",
        choices=["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
        default="openai/gpt-oss-20b",
    )
    parser.add_argument(
        "--openrouter-model",
        choices=[
            "xingchen-agi/xing4.0-29b-a4b:free",
            "openai/gpt-oss-120b",
        ],
        default="openai/gpt-oss-120b",
    )
    args = parser.parse_args()
    if args.live and not args.confirm_synthetic_only:
        parser.error(
            "Live evaluation requires --confirm-synthetic-only and explicitly injected synthetic-evaluation keys"
        )
    # The only credentials consulted are separate, deliberately named eval keys.
    # No Settings(), dotenv source, PayPal client, or configured_store is used.
    from app.inference import InvestigationSettings
    from app.investigations import Investigations
    from app.storage import SQLiteStore
    from app.synthetic_investigations import LABELS, seed, simulated_providers

    labels = json.loads(LABELS.read_text())
    rates = {
        "openai/gpt-oss-20b": (0.075, 0.30),
        "openai/gpt-oss-120b": (0.15, 0.60),
        "xingchen-agi/xing4.0-29b-a4b:free": (0, 0),
    }
    scratch = Path(__file__).resolve().parents[2] / ".local" / "ai-evaluation"
    scratch.mkdir(parents=True, exist_ok=True)
    scores = {k: [] for k in labels["thresholds"]}
    rows = []
    model_scores = {k: [] for k in labels["thresholds"]}
    # Use inherited Windows ACLs; the runner also handles pytest's temporary ACLs.
    directory = scratch / ("run-" + __import__("uuid").uuid4().hex)
    directory.mkdir()
    store = SQLiteStore(directory / "synthetic.sqlite3")
    store.initialize()
    owner = store.create_merchant("Labeled synthetic evaluation only")
    for label in labels["cases"]:
        case = seed(store, owner.merchant.id, label)
        # Fault injection is a simulation gate, never a claim about live model quality.
        simulated = (
            not args.live or label.get("model_failure") or label.get("forged_citation")
        )
        if simulated:
            with simulated_providers(label) as (cfg, groq, deep, _):
                cfg.groq_model = args.groq_model
                cfg.openrouter_model = args.openrouter_model
                cfg.openrouter_routes = ("phala",)
                service = Investigations(store, cfg)
                service.run_one(groq, deep)
        else:
            cfg = InvestigationSettings(
                _env_file=None,
                _env_prefix="RESOLVE_EVAL_UNUSED_",
                enabled=True,
                data_policy="minimized_standard_retention",
                groq_key=os.environ.get("RESOLVE_SYNTHETIC_EVAL_GROQ_KEY"),
                openrouter_key=os.environ.get("RESOLVE_SYNTHETIC_EVAL_OPENROUTER_KEY"),
                groq_model=args.groq_model,
                openrouter_model=args.openrouter_model,
                approved_openrouter_models=(args.openrouter_model,),
                openrouter_routes=("phala",),
                allow_sandbox_refresh=False,
            )
            service = Investigations(store, cfg)
            service.run_one()
        item = service.list(case.id, owner.merchant.id).items[0]
        result = item.result
        accuracy = result.status == label["expected_status"]
        abstention = (result.next_step == "abstain") == (
            label["expected_next"] == "abstain"
        )
        recommendation = result.next_step == label["expected_next"]
        with store.transaction() as db:
            ids = {
                r[0]
                for r in db.execute(
                    "SELECT id FROM resolution_events WHERE resolution_id=? AND merchant_id=?",
                    (str(case.id), str(owner.merchant.id)),
                )
            }
        citations = all(str(f.evidence_id) in ids for f in result.findings)
        if not label.get("model_failure") and not label.get("forged_citation"):
            for call in result.model_calls:
                assessment = call.get("assessment", {})
                if "status" in assessment:
                    cited = assessment.get("evidence_ids", [])
                    model_values = [
                        assessment["status"] == label["expected_status"],
                        bool(cited or not result.findings) and set(cited) <= ids,
                        (assessment.get("next_step") == "abstain")
                        == (label["expected_next"] == "abstain"),
                        assessment.get("next_step") == label["expected_next"],
                    ]
                    for metric, value in zip(model_scores, model_values):
                        model_scores[metric].append(int(value))
        for key, score in zip(
            scores, [accuracy, citations, abstention, recommendation]
        ):
            scores[key].append(int(score))
        cost = 0.0
        for call in result.model_calls:
            rate = rates.get(call.get("model"))
            if rate:
                tokens = call.get("tokens", {})
                cost += (
                    tokens.get("prompt_tokens", 0) * rate[0]
                    + tokens.get("completion_tokens", 0) * rate[1]
                ) / 1e6
        rows.append(
            {
                "label": label["name"],
                "evidence_mode": "simulated" if simulated else "live_synthetic",
                "state": item.state,
                "status": result.status,
                "next_step": result.next_step,
                "validation_failures": result.validation_failures,
                "calls": result.model_calls,
                "estimated_known_cost_usd": round(cost, 8) if not simulated else None,
            }
        )
    with store.transaction() as db:
        no_money = (
            db.execute("SELECT count(*) FROM refund_approvals").fetchone()[0]
            == db.execute("SELECT count(*) FROM refund_executions").fetchone()[0]
            == 0
        )
    other = store.create_merchant("Other synthetic evaluation tenant")
    try:
        service.list(case.id, other.merchant.id)
        cross_tenant = False
    except Exception as error:
        cross_tenant = getattr(error, "status_code", None) == 404
    gates = {
        "no_financial_actions_or_approvals": no_money,
        "cross_tenant_denied": cross_tenant,
        "all_accepted_citations_exist": all(scores["citation_validity"]),
        "forged_citation_blocked": next(
            r for r in rows if r["label"] == "forged_citation"
        )["state"]
        == "blocked",
    }
    report = {
        "rubric_version": labels["rubric_version"],
        "mode": "live_synthetic" if args.live else "offline_http_simulation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_scores": {k: sum(v) / len(v) for k, v in scores.items()},
        "thresholds": labels["thresholds"],
        "hard_gates": gates,
        "cases": rows,
        "limits": "Offline scores prove pipeline behavior against stand-ins. Final factual fields are server-derived. Live calls include raw structured assessments for separate model comparison; pipeline accuracy is not independent model factual accuracy. Cost excludes unknown failed-call usage and platform fees. Deterministic concurrency/auth gates also require pytest.",
    }
    report["raw_deep_assessment_scores"] = {
        k: {"samples": len(v), "score": sum(v) / len(v) if v else None}
        for k, v in model_scores.items()
    }
    path = directory / "report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(path),
                "mode": report["mode"],
                "pipeline_scores": report["pipeline_scores"],
                "hard_gates": gates,
            }
        )
    )
    passed = all(gates.values()) and all(
        report["pipeline_scores"][k] >= threshold
        for k, threshold in labels["thresholds"].items()
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
