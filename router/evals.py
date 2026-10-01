"""Eval harness: run the same cases against several models, then recommend routes."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import llm


def run_check(check: dict, text: str) -> bool:
    kind, value = check["type"], check.get("value")
    if kind == "contains":
        return value.lower() in text.lower()
    if kind == "exact":
        return text.strip().lower() == value.lower()
    if kind == "regex":
        return re.search(value, text) is not None
    if kind == "max_words":
        return len(text.split()) <= value
    if kind == "json_keys":
        try:
            obj = llm.extract_json(text)
        except ValueError:
            return False
        return isinstance(obj, dict) and all(k in obj for k in value)
    raise ValueError(f"unknown check type {kind!r}")


def load_cases(path: str) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def run_eval(cases: list[dict], targets: list[tuple[str, str]], complete_fn=None) -> list[dict]:
    complete_fn = complete_fn or llm.complete
    rows = []
    for provider, model in targets:
        for case in cases:
            row = {"target": f"{provider}/{model}", "task": case["task"], "id": case["id"],
                   "passed": False, "latency": 0.0, "cost": 0.0, "error": None}
            try:
                c = complete_fn(case["prompt"], system=case.get("system", ""),
                                provider=provider, model=model)
                row.update(passed=run_check(case["check"], c.text), latency=c.latency_s, cost=c.cost_usd)
            except llm.LLMError as e:
                row["error"] = str(e)
            rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    agg: dict = {}
    for r in rows:
        a = agg.setdefault((r["target"], r["task"]), {"n": 0, "passed": 0, "cost": 0.0, "latency": 0.0})
        a["n"] += 1
        a["passed"] += int(r["passed"])
        a["cost"] += r["cost"]
        a["latency"] += r["latency"]
    return agg


def recommend(agg: dict, threshold: float = 0.9) -> dict:
    """Per task: cheapest model whose pass rate meets the threshold; else the best performer."""
    by_task: dict = {}
    for (target, task), a in agg.items():
        by_task.setdefault(task, []).append((target, a["passed"] / a["n"], a["cost"]))
    recs = {}
    for task, options in by_task.items():
        ok = [o for o in options if o[1] >= threshold]
        pick = min(ok, key=lambda o: o[2]) if ok else max(options, key=lambda o: (o[1], -o[2]))
        recs[task] = {"target": pick[0], "pass_rate": pick[1], "cost": pick[2],
                      "met_threshold": bool(ok)}
    return recs


def routes_from_recs(recs: dict, agg: dict) -> dict:
    """Build a routes.json: recommended model first, then other models by pass rate."""
    def overall(target):
        rows = [a for (t, _), a in agg.items() if t == target]
        return sum(a["passed"] for a in rows) / max(1, sum(a["n"] for a in rows))

    def step(t):
        provider, model = t.split("/", 1)
        return {"provider": provider, "model": model}

    targets = sorted({t for t, _ in agg}, key=overall, reverse=True)
    routes = {"tasks": {}}
    for task, rec in recs.items():
        order = [rec["target"]] + [t for t in targets if t != rec["target"]]
        routes["tasks"][task] = {"chain": [step(t) for t in order]}
    routes["default"] = {"chain": [step(t) for t in targets]}
    return routes


def markdown_report(rows: list[dict], threshold: float) -> str:
    agg = summarize(rows)
    targets = sorted({t for t, _ in agg})
    out = ["## Overall", "", "| model | pass rate | avg latency (ms) | total cost (USD) | cost per pass (USD) |",
           "|---|---|---|---|---|"]
    for t in targets:
        sub = [a for (tt, _), a in agg.items() if tt == t]
        n, p = sum(a["n"] for a in sub), sum(a["passed"] for a in sub)
        cost, lat = sum(a["cost"] for a in sub), sum(a["latency"] for a in sub)
        per_pass = f"{cost / p:.6f}" if p else "n/a"
        out.append(f"| {t} | {p}/{n} ({p / n:.0%}) | {lat / n * 1000:.1f} | {cost:.6f} | {per_pass} |")
    out += ["", "## By task", "", "| task | model | pass rate | cost (USD) |", "|---|---|---|---|"]
    for (t, task), a in sorted(agg.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        out.append(f"| {task} | {t} | {a['passed']}/{a['n']} | {a['cost']:.6f} |")
    out += ["", f"## Recommended routes (cheapest model with pass rate >= {threshold:.0%})", ""]
    for task, r in sorted(recommend(agg, threshold).items()):
        note = "" if r["met_threshold"] else "  (no model met the threshold; best available)"
        out.append(f"- **{task}** -> `{r['target']}` ({r['pass_rate']:.0%}, ${r['cost']:.6f}){note}")
    errs = [r for r in rows if r["error"]]
    if errs:
        out += ["", "## Errors", ""] + [f"- {r['target']} / {r['id']}: {r['error']}" for r in errs]
    return "\n".join(out) + "\n"
