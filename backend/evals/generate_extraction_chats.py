"""Generate labelled synthetic chats for the promise extraction eval.

The label is fixed by this script before the model writes anything: a seeded
spec chooses each promise's kind, amount and the merchant turn that states it.
The generator model only writes the prose, and the script rejects chats whose
text does not carry the spec (wrong sender, missing amount, extra turns).
The generator is deliberately a different model family from the extractor.

    uv run python evals/generate_extraction_chats.py --live
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import groq

from app.ai_extraction import GROQ_DATA_POLICY, AISettings, current_data_policy

GENERATOR_MODEL = "qwen/qwen3.8-27b"
OUTPUT = BACKEND_DIR / "evals/extraction/generated.jsonl"
COUNT = 200
REVIEW_SHARE = 0.2

KIND_BRIEFS = {
    "refund": "refund {amount} to the buyer",
    "return": "accept a return and send the buyer a prepaid return label or arrange pickup",
    "replacement": "ship a replacement item",
    "order_cancellation": "cancel the order before it ships",
    "subscription": "{action} the buyer's subscription",
    "store_credit_or_exchange": "give the buyer {option}",
    "billing_correction": "{billing}",
    "dispute_handoff": "handle the matter through the buyer's open PayPal dispute and respond there",
}
CATEGORIES = [*KIND_BRIEFS, "no_promise", "multiple_promises"]
PRODUCTS = [
    "wireless earbuds", "a ceramic vase", "running shoes", "a phone case", "a desk lamp",
    "a yoga mat", "a coffee grinder", "a backpack", "a wool sweater", "a board game",
    "a water bottle", "a mechanical keyboard", "a skincare set", "a monthly snack box",
    "a photo editing app plan", "a cast iron pan", "a smartwatch strap", "a printed poster",
]
PROBLEMS = [
    "arrived damaged", "is the wrong size", "never arrived", "was charged twice",
    "stopped working after a week", "is missing parts", "was not as described",
    "was ordered by mistake", "keeps renewing after cancelling", "arrived late",
]
NO_PROMISE_STYLES = [
    "asks for photos and an order number but commits to nothing yet",
    "explains the store policy without committing to any remedy",
    "politely declines the request",
    "asks whether the buyer would prefer a refund or a replacement, without committing",
    "says they will check with the warehouse and get back, without committing to a remedy",
]


def money(cents):
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def promise_spec(kind, rng):
    amount = rng.choice([999, 1500, 2450, 3000, 4999, 7500, 12000, 18950])
    brief = KIND_BRIEFS[kind].format(
        amount=money(amount),
        action=rng.choice(["cancel", "pause"]),
        option=rng.choice(["store credit", "an exchange for a different size"]),
        billing=rng.choice(
            ["cancel the unpaid invoice", "reverse the duplicate charge",
             "correct the incorrect amount that was billed"]
        ),
    )
    return {"kind": kind, "amount_cents": amount if kind == "refund" else None, "brief": brief}


def build_spec(index, rng):
    category = CATEGORIES[index % len(CATEGORIES)]
    if category == "no_promise":
        promises = []
    elif category == "multiple_promises":
        kinds = rng.sample(["refund", "return", "replacement", "store_credit_or_exchange"], 2)
        promises = [promise_spec(kind, rng) for kind in kinds]
    else:
        promises = [promise_spec(category, rng)]
    turns = rng.choice([3, 4, 5])
    merchant_turns = [n for n in range(2, turns + 1, 2)] or [2]
    for promise in promises:
        promise["turn"] = rng.choice(merchant_turns)
    return {
        "category": category,
        "product": rng.choice(PRODUCTS),
        "problem": rng.choice(PROBLEMS),
        "turns": turns,
        "with_condition": rng.random() < 0.4,
        "with_deadline": rng.random() < 0.4,
        "no_promise_style": rng.choice(NO_PROMISE_STYLES),
        "promises": promises,
    }


def prompt(spec):
    lines = [
        (f"Write a realistic customer support chat about {spec['product']} that "
        f"{spec['problem']}. It has exactly {spec['turns']} messages. Odd-numbered "
        "messages (1, 3, 5) are from the buyer and even-numbered messages (2, 4) are "
        "from the merchant."),
    ]
    if spec["promises"]:
        for promise in spec["promises"]:
            lines.append(
                f"In message {promise['turn']} the merchant clearly commits, in the "
                f"future tense, to {promise['brief']}."
            )
            if promise["amount_cents"]:
                lines.append(
                    f"Write that amount exactly as {money(promise['amount_cents'])}."
                )
        lines.append(
            "The merchant makes no other commitment to a refund, return, replacement, "
            "cancellation, subscription change, store credit, exchange, billing "
            "correction or dispute handling anywhere in the chat."
        )
        if spec["with_condition"]:
            lines.append("Make the commitment depend on something the buyer must do first.")
        if spec["with_deadline"]:
            lines.append("Include a deadline for the commitment.")
    else:
        lines.append(
            f"The merchant {spec['no_promise_style']}. The merchant must not commit to "
            "any refund, return, replacement, cancellation, subscription change, store "
            "credit, exchange, billing correction or dispute handling."
        )
    lines.append(
        'Respond only with json: {"messages": [{"sender": "buyer" or "merchant", '
        '"text": "..."}]}. Use plain everyday language. No names of real companies.'
    )
    return "\n".join(lines)


def accept(spec, content):
    """Return labelled messages, or None when the text does not carry the spec."""
    try:
        raw = json.loads(content)["messages"]
    except (TypeError, ValueError, KeyError):
        return None
    if not isinstance(raw, list) or len(raw) != spec["turns"]:
        return None
    messages = []
    for number, message in enumerate(raw, start=1):
        sender = "buyer" if number % 2 else "merchant"
        if not isinstance(message, dict) or message.get("sender") != sender:
            return None
        text = str(message.get("text", "")).strip()
        if not text:
            return None
        messages.append({"id": f"m{number}", "sender": sender, "text": text})
    for promise in spec["promises"]:
        if promise["amount_cents"]:
            figure = money(promise["amount_cents"])
            holder = messages[promise["turn"] - 1]["text"]
            others = [m["text"] for m in messages if m["sender"] == "merchant"]
            if figure not in holder or sum(figure in text for text in others) != 1:
                return None
    return messages


def generate(client, spec, attempts=4):
    for _ in range(attempts):
        for _ in range(6):
            try:
                response = client.chat.completions.create(
                    model=GENERATOR_MODEL,
                    temperature=0.9,
                    max_tokens=1200,
                    reasoning_effort="none",
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt(spec)}],
                )
                break
            except groq.RateLimitError as error:
                wait = float(error.response.headers.get("retry-after") or 20)
                time.sleep(min(wait, 120))
            except groq.APIStatusError:
                response = None
                break
        else:
            raise RuntimeError("Generator rate limit did not clear")
        if response is None:
            continue
        messages = accept(spec, response.choices[0].message.content)
        if messages:
            return messages
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call Groq (required)")
    parser.add_argument("--count", type=int, default=COUNT)
    parser.add_argument("--seed", type=int, default=20261108)
    args = parser.parse_args()
    if not args.live:
        parser.error("Generation calls Groq; pass --live to run it")
    if current_data_policy() != GROQ_DATA_POLICY:
        parser.error(
            "Groq calls require RESOLVE_AI_DATA_POLICY=minimized_standard_retention in the "
            "process environment (app.inference never reads .env). Use it only for "
            "synthetic data."
        )
    key = AISettings().groq_api_key
    if key is None:
        parser.error("GROQ_API_KEY is not set")
    rng = random.Random(args.seed)
    client = groq.Groq(api_key=key.get_secret_value(), max_retries=2, timeout=60)

    done = {}
    if OUTPUT.exists():
        for line in OUTPUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                done[item["id"]] = item
    specs = [build_spec(index, rng) for index in range(args.count)]
    review = set(rng.sample(range(args.count), round(args.count * REVIEW_SHARE)))
    rejected = 0
    with OUTPUT.open("a", encoding="utf-8") as output:
        for index, spec in enumerate(specs):
            item_id = f"gen-{index + 1:03d}"
            if item_id in done:
                continue
            messages = generate(client, spec)
            if messages is None:
                rejected += 1
                print(f"{item_id}: rejected after retries", flush=True)
                continue
            item = {
                "id": item_id,
                "category": spec["category"],
                "messages": messages,
                "expected": [
                    {
                        "kind": promise["kind"],
                        "amount_cents": promise["amount_cents"],
                        "source_message_id": f"m{promise['turn']}",
                    }
                    for promise in spec["promises"]
                ],
                "label_source": "generated_from_spec",
                "generator_model": GENERATOR_MODEL,
                "generator_provider": "groq",
                "needs_manual_review": index in review,
                "manually_reviewed": False,
            }
            output.write(json.dumps(item, ensure_ascii=False) + "\n")
            output.flush()
            print(f"{item_id}: {spec['category']}", flush=True)
    print(f"Rejected specs: {rejected}")


if __name__ == "__main__":
    main()
