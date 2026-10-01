"""Deterministic stand-in models for offline runs and CI.

`mock-small` behaves like a cheap, weak model; `mock-large` like a pricier, stronger one.
Results from these are NOT a benchmark: they only exercise the harness. Use real
providers (see README) for real numbers.
"""
import json
import re

NEG = {"hate", "terrible", "awful", "broken", "worst", "refund", "angry"}
POS = {"love", "great", "amazing", "excellent", "fantastic", "happy"}


def handler(system: str, prompt: str, model: str) -> str:
    large = model == "mock-large"
    if "Classify sentiment" in prompt:
        words = set(re.findall(r"[a-z]+", prompt.split("Text:")[-1].lower()))
        return "negative" if words & NEG else "positive" if words & POS else "neutral"
    if "as JSON" in prompt or "JSON with keys" in prompt:
        m = re.search(r"Text: (\w+) is (\d+)", prompt)
        if large and m:
            return json.dumps({"name": m.group(1), "age": int(m.group(2))})
        return "Name: " + (m.group(1) if m else "unknown")
    if prompt.startswith("Summarize"):
        body = prompt.split("\n", 1)[-1].split()
        return " ".join(body[: 12 if large else 30])
    m = re.search(r"What is (\d+) \* (\d+)", prompt)
    if m:
        return str(int(m.group(1)) * int(m.group(2))) if large else "400"
    if "arrive" in prompt:
        return "6:05 pm" if large else "6:15 pm"
    return "I don't know."
