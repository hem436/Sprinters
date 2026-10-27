"""Run the eval set inside the API and store it for the Evaluation page (contract 11 sections 7 and 8; 05 /eval/runs).

The API process holds the search index (the on-disk Qdrant allows one process), so the eval runs there, in a
background thread, on the same agent the users have. Each case is written as soon as it is scored, so the page shows
progress; the contract 07 files (output/eval_results_<config>.csv, eval_comparison.csv) are written at the end.
"""
import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from agent.evaluation import load_cases, run_eval, write_comparison_csv, write_results_csv

log = logging.getLogger(__name__)

CASE_PAUSE_S = 6.0      # a pause after each case: Groq's free tier allows 8,000 tokens a minute per model
_lock = threading.Lock()


class RunInProgress(RuntimeError):
    """05 POST /eval/runs: 409 RUN_IN_PROGRESS."""


def start_run(agent, cases_path: Path, config_id: str, db_path: Path, new_recorder: Callable,
              out_dir: Path | None = None, case_ids: list[str] | None = None, pause_s: float = CASE_PAUSE_S) -> str:
    """Start one run in the background and return its run_id at once. One run at a time."""
    cases = load_cases(cases_path)
    if case_ids:
        unknown = sorted(set(case_ids) - {c.id for c in cases})
        if unknown:
            raise ValueError(f"no such case id: {', '.join(unknown)}")
        cases = [c for c in cases if c.id in case_ids]
    if not _lock.acquire(blocking=False):
        raise RunInProgress("an evaluation run is already in progress")
    run_id = f"eval-{config_id}-{uuid.uuid4().hex[:6]}"
    try:
        _write(db_path, "INSERT INTO eval_run (run_id, config_id, status, started_at, versions, summary) "
                        "VALUES (?, ?, 'RUNNING', ?, ?, ?)",
               (run_id, config_id, _now(), json.dumps(_versions()), json.dumps({"cases_total": len(cases)})))
    except Exception:
        _lock.release()
        raise
    threading.Thread(target=_run, name=run_id, daemon=True,
                     args=(agent, cases, config_id, db_path, new_recorder, out_dir, run_id, pause_s)).start()
    return run_id


def _run(agent, cases, config_id, db_path, new_recorder, out_dir, run_id, pause_s) -> None:
    try:
        def store_case(r: dict) -> None:
            _write(db_path, "INSERT OR REPLACE INTO eval_result (run_id, case_id, query_id, scenario, passed, measures) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                   (run_id, r["case_id"], r["query_id"], r["scenario"], r["passed"], json.dumps(r, default=str)))
            time.sleep(pause_s)

        run = run_eval(agent, agent.search, cases, config_id, new_recorder, on_case=store_case, run_id=run_id)
        _write(db_path, "UPDATE eval_run SET status = 'DONE', finished_at = ?, summary = ? WHERE run_id = ?",
               (_now(), json.dumps(run["summary"], default=str), run_id))
        if out_dir is not None:
            _write_files(out_dir, config_id, run)
        log.info("eval run %s done: %s of %s passed", run_id, run["summary"]["passed"], run["summary"]["cases_total"])
    except Exception:
        log.exception("eval run %s failed", run_id)
        _write(db_path, "UPDATE eval_run SET status = 'FAILED', finished_at = ? WHERE run_id = ?", (_now(), run_id))
    finally:
        _lock.release()


def _write_files(out_dir: Path, config_id: str, run: dict) -> None:
    """Contract 07: the per-case CSV; and once both configs have a run, the A against B comparison."""
    out_dir.mkdir(parents=True, exist_ok=True)
    write_results_csv(run["results"], out_dir / f"eval_results_{config_id}.csv")
    (out_dir / f"eval_summary_{config_id}.json").write_text(json.dumps(run["summary"], indent=1, default=str),
                                                            encoding="utf-8")
    summaries = {c: out_dir / f"eval_summary_{c}.json" for c in ("A", "B")}
    if all(p.exists() for p in summaries.values()):
        write_comparison_csv(*(json.loads(summaries[c].read_text(encoding="utf-8")) for c in ("A", "B")),
                             out_dir / "eval_comparison.csv")


def _versions() -> dict:
    from agent.answer import ANSWER_PROMPT_VERSION
    from agent.router import ROUTE_PROMPT_VERSION
    return {"answer_prompt": ANSWER_PROMPT_VERSION, "route_prompt": ROUTE_PROMPT_VERSION}


def _write(db_path: Path, sql: str, params: tuple) -> None:
    """One short connection per write, so the thread never shares a connection with the API."""
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        with conn:
            conn.execute(sql, params)
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
