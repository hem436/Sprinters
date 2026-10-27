"""Run the eval set against the real parts and write the contract 07 files (WP-AG6, WP-AG7).

    cd model
    python -m agent.eval_cli --configs A B            # needs LLM keys in .env, the demo corpus ingested, business.db

The agent is built exactly as POST /query builds it (backend/app/api/query.py), and every question is stored by the
real QueryRecorder, so each eval question opens in the drill-down. Writes output/eval_results_<config>.csv and, with
both configs, output/eval_comparison.csv.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--configs", nargs="+", default=["A", "B"], choices=["A", "B"])
    parser.add_argument("--cases", type=Path, default=ROOT / "evals" / "eval_set.jsonl")
    parser.add_argument("--only", nargs="*", help="case ids to run, for example D01 S01")
    parser.add_argument("--out", type=Path, default=ROOT / "output")
    args = parser.parse_args(argv)

    for folder in ("backend", "extraction"):            # the parts this run uses, as on main
        sys.path.append(str(ROOT / folder))
    from app.api.query import build_agent                # noqa: E402  Sinngam
    from app.config import get_config                    # noqa: E402
    from app.observability.recorder import QueryRecorder  # noqa: E402

    from agent.evaluation import load_cases, run_eval, write_comparison_csv, write_results_csv

    cases = select_cases(load_cases(args.cases), args.only)
    agent = build_agent(get_config())
    args.out.mkdir(parents=True, exist_ok=True)
    summaries = {}
    for config_id in args.configs:
        run = run_eval(agent, agent.search, cases, config_id, lambda q, s, c: QueryRecorder.start(q, s, c),
                       on_case=lambda r: print(f"{r['case_id']:4} passed={r['passed']} "
                                               f"{r['outcome']}/{r['reason_code']}", flush=True))
        write_results_csv(run["results"], args.out / f"eval_results_{config_id}.csv")
        summaries[config_id] = run["summary"]
        print(json.dumps({"config": config_id, **run["summary"]}, indent=1))
    if {"A", "B"} <= set(summaries):
        write_comparison_csv(summaries["A"], summaries["B"], args.out / "eval_comparison.csv")
    return 0


def select_cases(cases: list, only: list[str] | None) -> list:
    """--only keeps the named cases. A name not in the set stops the run, so a typo never reports "0 of 0 passed"
    (review #25)."""
    if not only:
        return cases
    unknown = sorted(set(only) - {c.id for c in cases})
    if unknown:
        raise SystemExit(f"--only: no such case id: {', '.join(unknown)}")
    return [c for c in cases if c.id in only]


if __name__ == "__main__":
    raise SystemExit(main())
