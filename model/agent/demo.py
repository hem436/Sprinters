"""The demo check (contract 07 `demo/script.md`, contract 12 WP-AG7): ask the 10 demo questions through the running API.

    cd model
    python -m agent.demo                                   # API at http://localhost:8000
    python -m agent.demo --api http://arka-server:8000 --only C01 B01

Each scene is a case of `evals/eval_set.jsonl`, so the demo and the evaluation expect the same thing. A scene passes when
the route, the expected behaviour and the answer words all match. Exit code 0 only when every scene passes.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from agent.evaluation import BEHAVIOURS, criteria_ok, load_cases
from agent.types import QueryResponse

ROOT = Path(__file__).resolve().parents[2]
# demo/script.md, in the order we show them: case id, who presents it
SCENES = [("C01", "Arka"), ("M01", "Arka"), ("X01", "Arka"), ("D01", "Hemant"), ("S01", "Sinngam"),
          ("B01", "Sinngam"), ("B02", "Sinngam"), ("F04", "Myank"), ("I01", "Arka"), ("N01", "Arka")]


def post(api: str, path: str, body: dict, timeout: float = 120) -> dict:
    request = urllib.request.Request(api.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def run_scene(api: str, case) -> tuple[bool, str]:
    """Ask every turn of the case in one session; judge the last answer."""
    session = f"demo-{uuid.uuid4().hex[:8]}"
    data = {}
    for turn in case.turns:
        data = post(api, "/query", {"question": turn, "session_id": session})
    r = QueryResponse.model_validate(data)
    checks = {
        "route": r.route == case.expected_route,
        "behaviour": BEHAVIOURS[case.expected_behavior](r),
        "words": criteria_ok(r.answer_markdown, case.answer_must_include, case.answer_must_not_include),
    }
    failed = [name for name, ok in checks.items() if not ok]
    detail = f"{r.route} {r.outcome}/{r.reason_code} {r.latency_ms} ms, cost {r.usage.cost_usd}"
    return not failed, detail + (f"  FAILED: {', '.join(failed)}; answer: {r.answer_markdown[:160]!r}" if failed else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--only", nargs="*", help="case ids, for example C01 B01")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    try:
        with urllib.request.urlopen(args.api.rstrip("/") + "/health", timeout=10) as response:
            print("health:", response.read().decode()[:200])
    except (urllib.error.URLError, OSError) as error:
        print(f"the API at {args.api} does not answer: {error}")
        return 2

    cases = {c.id: c for c in load_cases(ROOT / "evals" / "eval_set.jsonl")}
    passed = 0
    scenes = [(cid, who) for cid, who in SCENES if not args.only or cid in args.only]
    for n, (case_id, presenter) in enumerate(scenes, start=1):
        case = cases[case_id]
        started = time.perf_counter()
        try:
            ok, detail = run_scene(args.api, case)
        except (urllib.error.URLError, OSError, ValueError) as error:
            ok, detail = False, f"request failed: {error}"
        passed += ok
        print(f"{n:2}. {'PASS' if ok else 'FAIL'} {case_id} ({presenter}) {case.turns[-1]!r}  "
              f"[{time.perf_counter() - started:.1f} s] {detail}", flush=True)
    print(f"\n{passed} of {len(scenes)} scenes pass")
    return 0 if passed == len(scenes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
