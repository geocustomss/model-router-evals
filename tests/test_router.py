import json
import os
import tempfile
import unittest
from unittest import mock as umock
from pathlib import Path

from router import evals, llm, mock
from router.core import BudgetExceeded, Router

llm.register_mock(mock.handler)


def make_routes(chain):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"default": {"chain": chain}, "tasks": {}}, f)
    f.close()
    return f.name


class ChecksTest(unittest.TestCase):
    def test_checks(self):
        self.assertTrue(evals.run_check({"type": "contains", "value": "AB"}, "xaby"))
        self.assertTrue(evals.run_check({"type": "exact", "value": "yes"}, " Yes\n"))
        self.assertFalse(evals.run_check({"type": "max_words", "value": 2}, "a b c"))
        self.assertTrue(evals.run_check({"type": "json_keys", "value": ["a"]}, '```json\n{"a": 1}\n```'))
        self.assertFalse(evals.run_check({"type": "json_keys", "value": ["a"]}, "not json"))
        self.assertTrue(evals.run_check({"type": "regex", "value": r"\d{3}"}, "id 391"))


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.log = tempfile.mktemp(suffix=".jsonl")

    def test_falls_back_when_first_model_fails(self):
        def fake(prompt, **kw):
            if kw["model"] == "bad":
                raise llm.LLMError("boom")
            return llm.Completion("ok", kw["provider"], kw["model"], cost_usd=0.01)

        routes = make_routes([{"provider": "mock", "model": "bad"}, {"provider": "mock", "model": "good"}])
        r = Router(routes, self.log, complete_fn=fake)
        c = r.run("anything", "hi")
        self.assertEqual(c.model, "good")
        lines = [json.loads(l) for l in Path(self.log).read_text().splitlines()]
        self.assertEqual([l["ok"] for l in lines], [False, True])

    def test_all_fail_raises(self):
        def fake(prompt, **kw):
            raise llm.LLMError("down")
        r = Router(make_routes([{"provider": "mock", "model": "a"}]), self.log, complete_fn=fake)
        with self.assertRaises(llm.LLMError):
            r.run("t", "hi")

    def test_budget_stops_spending(self):
        fake = lambda prompt, **kw: llm.Completion("ok", "mock", "m", cost_usd=0.6)
        r = Router(make_routes([{"provider": "mock", "model": "m"}]), self.log,
                   budget_usd=1.0, complete_fn=fake)
        r.run("t", "1")
        r.run("t", "2")
        with self.assertRaises(BudgetExceeded):
            r.run("t", "3")


class EvalTest(unittest.TestCase):
    def test_end_to_end_with_mock_models(self):
        cases = evals.load_cases("eval/cases.jsonl")
        rows = evals.run_eval(cases, [("mock", "mock-small"), ("mock", "mock-large")])
        agg = evals.summarize(rows)
        rate = lambda t: sum(a["passed"] for (x, _), a in agg.items() if x == t) / len(cases)
        self.assertEqual(rate("mock/mock-large"), 1.0)
        self.assertLess(rate("mock/mock-small"), 1.0)

    def test_recommend_picks_cheapest_passing(self):
        agg = {("a/cheap", "t"): {"n": 10, "passed": 9, "cost": 0.1, "latency": 1},
               ("a/pricey", "t"): {"n": 10, "passed": 10, "cost": 1.0, "latency": 1},
               ("a/cheap", "hard"): {"n": 10, "passed": 4, "cost": 0.1, "latency": 1},
               ("a/pricey", "hard"): {"n": 10, "passed": 9, "cost": 1.0, "latency": 1}}
        recs = evals.recommend(agg, 0.9)
        self.assertEqual(recs["t"]["target"], "a/cheap")
        self.assertEqual(recs["hard"]["target"], "a/pricey")
        routes = evals.routes_from_recs(recs, agg)
        self.assertEqual(routes["tasks"]["t"]["chain"][0]["model"], "cheap")
        self.assertEqual(len(routes["tasks"]["t"]["chain"]), 2)


class JsonHelpersTest(unittest.TestCase):
    def test_complete_json_retries_with_feedback(self):
        replies = iter(["nope", '{"x": 1}'])
        seen = []

        def fake(prompt, **kw):
            seen.append(prompt)
            return llm.Completion(next(replies), "mock", "m")

        def validate(o):
            if "x" not in o:
                raise ValueError("missing x")

        obj, attempts = llm.complete_json("give json", validate, complete_fn=fake)
        self.assertEqual(obj, {"x": 1})
        self.assertEqual(len(attempts), 2)
        self.assertIn("previous reply was invalid", seen[1])


class ProviderShapeTest(unittest.TestCase):
    """Offline checks that each provider adapter builds the right request and parses the reply."""

    def call(self, provider, reply, env):
        captured = {}

        def fake_post(url, headers, payload, **kw):
            captured.update(url=url, headers=headers, payload=payload)
            return reply

        with umock.patch.object(llm, "_http_post", fake_post), umock.patch.dict(os.environ, env):
            c = llm.complete("hello", system="be brief", provider=provider, model="m1", max_tokens=50)
        return c, captured

    def test_xai_grok(self):
        reply = {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        c, req = self.call("xai", reply, {"XAI_API_KEY": "k"})
        self.assertEqual((c.text, c.input_tokens, c.output_tokens), ("hi", 3, 2))
        self.assertEqual(req["url"], "https://api.x.ai/v1/chat/completions")
        self.assertEqual(req["headers"]["Authorization"], "Bearer k")
        self.assertEqual(req["payload"]["messages"][0], {"role": "system", "content": "be brief"})

    def test_anthropic(self):
        reply = {"content": [{"type": "text", "text": "yo"}], "usage": {"input_tokens": 4, "output_tokens": 1}}
        c, req = self.call("anthropic", reply, {"ANTHROPIC_API_KEY": "k"})
        self.assertEqual((c.text, c.input_tokens), ("yo", 4))
        self.assertEqual(req["headers"]["x-api-key"], "k")
        self.assertEqual(req["payload"]["system"], "be brief")

    def test_gemini(self):
        reply = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                 "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}}
        c, req = self.call("gemini", reply, {"GEMINI_API_KEY": "k"})
        self.assertEqual((c.text, c.output_tokens), ("ok", 1))
        self.assertIn("models/m1:generateContent", req["url"])

    def test_missing_key_is_a_clean_error(self):
        with umock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(llm.LLMError):
                llm.complete("x", provider="xai", model="m")


if __name__ == "__main__":
    unittest.main()
