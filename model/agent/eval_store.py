"""Run the eval set inside the API and store it for the Evaluation page (contract 11 sections 7 and 8; 05 /eval/runs).

The API process holds the search index (the on-disk Qdrant allows one process), so the eval runs there, in a
background thread, on the same agent the users have. Each case is written as soon as it is scored, with the measures
so far, so the page shows progress; the contract 07 files (output/eval_results_<config>.csv, eval_comparison.csv) are
written at the end of a run over the full set.
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

from agent.evaluation import load_cases, run_eval, summarize, write_comparison_csv, write_results_csv

log = logging.getLogger(__name__)

CASE_PAUSE_S = 6.0      # a pause between cases: Groq's free tier allows 8,000 tokens a minute per model
STALE_S = 600           # a RUNNING run with no progress for 10 minutes is left from a restart (a case takes < 1 min)
_lock = threading.Lock()


class RunInProgress(RuntimeError):
    """05 POST /eval/runs: 409 RUN_IN_PROGRESS."""


class UnknownCases(ValueError):
    """The request named case ids that the eval set does not have: the caller's mistake (422)."""


class EvalSetError(RuntimeError):
    """The eval set file is missing or broken: the server's fault (500), not the request's (review #25)."""


def start_run(agent, cases_path: Path, config_id: str, db_path: Path, new_recorder: Callable,
              out_dir: Path | None = None, case_ids: list[str] | None = None, pause_s: float = CASE_PAUSE_S) -> str:
    """Start one run in the background and return its run_id at once. One run at a time."""
    cases = _select(_load(cases_path), case_ids)
    if not _lock.acquire(blocking=False):
        raise RunInProgress("an evaluation run is already in progress")
    run_id, claimed = f"eval-{config_id}-{uuid.uuid4().hex[:6]}", False
    try:
        _claim(db_path, run_id, config_id, len(cases))
        claimed = True
        # files only for the full set, so A against B never compares different case sets (review #25)
        files_dir = out_dir if not case_ids else None
        threading.Thread(target=_run, name=run_id, daemon=True,
                         args=(agent, cases, config_id, db_path, new_recorder, files_dir, run_id, pause_s)).start()
    except BaseException:
        # nothing will run: free the lock and close the row, so the next request does not get 409 (review #25)
        if claimed:
            _set_status(db_path, run_id, "FAILED")
        _lock.release()
        raise
    return run_id


def _load(cases_path: Path) -> list:
    try:
        return load_cases(cases_path)
    except (OSError, ValueError) as error:
        raise EvalSetError(f"eval set {cases_path}: {error}") from error


def _select(cases: list, case_ids: list[str] | None) -> list:
    if not case_ids:
        return cases
    unknown = sorted(set(case_ids) - {c.id for c in cases})
    if unknown:
        raise UnknownCases(f"no such case id: {', '.join(unknown)}")
    return [c for c in cases if c.id in case_ids]


def _claim(db_path: Path, run_id: str, config_id: str, cases_total: int) -> None:
    """One transaction, so two API workers cannot both start a run (review #25). A RUNNING run that has made no
    progress for STALE_S was left by a restart: it becomes FAILED. Any other RUNNING run means 409."""
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for other, summary, started in conn.execute(
                "SELECT run_id, summary, started_at FROM eval_run WHERE status = 'RUNNING'").fetchall():
            if _idle_s(summary, started) < STALE_S:
                raise RunInProgress(f"evaluation run {other} is already in progress")
            conn.execute("UPDATE eval_run SET status = 'FAILED', finished_at = ? WHERE run_id = ?", (_now(), other))
            log.warning("eval run %s had no progress for %s s: marked FAILED", other, STALE_S)
        conn.execute("INSERT INTO eval_run (run_id, config_id, status, started_at, versions, summary) "
                     "VALUES (?, ?, 'RUNNING', ?, ?, ?)",
                     (run_id, config_id, _now(), json.dumps(_versions()),
                      json.dumps({"cases_total": cases_total, "cases_done": 0, "updated_at": _now()})))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _idle_s(summary: str | None, started_at: str) -> float:
    """Seconds since the run last wrote progress (or started, for a run made before progress was written)."""
    last = (json.loads(summary) if summary else {}).get("updated_at") or started_at
    return (datetime.now().astimezone() - datetime.fromisoformat(last)).total_seconds()


def _run(agent, cases, config_id, db_path, new_recorder, out_dir, run_id, pause_s) -> None:
    done: list[dict] = []
    try:
        def store_case(r: dict) -> None:
            done.append(r)
            _store_case(db_path, run_id, r, len(cases), done)
            if len(done) < len(cases):          # no pause after the last case (review #25)
                time.sleep(pause_s)

        run = run_eval(agent, agent.search, cases, config_id, new_recorder, on_case=store_case, run_id=run_id)
        _set_status(db_path, run_id, "DONE", run["summary"])
        if out_dir is not None:
            _write_files(out_dir, config_id, run, [c.id for c in cases])
        log.info("eval run %s done: %s of %s passed", run_id, run["summary"]["passed"], run["summary"]["cases_total"])
    except Exception:
        log.exception("eval run %s failed", run_id)
        _set_status(db_path, run_id, "FAILED")
    finally:
        _lock.release()


def _store_case(db_path: Path, run_id: str, r: dict, cases_total: int, done: list[dict]) -> None:
    """The case row and the measures so far, so a RUNNING run shows numbers on the page (review #25). A failed
    write (for example "database is locked") loses this row only, not the run (review #25)."""
    progress = {**summarize(done), "cases_total": cases_total, "cases_done": len(done), "updated_at": _now()}
    try:
        _write(db_path, "INSERT OR REPLACE INTO eval_result (run_id, case_id, query_id, scenario, passed, measures) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
               (run_id, r["case_id"], r["query_id"], r["scenario"], r["passed"], json.dumps(r, default=str)))
        _write(db_path, "UPDATE eval_run SET summary = ? WHERE run_id = ?", (json.dumps(progress, default=str), run_id))
    except sqlite3.Error:
        log.exception("eval run %s: case %s was not stored", run_id, r["case_id"])


def _set_status(db_path: Path, run_id: str, status: str, summary: dict | None = None) -> None:
    if summary is None:
        _write(db_path, "UPDATE eval_run SET status = ?, finished_at = ? WHERE run_id = ?", (status, _now(), run_id))
    else:
        _write(db_path, "UPDATE eval_run SET status = ?, finished_at = ?, summary = ? WHERE run_id = ?",
               (status, _now(), json.dumps(summary, default=str), run_id))


def _write_files(out_dir: Path, config_id: str, run: dict, case_ids: list[str]) -> None:
    """Contract 07: the per-case CSV; and once both configs ran on the same cases, the A against B comparison."""
    out_dir.mkdir(parents=True, exist_ok=True)
    write_results_csv(run["results"], out_dir / f"eval_results_{config_id}.csv")
    (out_dir / f"eval_summary_{config_id}.json").write_text(
        json.dumps({"case_ids": case_ids, "summary": run["summary"]}, indent=1, default=str), encoding="utf-8")
    paths = [out_dir / f"eval_summary_{c}.json" for c in ("A", "B")]
    if not all(p.exists() for p in paths):
        return
    a, b = (json.loads(p.read_text(encoding="utf-8")) for p in paths)
    if a.get("case_ids") != b.get("case_ids"):
        log.warning("eval_comparison.csv not written: A and B ran on different case sets")
        return
    write_comparison_csv(a["summary"], b["summary"], out_dir / "eval_comparison.csv")


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
