# model-router-evals

[![CI](https://github.com/geocustomss/model-router-evals/actions/workflows/ci.yml/badge.svg)](https://github.com/geocustomss/model-router-evals/actions/workflows/ci.yml)

Route each type of AI task to the **cheapest model that's good enough**, and prove it with an eval harness.

Most teams pick one model for everything. This project does the opposite: run the same test cases against several
providers (Anthropic, OpenAI, Gemini, xAI Grok), measure pass rate, latency and cost per task type, then generate a routing
table automatically. At runtime the router sends each task to its assigned model, falls back to the next one if a
provider fails, logs every call, and enforces a spend budget.

```
eval cases ──► run on N models ──► pass rate / latency / cost per task ──► recommended routes.json
                                                                                 │
app code ──► Router.run(task, prompt) ──► primary model ──fail──► fallback ──► JSONL call log + budget guard
```

## Quickstart (no API keys needed)

```bash
python -m unittest discover -s tests -v
python -m router eval --targets mock/mock-small mock/mock-large --write-routes out/routes.generated.json
```

## Use real models

```bash
cp .env.example .env && export $(grep -v '^#' .env | xargs)   # add your keys
python -m router eval --targets \
  anthropic/claude-haiku-4-5-20251001 anthropic/claude-sonnet-5-5 openai/gpt-4o-mini gemini/gemini-2.0-flash \
  xai/YOUR-GROK-MODEL \
  --out docs/real_report.md --write-routes router/routes.json
python -m router ask classify "Classify sentiment as positive, negative, or neutral. Text: great service" --budget 0.05
```

Model names change often. Update them in `router/routes.json` and prices in `router/pricing.json`
(prices there are examples; verify them before trusting cost numbers).

## Sample report (mock models: demonstrates the harness, not real model quality)

## Overall

| model | pass rate | avg latency (ms) | total cost (USD) | cost per pass (USD) |
|---|---|---|---|---|
| mock/mock-large | 8/8 (100%) | 0.0 | 0.000375 | 0.000047 |
| mock/mock-small | 3/8 (38%) | 0.0 | 0.000041 | 0.000014 |

## By task

| task | model | pass rate | cost (USD) |
|---|---|---|---|
| classify | mock/mock-large | 3/3 | 0.000109 |
| classify | mock/mock-small | 3/3 | 0.000011 |
| extract_json | mock/mock-large | 2/2 | 0.000108 |
| extract_json | mock/mock-small | 0/2 | 0.000007 |
| reasoning | mock/mock-large | 2/2 | 0.000038 |
| reasoning | mock/mock-small | 0/2 | 0.000004 |
| summarize | mock/mock-large | 1/1 | 0.000120 |
| summarize | mock/mock-small | 0/1 | 0.000019 |

## Recommended routes (cheapest model with pass rate >= 90%)

- **classify** -> `mock/mock-small` (100%, $0.000011)
- **extract_json** -> `mock/mock-large` (100%, $0.000108)
- **reasoning** -> `mock/mock-large` (100%, $0.000038)
- **summarize** -> `mock/mock-large` (100%, $0.000120)

> Replace this section with your own run against real models. Add 30+ cases from your real workload;
> 8 cases is a demo, not evidence.

## Design decisions

- **Pass/fail checks, not vibes**: each case has a deterministic check (exact, contains, regex, max words, JSON keys),
  so results are reproducible and cheap to rerun on every model release.
- **Cheapest model above a quality bar**: `recommend()` picks by cost subject to a pass-rate threshold. This is the
  actual cost-optimization lever: classification rarely needs a frontier model.
- **Fallback chains + budget guard**: provider outages and runaway loops are handled in code, and every attempt
  (including failures) is logged to `logs/calls.jsonl`.
- **Standard library only**: provider calls go through one small client (`router/llm.py`) with retries on 429/5xx,
  which keeps the repo easy to read, test and run in CI.

## Limitations / next steps

- Checks are programmatic; add an LLM-as-judge check for open-ended tasks (and measure the judge's own reliability).
- Pass rates on small samples are noisy; add confidence intervals and multiple runs per case.
- Add a latency percentile view (p50/p95) and streaming support.
- Provider adapters are written against public REST docs; live behavior depends on your account and current model names.
