# Promise extraction eval - 2026-11-09

**live eval on synthetic data.** Extractor `openai/gpt-oss-120b` via Groq; synthetic chats (gold 50, hard 30). Generated chats come from `None`; their labels are fixed by the generator spec and are not manually reviewed (0 flagged for review). Hand-written sets were authored by the coding assistant, not by a human annotator.

Run: model output recorded live in `extraction_2026-11-08_r1_records.jsonl`, replayed through the current validators (no new model calls; latency and tokens are the originals)

Precision/recall/F1 count a proposal correct when its kind matches a label and its source is the promise's first statement or a labelled restatement. An extra copy of a matched promise is a duplicate, excluded from precision and counted separately; strict grading (one source, copies are false positives) is shown under Label fix. Brackets are 95% bootstrap intervals over chats. Amount accuracy is over matches. Injection rate is over chats with an attack.

## Validated output (what the API returns)

| Group | Chats | TP/Pred/Exp | Dup | Precision | Recall | F1 | Kind acc | Source acc | Amount acc | Needs review | Injection success | Avg latency s | Tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| overall | 80 | 74/79/75 | 0 | 0.937 [0.89, 0.99] | 0.987 [0.96, 1.00] | 0.961 [0.93, 0.99] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.871 | 57153 |
| dataset:gold | 50 | 40/40/40 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.835 | 34635 |
| dataset:hard | 30 | 34/39/35 | 0 | 0.872 [0.78, 0.97] | 0.971 [0.91, 1.00] | 0.919 [0.86, 0.97] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.929 | 22518 |
| category:gold/billing_correction | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.763 | 3460 |
| category:gold/dispute_handoff | 2 | 2/2/2 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.321 | 1561 |
| category:gold/no_promise | 10 | 0/0/0 | 0 | - | - | - | - | - | - | 0.000 | - | 0.572 | 5918 |
| category:gold/order_cancellation | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.841 | 3511 |
| category:gold/refund | 8 | 8/8/8 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.047 | 6016 |
| category:gold/replacement | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.822 | 3576 |
| category:gold/return | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.944 | 3691 |
| category:gold/store_credit_or_exchange | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.738 | 3430 |
| category:gold/subscription | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.900 | 3472 |
| category:hard/amount_vs_order_number | 6 | 6/6/6 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.792 | 4082 |
| category:hard/currency_formats | 6 | 6/6/6 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.792 | 4188 |
| category:hard/hinglish | 7 | 6/6/6 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.902 | 4917 |
| category:hard/multiple_promises | 6 | 11/11/12 | 0 | 1.000 [1.00, 1.00] | 0.917 [0.75, 1.00] | 0.957 [0.86, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.057 | 4811 |
| category:hard/revised_promise | 5 | 5/10/5 | 0 | 0.500 [0.50, 0.50] | 1.000 [1.00, 1.00] | 0.667 [0.67, 0.67] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.144 | 4520 |

## Ablation: raw model output vs after code validators

| Group | Raw P | Raw R | Raw F1 | Valid P | Valid R | Valid F1 | Hallucinated quotes blocked | Buyer-sourced blocked | Injections raw -> validated | True positives lost |
|---|---|---|---|---|---|---|---|---|---|---|
| overall | 0.937 | 0.987 | 0.961 | 0.937 | 0.987 | 0.961 | 0 | 0 | - | 0 |
| dataset:gold | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | - | 0 |
| dataset:hard | 0.872 | 0.971 | 0.919 | 0.872 | 0.971 | 0.919 | 0 | 0 | - | 0 |

## Agent-only vs system

Agent-only is the model's raw output; system is what the API returns after validators. A violation is a proposal that names an unknown kind, cites a buyer message, quotes text not in the cited message, states a refund amount not in its quote, or carries an injected attack. Executed violations are those in the system output, i.e. what a merchant would be shown. Nothing here moves money: proposals are never recorded or sent to PayPal.

| Group | Agent-only violations | Executed (system) violations | Validator drops by reason | Adjustments by reason |
|---|---|---|---|---|
| overall | 0 | 0 | - | quote_normalized 1 |
| dataset:gold | 0 | 0 | - | - |
| dataset:hard | 0 | 0 | - | quote_normalized 1 |

## Label fix: strict vs restatement-aware grading

Same model output and validators; only the labels and grading differ.

| Group | P strict | P restatement | R strict | R restatement | Duplicates | False positives strict -> restatement | Possible revisions flagged |
|---|---|---|---|---|---|---|---|
| overall | 0.937 | 0.937 | 0.987 | 0.987 | 0 | 5 -> 5 | 4 |
| dataset:gold | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 -> 0 | 0 |
| dataset:hard | 0.872 | 0.872 | 0.971 | 0.971 | 0 | 5 -> 5 | 4 |

## Precision by stage

Baseline: extractor code at the time of `extraction_2026-11-08_r1_records.jsonl`, as recorded. The current stage replays the same recorded model output through the current validators.

| Group | Baseline, strict labels | Baseline, restatement labels | Current extractor, restatement labels | Recall baseline -> current |
|---|---|---|---|---|
| overall | 0.937 | 0.937 | 0.937 | 0.987 -> 0.987 |
| dataset:gold | 1.000 | 1.000 | 1.000 | 1.000 -> 1.000 |
| dataset:hard | 0.872 | 0.872 | 0.872 | 0.971 -> 0.971 |

Review reasons (overall): none. Chats with at least one error: 6 (listed in the JSON).

## Limits

- All chats are synthetic. Hand-written sets were authored by the coding assistant; no human has verified any label.
- Generated labels come from the generator spec. Restatement labels (`acceptable_source_ids`) were added by a separate pass with `n/a` and are unreviewed. Restatement-aware grading raises precision by accepting those labels; the strict column shows the effect.
- The extractor merges restatements only when kind, amount and normalized condition are identical. A restatement that drops or rewords the condition stays separate as a possible revision; a revision that changes only the action (for example pause -> cancel) merges, because action is not a proposal field.
- One run at temperature 0; run-to-run variance is not measured. Intervals reflect chat sampling only.
