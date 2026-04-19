"""LLM-powered trace annotation — classifies reasoning blocks and flags mistakes."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

from ard.schema import Trace

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
MAX_BATCH = 40

CATEGORIES = [
    "planning",
    "investigating",
    "implementing",
    "debugging",
    "refactoring",
    "testing",
    "explaining",
]

FLAGS = [
    "tangent",
    "backtracking",
    "wrong_file",
    "unnecessary",
]

SYSTEM_PROMPT = f"""You are an agent execution analyzer. You will receive a list of reasoning blocks from an AI agent's execution trace. Each block is the agent's internal monologue or response at a point in time.

For each block, classify it and optionally flag issues.

Categories (pick exactly one):
{chr(10).join(f"- {c}" for c in CATEGORIES)}

Optional flags (pick zero or one):
{chr(10).join(f"- {f}" for f in FLAGS)}
- null (no flag, this is normal behavior)

Respond with a JSON array of objects, one per input block, in order:
[{{"category": "investigating", "flag": null}}, {{"category": "debugging", "flag": "backtracking"}}, ...]

Be concise. Only flag genuinely problematic behavior, not normal workflow.

Return ONLY the JSON array. No markdown, no explanation, no code fences."""


def _call_api(reasoning_texts: list[str], api_key: str) -> list[dict[str, Any]]:
    """Call Anthropic API to classify reasoning blocks."""
    numbered = "\n\n".join(f"[{i}] {text[:300]}" for i, text in enumerate(reasoning_texts))

    body = json.dumps(
        {
            "model": MODEL,
            "max_tokens": 2048,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": f"Classify these {len(reasoning_texts)} reasoning blocks:\n\n{numbered}",
                }
            ],
        }
    ).encode()

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    text = data["content"][0]["text"]
    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end == 0:
        return [{"category": "explaining", "flag": None}] * len(reasoning_texts)
    json_str = text[start:end]
    # Strip control characters that break JSON parsing
    json_str = re.sub(r"[\x00-\x1f\x7f]", " ", json_str)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Try extracting individual objects if the array is malformed
        results = []
        for m in re.finditer(r"\{[^{}]+\}", json_str):
            try:
                results.append(json.loads(m.group()))
            except json.JSONDecodeError:
                continue
        if results:
            return results
        return [{"category": "explaining", "flag": None}] * len(reasoning_texts)


def annotate_trace(trace: Trace) -> Trace:
    """Add LLM-generated annotations to reasoning events in a trace."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable required for --analyze. "
            "Set it with: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    reasoning_events = [
        (i, e) for i, e in enumerate(trace.events) if e.type == "reasoning" and e.data.get("text")
    ]

    if not reasoning_events:
        return trace

    # Process in batches
    for batch_start in range(0, len(reasoning_events), MAX_BATCH):
        batch = reasoning_events[batch_start : batch_start + MAX_BATCH]
        texts = [e.data["text"] for _, e in batch]

        try:
            results = _call_api(texts, api_key)
        except Exception as exc:
            print(f"Warning: analysis failed for batch {batch_start}: {exc}")
            continue

        for (event_idx, event), result in zip(batch, results):
            if isinstance(result, dict):
                event.data["category"] = result.get("category", "explaining")
                flag = result.get("flag")
                if flag:
                    event.data["flag"] = flag

    return trace
