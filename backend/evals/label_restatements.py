"""Add restatement labels (`acceptable_source_ids`) to the generated eval set.

A restatement repeats one promise with the same terms in a later merchant turn.
The labeller is the generator's model, not the extractor's, and its answer is
constrained in code: only later merchant turns can be restatements. A later
turn the labeller reports as changing the terms is not added; the chat is
flagged for manual review instead, because under the README's revision rule
the label itself may need to move.

    uv run python evals/label_restatements.py --live
"""

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import groq

from app.ai_extraction import GROQ_DATA_POLICY, AISettings, current_data_policy

LABELER_MODEL = "qwen/qwen3.8-27b"
DATASET = BACKEND_DIR / "evals/extraction/generated.jsonl"


def prompt(item, promise, later):
    chat = "\n".join(f"{m['id']} ({m['sender']}): {m['text']}" for m in item["messages"])
    amount = (
        f" for {promise['amount_cents'] / 100:.2f} USD" if promise["amount_cents"] else ""
    )
    return (
        f"Support chat:\n{chat}\n\n"
        f"In {promise['source_message_id']} the merchant committed to a "
        f"{promise['kind'].replace('_', ' ')}{amount}.\n"
        f"For each later merchant message ({', '.join(later)}), decide:\n"
        '- "restatement": it repeats, confirms or reports progress on that same '
        "commitment with the same terms.\n"
        '- "revision": it changes the terms of that commitment (amount, condition, '
        "action) or replaces it.\n"
        '- "unrelated": anything else, including a different kind of commitment.\n'
        'Respond only with json: {"labels": {"<message id>": "restatement" | '
        '"revision" | "unrelated"}}'
    )


def classify(client, item, promise, later):
    for _ in range(6):
        try:
            response = client.chat.completions.create(
                model=LABELER_MODEL,
                temperature=0,
                max_tokens=300,
                reasoning_effort="none",
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt(item, promise, later)}],
            )
            labels = json.loads(response.choices[0].message.content)["labels"]
            return {m: labels.get(m) for m in later}
        except groq.RateLimitError as error:
            time.sleep(min(float(error.response.headers.get("retry-after") or 20), 120))
        except (groq.APIStatusError, ValueError, KeyError, TypeError, AttributeError):
            time.sleep(2)
    raise RuntimeError(f"No usable label for {item['id']}")


def label(item, client):
    position = {m["id"]: n for n, m in enumerate(item["messages"])}
    notes = []
    for promise in item["expected"]:
        later = [
            m["id"]
            for m in item["messages"]
            if m["sender"] == "merchant"
            and position[m["id"]] > position[promise["source_message_id"]]
        ]
        labels = classify(client, item, promise, later) if later else {}
        promise["acceptable_source_ids"] = [promise["source_message_id"]] + [
            m for m in later if labels.get(m) == "restatement"
        ]
        revisions = [m for m in later if labels.get(m) == "revision"]
        if revisions:
            notes.append(f"{promise['kind']}: labeller reported a revision in {', '.join(revisions)}")
    item["restatement_labeler"] = LABELER_MODEL
    item["restatement_checked"] = True
    if notes:
        item["needs_manual_review"] = True
        item["review_note"] = "; ".join(notes)
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call Groq (required)")
    args = parser.parse_args()
    if not args.live:
        parser.error("Labelling calls Groq; pass --live to run it")
    if current_data_policy() != GROQ_DATA_POLICY:
        parser.error(
            "Groq calls require RESOLVE_AI_DATA_POLICY=minimized_standard_retention in the "
            "process environment (app.inference never reads .env). Use it only for "
            "synthetic data."
        )
    key = AISettings().groq_api_key
    if key is None:
        parser.error("GROQ_API_KEY is not set")
    client = groq.Groq(api_key=key.get_secret_value(), max_retries=2, timeout=60)
    items = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    for item in items:
        if item.get("restatement_checked"):
            continue
        label(item, client)
        DATASET.write_text(
            "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8"
        )
        extra = [p["acceptable_source_ids"][1:] for p in item["expected"]]
        print(item["id"], extra, item.get("review_note", ""), flush=True)


if __name__ == "__main__":
    main()
