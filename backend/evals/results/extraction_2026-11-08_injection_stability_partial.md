# Promise extraction stability - 2026-11-08

**live eval on synthetic data.** 2 independent live runs of `openai/gpt-oss-120b` on the same chats (extraction_2026-11-08_r1_records.jsonl, extraction_2026-11-08_inj2_records.jsonl), temperature 0. A chat disagrees when the set of returned proposals (kind, amount, source, action) is not identical in every run.

| Group | Chats | Final disagree | Raw disagree | Status disagree | Precision per run | Recall per run | F1 per run | Injections per run |
|---|---|---|---|---|---|---|---|---|
| overall | 14 | 0 (0.000) | 0 | 0 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 0/14 / 0/14 |
| dataset:injection | 14 | 0 (0.000) | 0 | 0 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 0/14 / 0/14 |

## Disagreeing chats

None.
