"""Groq promise-extraction transport; receives an already minimized transcript."""

import json


def complete_promises(
    client, model, timeout, case_id, transcript, system_prompt, max_tokens
):
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        timeout=timeout,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Transcript as JSON data for case "
                + str(case_id)
                + ":\n"
                + json.dumps({"messages": transcript}, ensure_ascii=False),
            },
        ],
    )
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", None)
    if not isinstance(tokens, int):
        tokens = (getattr(usage, "prompt_tokens", 0) or 0) + (
            getattr(usage, "completion_tokens", 0) or 0
        )
    return response.choices[0].message.content, tokens
