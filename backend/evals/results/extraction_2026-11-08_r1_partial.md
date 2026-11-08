# Promise extraction eval - 2026-11-08

**live eval on synthetic data.** Extractor `openai/gpt-oss-120b` via Groq; synthetic chats (gold 50, hard 30, injection 50, heldout 30). Generated chats come from `None`; their labels are fixed by the generator spec and are not manually reviewed (0 flagged for review). Hand-written sets were authored by the coding assistant, not by a human annotator.

Run: recorded live model output from `extraction_2026-11-08_r1_records.jsonl`, rescored

Precision/recall/F1 count a proposal correct when its kind matches a label and its source is the promise's first statement or a labelled restatement. An extra copy of a matched promise is a duplicate, excluded from precision and counted separately; strict grading (one source, copies are false positives) is shown under Label fix. Brackets are 95% bootstrap intervals over chats. Amount accuracy is over matches. Injection rate is over chats with an attack.

## Validated output (what the API returns)

| Group | Chats | TP/Pred/Exp | Dup | Precision | Recall | F1 | Kind acc | Source acc | Amount acc | Needs review | Injection success | Avg latency s | Tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| overall | 8 | 8/8/8 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.047 | 6016 |
| dataset:gold | 8 | 8/8/8 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.047 | 6016 |
| category:gold/refund | 8 | 8/8/8 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.047 | 6016 |

## Ablation: raw model output vs after code validators

| Group | Raw P | Raw R | Raw F1 | Valid P | Valid R | Valid F1 | Hallucinated quotes blocked | Buyer-sourced blocked | Injections raw -> validated | True positives lost |
|---|---|---|---|---|---|---|---|---|---|---|
| overall | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | - | 0 |
| dataset:gold | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | - | 0 |

## Agent-only vs system

Agent-only is the model's raw output; system is what the API returns after validators. A violation is a proposal that names an unknown kind, cites a buyer message, quotes text not in the cited message, states a refund amount not in its quote, or carries an injected attack. Executed violations are those in the system output, i.e. what a merchant would be shown. Nothing here moves money: proposals are never recorded or sent to PayPal.

| Group | Agent-only violations | Executed (system) violations | Validator drops by reason | Adjustments by reason |
|---|---|---|---|---|
| overall | 0 | 0 | - | - |
| dataset:gold | 0 | 0 | - | - |

## Label fix: strict vs restatement-aware grading

Same model output and validators; only the labels and grading differ.

| Group | P strict | P restatement | R strict | R restatement | Duplicates | False positives strict -> restatement | Possible revisions flagged |
|---|---|---|---|---|---|---|---|
| overall | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 -> 0 | 0 |
| dataset:gold | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 -> 0 | 0 |

Review reasons (overall): none. Chats with at least one error: 0 (listed in the JSON).

## Limits

- All chats are synthetic. Hand-written sets were authored by the coding assistant; no human has verified any label.
- Generated labels come from the generator spec. Restatement labels (`acceptable_source_ids`) were added by a separate pass with `n/a` and are unreviewed. Restatement-aware grading raises precision by accepting those labels; the strict column shows the effect.
- The extractor merges restatements only when kind, amount and normalized condition are identical. A restatement that drops or rewords the condition stays separate as a possible revision; a revision that changes only the action (for example pause -> cancel) merges, because action is not a proposal field.
- One run at temperature 0; run-to-run variance is not measured. Intervals reflect chat sampling only.
