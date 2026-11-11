"""The end-to-end evaluation harness stays green and keeps its synthetic labelling.
Synthetic data only: local SQLite, a local synthetic PayPal provider, no AI calls."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

import run_e2e_eval


def test_every_readme_metric_passes_on_a_small_seed():
    report = run_e2e_eval.run(seed=3, cases=6, resolution_cases=10)
    failed = [(s["metric"], c["name"]) for s in report["sections"] for c in s["checks"] if not c["passed"]]
    assert failed == []
    metrics = [section["metric"] for section in report["sections"]]
    assert metrics == ["case_to_payment_matching", "incomplete_refund_detection", "pending_refunds",
                       "duplicate_and_excessive_refunds_blocked", "recovery_after_interrupted_request",
                       "time_to_verified_resolution", "extraction_and_injection"]
    assert report["checks_total"] == report["checks_passed"] > 30
    assert report["label"].startswith("SYNTHETIC")


def test_results_files_are_dated_and_labelled(tmp_path):
    assert run_e2e_eval.main(["--seed", "3", "--cases", "4", "--date", "2026-01-02", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "e2e_2026-01-02.json").read_text(encoding="utf-8"))
    text = (tmp_path / "e2e_2026-01-02.md").read_text(encoding="utf-8")
    assert data["date"] == "2026-01-02" and data["label"].startswith("SYNTHETIC")
    assert "**SYNTHETIC" in text and "RECORDED EARLIER" in text and "FAIL" not in text
    assert "Recovery from interrupted payment requests" in text


def test_expected_status_rule_is_written_from_the_readme():
    from decimal import Decimal as D
    rule = run_e2e_eval.expected_status
    assert rule(D(50), D(50), True) == "kept"
    assert rule(D(50), D(0), False) == "at_risk"
    assert rule(D(50), D(10), False) == "partially_kept"
    assert rule(D(50), D(10), True) == "at_risk"
    assert rule(D(50), D(0), True) == "broken"
