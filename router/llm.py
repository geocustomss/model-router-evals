"""Tiny provider-agnostic LLM client (standard library only).

Providers: anthropic, openai, gemini, xai (Grok), mock. Every call returns a Completion with
token counts, latency and estimated cost, so cost/quality tradeoffs are measurable.
The `mock` provider delegates to a handler registered by the project, which lets
tests, CI and demos run without API keys or network access.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_PRICING_FILE = Path(__file__).with_name("pricing.json")


class LLMError(RuntimeError):
    """Raised when a provider call fails (after retries) or returns unusable output."""


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0


_mock_handler = None


def register_mock(handler) -> None:
    """handler(system: str, prompt: str, model: str) -> str"""
    global _mock_handler
    _mock_handler = handler


def _need(env: str) -> str:
    key = os.getenv(env)
    if not key:
        raise LLMError(f"{env} is not set")
    return key


def _http_post(url: str, headers: dict, payload: dict, timeout: int = 60, retries: int = 2) -> dict:
    data = json.dumps(payload).encode()
    last: Exception = LLMError("request failed")
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json", **headers}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            last = LLMError(f"HTTP {e.code}: {body}")
            if e.code not in (429, 500, 502, 503, 529):  # only retry transient errors
                raise last
        except (urllib.error.URLError, TimeoutError) as e:
            last = LLMError(f"network error: {e}")
        time.sleep(2**attempt)
    raise last


def _anthropic(model, system, prompt, max_tokens):
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    if system:
        payload["system"] = system
    d = _http_post("https://api.anthropic.com/v1/messages",
                   {"x-api-key": _need("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
                   payload)
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    u = d.get("usage", {})
    return text, u.get("input_tokens", 0), u.get("output_tokens", 0)


def _openai(model, system, prompt, max_tokens):
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    d = _http_post("https://api.openai.com/v1/chat/completions",
                   {"Authorization": f"Bearer {_need('OPENAI_API_KEY')}"},
                   {"model": model, "messages": messages, "max_completion_tokens": max_tokens})
    u = d.get("usage", {})
    return (d["choices"][0]["message"]["content"] or "",
            u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


def _xai(model, system, prompt, max_tokens):
    """xAI (Grok) exposes an OpenAI-compatible chat completions endpoint."""
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    d = _http_post("https://api.x.ai/v1/chat/completions",
                   {"Authorization": f"Bearer {_need('XAI_API_KEY')}"},
                   {"model": model, "messages": messages, "max_tokens": max_tokens})
    u = d.get("usage", {})
    return (d["choices"][0]["message"]["content"] or "",
            u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


def _gemini(model, system, prompt, max_tokens):
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"maxOutputTokens": max_tokens}}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    d = _http_post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"x-goog-api-key": _need("GEMINI_API_KEY")}, payload)
    parts = d["candidates"][0]["content"].get("parts", [])
    u = d.get("usageMetadata", {})
    return ("".join(p.get("text", "") for p in parts),
            u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))


_PROVIDERS = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini, "xai": _xai}


def estimate_cost(provider: str, model: str, tin: int, tout: int) -> float:
    try:
        price = json.loads(_PRICING_FILE.read_text()).get(f"{provider}/{model}")
    except (OSError, ValueError):
        price = None
    if not isinstance(price, dict):
        return 0.0
    return (tin * price["in"] + tout * price["out"]) / 1_000_000


def complete(prompt: str, *, system: str = "", provider: str = "mock",
             model: str = "mock-small", max_tokens: int = 1024) -> Completion:
    t0 = time.perf_counter()
    if provider == "mock":
        if _mock_handler is None:
            raise LLMError("no mock handler registered")
        text = _mock_handler(system, prompt, model)
        tin, tout = len(system + prompt) // 4, len(text) // 4
    elif provider in _PROVIDERS:
        text, tin, tout = _PROVIDERS[provider](model, system, prompt, max_tokens)
    else:
        raise LLMError(f"unknown provider {provider!r}")
    return Completion(text, provider, model, tin, tout, time.perf_counter() - t0,
                      estimate_cost(provider, model, tin, tout))


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply (handles code fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in reply")
    obj, _ = json.JSONDecoder().raw_decode(t[min(starts):])
    return obj


def complete_json(prompt: str, validate, *, system: str = "", retries: int = 2,
                  complete_fn=None, **kw):
    """Call the model until it returns JSON that passes `validate` (which raises ValueError).

    On failure the error is fed back to the model. Returns (obj, [Completion, ...]) so
    callers can account for the cost of retries.
    """
    complete_fn = complete_fn or complete
    attempts, current, err = [], prompt, "unknown"
    for _ in range(retries + 1):
        c = complete_fn(current, system=system, **kw)
        attempts.append(c)
        try:
            obj = extract_json(c.text)
            validate(obj)
            return obj, attempts
        except ValueError as e:
            err = str(e)
            current = (f"{prompt}\n\nYour previous reply was invalid ({err}). "
                       "Reply again with ONLY valid JSON matching the requested schema.")
    raise LLMError(f"no valid JSON after {retries + 1} attempts: {err}")
