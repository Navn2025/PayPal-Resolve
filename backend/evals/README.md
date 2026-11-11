# Evaluations

All evaluations here use **synthetic data**. Each result file states how it was
produced: a local simulation, or live model calls on synthetic chats.

| Script | What it measures | Data and calls | Latest result |
|---|---|---|---|
| `run_e2e_eval.py` | The README evaluation plan, end to end | Synthetic cases; local synthetic PayPal; no AI calls | `results/e2e_2026-11-11.md` |
| `run_resolution_eval.py` | Time to verified resolution | Synthetic cases with generated delays | `results/resolution_time_2026-11-10.md` |
| `run_extraction_eval.py` | Promise-extraction accuracy and injection resistance | Synthetic chats; live Groq only with `--live` | `results/extraction_2026-11-08_r1.md` (see `extraction/README.md`) |

## End-to-end harness

Run it from `backend/`:

```powershell
uv run python evals/run_e2e_eval.py            # writes results/e2e_<today>.json and .md
uv run python evals/run_e2e_eval.py --seed 11 --cases 30 --date 2026-11-11
```

**What it does:** it starts the real API on a temporary SQLite database with
one synthetic merchant and a local synthetic PayPal provider. The provider
never touches the network; refunds are recorded through the store's own
provider-refund recorder, as the backend tests do. Each check records the
expected and the observed outcome. The exit code is 1 if any check fails.

**What each README metric checks:**

| README metric | What is checked |
|---|---|
| Correct matching between cases and payments | One payment per case and one case per payment; another merchant's payment isn't found; a refund promise above the capture is rejected; a PayPal capture whose amount differs from the payment is refused |
| Detection of incomplete refund commitments | Seeded cases (none, partial, full, two-part refunds; due or overdue). The promise-health status and remaining amount are compared with the README rule. Reported as recall, precision and status accuracy |
| Correct treatment of pending refunds | Pending is held as pending, not counted as completed, and subtracted from the refundable and uncovered amounts. No new refund is recommended while one is pending. The next step names it. The recommendation returns once the refund completes |
| Duplicate and excessive refund attempts blocked | An approval above the recommendation is rejected; a replayed execution returns the same record; a second execution is rejected; PayPal gets one request; a second refund promise on the same capture is rejected |
| Recovery from interrupted payment requests | The provider accepts a refund but the response is lost. Both the retry after an app restart and the recovery worker are covered. Checked: the balance stays reserved, no new approval is possible, the refund completes with the same PayPal request ID, and PayPal holds exactly one refund |
| Time to verified resolution | Reuses `run_resolution_eval.py` (seed 7); the delays are generated |
| Commitment-extraction accuracy | **Not re-run.** Quoted from the recorded live-on-synthetic results with their own labels |

**Limits:**

- **Synthetic only:** no PayPal Sandbox or live provider behaviour is
  exercised.
- **Detection figures:** the precision and recall compare the API with an
  expected rule written from the README. They show that the full path works end
  to end (recorded refunds → reconciliation → promise health); they aren't a
  statistical accuracy estimate.
- **AI figures:** the extraction and injection numbers come from earlier runs.
  The injection-stability rerun is partial (14 of 50 chats; CHG-038).
