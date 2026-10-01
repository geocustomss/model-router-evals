"""Task-based model router with fallbacks, cost tracking and a spend budget."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import llm


class BudgetExceeded(RuntimeError):
    pass


class Router:
    def __init__(self, routes_path: str = "router/routes.json", log_path: str = "logs/calls.jsonl",
                 budget_usd: float | None = None, complete_fn=None):
        self.routes = json.loads(Path(routes_path).read_text())
        self.log_path = Path(log_path)
        self.budget_usd = budget_usd
        self.spent_usd = 0.0
        self.complete_fn = complete_fn or llm.complete

    def chain_for(self, task: str) -> list[dict]:
        return self.routes.get("tasks", {}).get(task, self.routes["default"])["chain"]

    def _log(self, record: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"ts": time.time(), **record}) + "\n")

    def run(self, task: str, prompt: str, system: str = "", max_tokens: int = 1024) -> llm.Completion:
        errors = []
        for step in self.chain_for(task):
            if self.budget_usd is not None and self.spent_usd >= self.budget_usd:
                raise BudgetExceeded(f"spent ${self.spent_usd:.4f} of ${self.budget_usd:.4f}")
            try:
                c = self.complete_fn(prompt, system=system, provider=step["provider"],
                                     model=step["model"], max_tokens=max_tokens)
            except llm.LLMError as e:
                errors.append(f"{step['provider']}/{step['model']}: {e}")
                self._log({"task": task, "ok": False, **step, "error": str(e)})
                continue  # fall back to the next model in the chain
            self.spent_usd += c.cost_usd
            self._log({"task": task, "ok": True, "provider": c.provider, "model": c.model,
                       "latency_s": round(c.latency_s, 4), "cost_usd": c.cost_usd,
                       "input_tokens": c.input_tokens, "output_tokens": c.output_tokens})
            return c
        raise llm.LLMError("all models in chain failed: " + " | ".join(errors))
