import argparse
import json
from pathlib import Path

from . import evals, llm, mock
from .core import Router


def _target(s: str) -> tuple[str, str]:
    provider, _, model = s.partition("/")
    if not model:
        raise SystemExit(f"target must look like provider/model, got {s!r}")
    return provider, model


def main() -> None:
    llm.register_mock(mock.handler)
    p = argparse.ArgumentParser(prog="router")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("eval", help="compare models on an eval set and recommend routes")
    e.add_argument("--cases", default="eval/cases.jsonl")
    e.add_argument("--targets", nargs="+", required=True,
                   help="provider/model, e.g. anthropic/claude-haiku-4-5-20251001")
    e.add_argument("--threshold", type=float, default=0.9)
    e.add_argument("--out", help="write the markdown report here")
    e.add_argument("--write-routes", help="write recommended routes.json here")

    a = sub.add_parser("ask", help="route a single prompt")
    a.add_argument("task")
    a.add_argument("prompt")
    a.add_argument("--routes", default="router/routes.json")
    a.add_argument("--budget", type=float)

    args = p.parse_args()
    if args.cmd == "eval":
        rows = evals.run_eval(evals.load_cases(args.cases), [_target(t) for t in args.targets])
        report = evals.markdown_report(rows, args.threshold)
        print(report)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(report)
        if args.write_routes:
            agg = evals.summarize(rows)
            routes = evals.routes_from_recs(evals.recommend(agg, args.threshold), agg)
            Path(args.write_routes).parent.mkdir(parents=True, exist_ok=True)
            Path(args.write_routes).write_text(json.dumps(routes, indent=2))
            print(f"wrote {args.write_routes}")
    else:
        c = Router(args.routes, budget_usd=args.budget).run(args.task, args.prompt)
        print(c.text)
        print(f"\n[{c.provider}/{c.model} | {c.latency_s * 1000:.0f} ms | ${c.cost_usd:.6f}]")


if __name__ == "__main__":
    main()
