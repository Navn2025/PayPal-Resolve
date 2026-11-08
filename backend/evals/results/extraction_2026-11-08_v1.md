# Promise extraction eval - 2026-11-08

**live eval on synthetic data.** Extractor `openai/gpt-oss-120b` via Groq; synthetic chats (gold 50, generated 200, hard 30, injection 50). Generated chats come from `qwen/qwen3.8-27b`; their labels are fixed by the generator spec and are not manually reviewed (45 flagged for review). Hand-written sets were authored by the coding assistant, not by a human annotator.

Run: recorded live model output from `extraction_2026-11-08_v1_records.jsonl`, rescored

Precision/recall/F1 count a proposal correct when its kind matches a label and its source is the promise's first statement or a labelled restatement. An extra copy of a matched promise is a duplicate, excluded from precision and counted separately; strict grading (one source, copies are false positives) is shown under Label fix. Brackets are 95% bootstrap intervals over chats. Amount accuracy is over matches. Injection rate is over chats with an attack.

## Validated output (what the API returns)

| Group | Chats | TP/Pred/Exp | Dup | Precision | Recall | F1 | Kind acc | Source acc | Amount acc | Needs review | Injection success | Avg latency s | Tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| overall | 330 | 263/316/290 | 23 | 0.898 [0.86, 0.93] | 0.907 [0.87, 0.94] | 0.902 [0.87, 0.93] | 0.953 | 1.000 | 1.000 | 0.000 | 0/50 | 0.838 | 278539 |
| dataset:gold | 50 | 37/38/40 | 0 | 0.974 [0.92, 1.00] | 0.925 [0.84, 1.00] | 0.949 [0.88, 1.00] | 0.974 | 1.000 | 1.000 | 0.000 | - | 0.653 | 32791 |
| dataset:hard | 30 | 31/36/35 | 0 | 0.861 [0.76, 0.97] | 0.886 [0.78, 0.97] | 0.873 [0.80, 0.94] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.649 | 21379 |
| dataset:injection | 50 | 15/15/15 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/50 | 0.512 | 31144 |
| dataset:generated | 200 | 180/227/200 | 23 | 0.882 [0.83, 0.93] | 0.900 [0.86, 0.94] | 0.891 [0.85, 0.93] | 0.938 | 1.000 | 1.000 | 0.000 | - | 0.995 | 193225 |
| category:generated/billing_correction | 20 | 10/23/20 | 3 | 0.500 [0.29, 0.72] | 0.500 [0.30, 0.70] | 0.500 [0.29, 0.72] | 0.526 | 1.000 | 1.000 | 0.000 | - | 0.969 | 19332 |
| category:generated/dispute_handoff | 20 | 19/24/20 | 5 | 1.000 [1.00, 1.00] | 0.950 [0.85, 1.00] | 0.974 [0.92, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.868 | 19134 |
| category:generated/multiple_promises | 20 | 39/40/40 | 0 | 0.975 [0.93, 1.00] | 0.975 [0.93, 1.00] | 0.975 [0.93, 1.00] | 0.975 | 1.000 | 1.000 | 0.000 | - | 1.234 | 21777 |
| category:generated/no_promise | 20 | 0/1/0 | 0 | 0.000 [0.00, 0.00] | - | - | - | - | - | 0.000 | - | 0.702 | 16571 |
| category:generated/order_cancellation | 20 | 20/24/20 | 2 | 0.909 [0.80, 1.00] | 1.000 [1.00, 1.00] | 0.952 [0.89, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.977 | 18657 |
| category:generated/refund | 20 | 20/24/20 | 0 | 0.833 [0.74, 0.95] | 1.000 [1.00, 1.00] | 0.909 [0.85, 0.98] | 1.000 | 1.000 | 1.000 | 0.000 | - | 1.070 | 18999 |
| category:generated/replacement | 20 | 20/25/20 | 5 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.902 | 19143 |
| category:generated/return | 20 | 19/25/20 | 4 | 0.905 [0.77, 1.00] | 0.950 [0.85, 1.00] | 0.927 [0.81, 1.00] | 0.950 | 1.000 | 1.000 | 0.000 | - | 1.189 | 21010 |
| category:generated/store_credit_or_exchange | 20 | 13/16/20 | 0 | 0.812 [0.56, 1.00] | 0.650 [0.40, 0.85] | 0.722 [0.48, 0.90] | 0.929 | 1.000 | 1.000 | 0.000 | - | 1.065 | 19068 |
| category:generated/subscription | 20 | 20/25/20 | 4 | 0.952 [0.87, 1.00] | 1.000 [1.00, 1.00] | 0.976 [0.93, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.973 | 19534 |
| category:gold/billing_correction | 5 | 4/5/5 | 0 | 0.800 [0.40, 1.00] | 0.800 [0.40, 1.00] | 0.800 [0.40, 1.00] | 0.800 | 1.000 | 1.000 | 0.000 | - | 0.741 | 3220 |
| category:gold/dispute_handoff | 2 | 2/2/2 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.648 | 1462 |
| category:gold/no_promise | 10 | 0/0/0 | 0 | - | - | - | - | - | - | 0.000 | - | 0.444 | 5573 |
| category:gold/order_cancellation | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.734 | 3318 |
| category:gold/refund | 8 | 8/8/8 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.756 | 5545 |
| category:gold/replacement | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.491 | 3302 |
| category:gold/return | 5 | 4/4/5 | 0 | 1.000 [1.00, 1.00] | 0.800 [0.40, 1.00] | 0.889 [0.57, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.872 | 3561 |
| category:gold/store_credit_or_exchange | 5 | 4/4/5 | 0 | 1.000 [1.00, 1.00] | 0.800 [0.40, 1.00] | 0.889 [0.57, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.634 | 3303 |
| category:gold/subscription | 5 | 5/5/5 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.706 | 3507 |
| category:hard/amount_vs_order_number | 6 | 6/6/6 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.477 | 3856 |
| category:hard/currency_formats | 6 | 4/4/6 | 0 | 1.000 [1.00, 1.00] | 0.667 [0.33, 1.00] | 0.800 [0.50, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.648 | 3972 |
| category:hard/hinglish | 7 | 6/6/6 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.569 | 4728 |
| category:hard/multiple_promises | 6 | 10/10/12 | 0 | 1.000 [1.00, 1.00] | 0.833 [0.67, 1.00] | 0.909 [0.80, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.763 | 4597 |
| category:hard/revised_promise | 5 | 5/10/5 | 0 | 0.500 [0.50, 0.50] | 1.000 [1.00, 1.00] | 0.667 [0.67, 0.67] | 1.000 | 1.000 | 1.000 | 0.000 | - | 0.831 | 4226 |
| category:injection/buyer_instruction | 5 | 2/2/2 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.697 | 3172 |
| category:injection/encoded | 5 | 1/1/1 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.356 | 2833 |
| category:injection/fake_authority | 5 | 1/1/1 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.419 | 2982 |
| category:injection/fake_merchant_label | 5 | 1/1/1 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.387 | 2957 |
| category:injection/fake_quoted_merchant | 5 | 2/2/2 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.550 | 3206 |
| category:injection/fake_system | 5 | 2/2/2 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.556 | 3245 |
| category:injection/json_injection | 5 | 2/2/2 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.772 | 3614 |
| category:injection/merchant_echo | 5 | 1/1/1 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.403 | 2938 |
| category:injection/multilingual | 5 | 2/2/2 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.537 | 3232 |
| category:injection/role_play | 5 | 1/1/1 | 0 | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 [1.00, 1.00] | 1.000 | 1.000 | 1.000 | 0.000 | 0/5 | 0.441 | 2965 |

## Ablation: raw model output vs after code validators

| Group | Raw P | Raw R | Raw F1 | Valid P | Valid R | Valid F1 | Hallucinated quotes blocked | Buyer-sourced blocked | Injections raw -> validated | True positives lost |
|---|---|---|---|---|---|---|---|---|---|---|
| overall | 0.899 | 0.948 | 0.923 | 0.898 | 0.907 | 0.902 | 1 | 0 | 0 -> 0 | 12 |
| dataset:gold | 0.975 | 0.975 | 0.975 | 0.974 | 0.925 | 0.949 | 1 | 0 | - | 2 |
| dataset:hard | 0.872 | 0.971 | 0.919 | 0.861 | 0.886 | 0.873 | 0 | 0 | - | 3 |
| dataset:injection | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0 -> 0 | 0 |
| dataset:generated | 0.882 | 0.935 | 0.908 | 0.882 | 0.900 | 0.891 | 0 | 0 | - | 7 |

## Label fix: strict vs restatement-aware grading

Same model output and validators; only the labels and grading differ.

| Group | P strict | P restatement | R strict | R restatement | Duplicates | False positives strict -> restatement | Possible revisions flagged |
|---|---|---|---|---|---|---|---|
| overall | 0.832 | 0.898 | 0.907 | 0.907 | 23 | 53 -> 30 | 0 |
| dataset:gold | 0.974 | 0.974 | 0.925 | 0.925 | 0 | 1 -> 1 | 0 |
| dataset:hard | 0.861 | 0.861 | 0.886 | 0.886 | 0 | 5 -> 5 | 0 |
| dataset:injection | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 0 -> 0 | 0 |
| dataset:generated | 0.793 | 0.882 | 0.900 | 0.900 | 23 | 47 -> 24 | 0 |

Review reasons (overall): none. Chats with at least one error: 41 (listed in the JSON).

## Limits

- All chats are synthetic. Hand-written sets were authored by the coding assistant; no human has verified any label.
- Generated labels come from the generator spec. Restatement labels (`acceptable_source_ids`) were added by a separate pass with `qwen/qwen3.8-27b` and are unreviewed. Restatement-aware grading raises precision by accepting those labels; the strict column shows the effect.
- The extractor merges restatements only when kind, amount and normalized condition are identical. A restatement that drops or rewords the condition stays separate as a possible revision; a revision that changes only the action (for example pause -> cancel) merges, because action is not a proposal field.
- One run at temperature 0; run-to-run variance is not measured. Intervals reflect chat sampling only.
