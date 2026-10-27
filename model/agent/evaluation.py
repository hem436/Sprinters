"""WP-AG6: the evaluation runner (contract 11 sections 7 and 8, contract 07).

Runs every case of `evals/eval_set.jsonl` through the real `Agent.answer`, scores it, and returns one result per case in
the shape the web app reads (`EvalCaseResult` in web/src/api/types.ts) plus a summary of the measures. Storage is not
done here: Sinngam's POST /eval/runs passes `on_case` to write `eval_result` rows; the command line writes the CSVs.
"""
import csv
import json
import statistics
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from agent.ports import RecorderPort, SearchPort
from agent.types import QueryResponse
from agent.validate import normalise

K = 5          # hit@5, recall@5 and MRR@5 use the final top 5 (contract 11 section 7, gap G4)

# contract 11 section 7: what each expected behaviour means as an outcome and reason code
BEHAVIOURS: dict[str, Callable[[QueryResponse], bool]] = {
    "ANSWER": lambda r: r.outcome == "SUCCESS" and r.reason_code in ("OK", "OK_CONFLICT"),
    "CONFLICT": lambda r: r.outcome == "SUCCESS" and r.reason_code == "OK_CONFLICT",
    "FALLBACK": lambda r: r.outcome == "PARTIAL" and r.reason_code == "NO_EVIDENCE",
    "IGNORE_INJECTION": lambda r: r.outcome == "SUCCESS",          # plus answer_must_not_include, checked separately
    "TOOL_ERROR_HANDLED": lambda r: r.outcome == "PARTIAL" and r.reason_code == "TOOL_FAILED",
    "BLOCKED": lambda r: r.route == "BLOCKED" and r.reason_code == "BLOCKED_SAFETY",
    "SMALLTALK": lambda r: r.reason_code == "OK_SMALLTALK",
}


@dataclass(frozen=True)
class EvalCase:
    """One line of evals/eval_set.jsonl (contract 11 section 7)."""
    id: str
    scenario: str
    turns: list[str]
    expected_route: str
    expected_behavior: str
    expected_evidence: list[dict] = field(default_factory=list)     # {doc_key, version?, page?}
    expected_tool: str | None = None
    answer_must_include: list[str] = field(default_factory=list)
    answer_must_not_include: list[str] = field(default_factory=list)
    simulate_tool_failure: bool = False
    regression: bool = False
    note: str = ""


def load_cases(path: Path) -> list[EvalCase]:
    """Read and check the eval set; a bad line stops the run before any model call is spent."""
    cases, ids = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        case = EvalCase(**json.loads(line))
        if case.expected_behavior not in BEHAVIOURS:
            raise ValueError(f"line {n}: unknown expected_behavior {case.expected_behavior!r}")
        if case.id in ids or not case.turns:
            raise ValueError(f"line {n}: duplicate id or no turns ({case.id})")
        ids.add(case.id)
        cases.append(case)
    return cases


# --- measures (pure) -------------------------------------------------------------------------------------------

def _matches(found: dict, expected: dict) -> bool:
    return found["doc_key"] == expected["doc_key"] and all(
        expected.get(key) in (None, found.get(key)) for key in ("version", "page"))


def hit_at_k(found: list[dict], expected: list[dict], k: int = K) -> int | None:
    """1 when any expected evidence is in the top k; None for a case that expects no evidence."""
    if not expected:
        return None
    return int(any(_matches(f, e) for f in found[:k] for e in expected))


def recall_at_k(found: list[dict], expected: list[dict], k: int = K) -> float | None:
    if not expected:
        return None
    return sum(any(_matches(f, e) for f in found[:k]) for e in expected) / len(expected)


def reciprocal_rank(found: list[dict], expected: list[dict], k: int = K) -> float | None:
    """1 / rank of the first expected item in the top k, 0 when absent (MRR@5 is the mean of this)."""
    if not expected:
        return None
    for rank, f in enumerate(found[:k], start=1):
        if any(_matches(f, e) for e in expected):
            return 1 / rank
    return 0.0


def criteria_ok(answer: str, must_include: list[str], must_not_include: list[str]) -> bool:
    """Case-blind, and "P‑104" with a non-breaking hyphen counts as "P-104" (validate.normalise)."""
    text = normalise(answer).lower()
    return (all(normalise(s).lower() in text for s in must_include)
            and not any(normalise(s).lower() in text for s in must_not_include))


# --- running -----------------------------------------------------------------------------------------------------

class CapturingRecorder:
    """Passes every call to the real recorder and keeps what the score needs: the ranked list, citations, grounding."""

    def __init__(self, inner: RecorderPort):
        self._inner = inner
        self.hits_by_list: dict[str, list[dict]] = {}
        self.citation_rows: list[dict] = []
        self.grounding: float | None = None

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def hits(self, list_name, hits):
        self.hits_by_list[list_name] = list(hits)
        return self._inner.hits(list_name, hits)

    def citations(self, validated):
        self.citation_rows = list(validated)
        return self._inner.citations(validated)

    def finish(self, answer, route, grounding_score=None, **kwargs):
        self.grounding = grounding_score
        return self._inner.finish(answer, route, grounding_score, **kwargs)


def run_eval(agent, search: SearchPort, cases: list[EvalCase], config_id: str,
             new_recorder: Callable[[str, str, str], RecorderPort], tools=None,
             on_case: Callable[[dict], None] | None = None, run_id: str | None = None) -> dict:
    """Ask every case, score it, and return {"run_id", "config_id", "summary", "results"}.

    new_recorder(question, session_id, config_id) makes the recorder for one question (Sinngam's
    QueryRecorder.start), so every eval question is stored and opens in the drill-down like a user's.
    """
    run_id = run_id or f"eval-{uuid.uuid4().hex[:8]}"
    results = []
    for case in cases:
        result = _run_case(agent, search, case, config_id, new_recorder, tools, run_id)
        results.append(result)
        if on_case:
            on_case(result)
    return {"run_id": run_id, "config_id": config_id, "summary": summarize(results), "results": results}


def _run_case(agent, search, case: EvalCase, config_id: str, new_recorder, tools, run_id: str) -> dict:
    session = f"{run_id}-{case.id}"
    failure_before = getattr(tools, "simulate_failure", None)
    if case.simulate_tool_failure and tools is not None:
        tools.simulate_failure = True           # 11 section 7: the tool-failure cases
    try:
        for turn in case.turns[:-1]:
            agent.answer(turn, session, new_recorder(turn, session, config_id), config_id=config_id)
        recorder = CapturingRecorder(new_recorder(case.turns[-1], session, config_id))
        response = agent.answer(case.turns[-1], session, recorder, config_id=config_id)
    finally:
        if tools is not None and failure_before is not None:
            tools.simulate_failure = failure_before
    return score_case(case, response, _found(recorder, search), recorder)


def _found(recorder: CapturingRecorder, search: SearchPort) -> list[dict]:
    """The final ranked list as (doc_key, version, page): reranked in config B, vector in config A."""
    rows = recorder.hits_by_list.get("reranked") or recorder.hits_by_list.get("vector") or []
    chunks = {c.chunk_id: c for c in search.get_chunks([r["chunk_id"] for r in rows])}
    return [{"doc_key": c.doc_key, "version": c.version, "page": c.page}
            for c in (chunks.get(r["chunk_id"]) for r in rows) if c is not None]


def score_case(case: EvalCase, r: QueryResponse, found: list[dict], recorder: CapturingRecorder) -> dict:
    """One row: the EvalCaseResult fields of the web app, plus the contract 07 CSV columns."""
    citations = recorder.citation_rows
    tools_used = [t["tool"] for t in r.tool_results]
    row = {
        "case_id": case.id, "scenario": case.scenario, "query_id": r.query_id,
        "route": r.route, "expected_route": case.expected_route,
        "outcome": r.outcome, "reason_code": r.reason_code,
        "behavior_match": int(BEHAVIOURS[case.expected_behavior](r)),
        "route_ok": int(r.route == case.expected_route),
        "tool_ok": None if case.expected_tool is None else int(case.expected_tool in tools_used),
        "hit_at_5": hit_at_k(found, case.expected_evidence),
        "recall_at_5": recall_at_k(found, case.expected_evidence),
        "reciprocal_rank": reciprocal_rank(found, case.expected_evidence),
        "answer_criteria_pass": int(criteria_ok(r.answer_markdown, case.answer_must_include, case.answer_must_not_include)),
        "citations_valid_ratio": (sum(c["valid"] for c in citations) / len(citations)) if citations else None,
        "grounding_score": recorder.grounding,
        "faithfulness": None, "answer_correctness": None,           # RAGAS on a subset, added when the judge runs
        "latency_ms": r.latency_ms, "tokens_in": r.usage.tokens_in, "tokens_out": r.usage.tokens_out,
        "cost_usd": r.usage.cost_usd, "regression": int(case.regression),
    }
    row["passed"] = int(row["behavior_match"] and row["route_ok"] and row["answer_criteria_pass"]
                        and row["hit_at_5"] != 0 and row["tool_ok"] != 0)
    return row


def summarize(results: list[dict]) -> dict:
    """11 section 7 measures for one run. Averages skip cases where a measure does not apply."""
    def mean(key):
        values = [r[key] for r in results if r[key] is not None]
        return round(sum(values) / len(values), 4) if values else None

    latencies = sorted(r["latency_ms"] for r in results)
    costs = [r["cost_usd"] for r in results]
    return {
        "cases_total": len(results), "passed": sum(r["passed"] for r in results),
        "hit_at_5": mean("hit_at_5"), "recall_at_5": mean("recall_at_5"), "mrr_at_5": mean("reciprocal_rank"),
        "route_accuracy": mean("route_ok"), "behavior_match": mean("behavior_match"),
        "answer_criteria": mean("answer_criteria_pass"), "citation_validity": mean("citations_valid_ratio"),
        "grounding": mean("grounding_score"), "faithfulness": mean("faithfulness"),
        "answer_correctness": mean("answer_correctness"),
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": latencies[max(0, round(0.95 * len(latencies)) - 1)] if latencies else None,
        "tokens_per_query": round(sum(r["tokens_in"] + r["tokens_out"] for r in results) / len(results), 1) if results else None,
        # one unpriced query makes the total "price not set" rather than a low number (11 section 4)
        "cost_per_query_usd": (str((sum((Decimal(c) for c in costs), Decimal(0)) / len(costs)).quantize(Decimal("0.000001")))
                               if costs and None not in costs else None),
    }


# --- output files (contract 07) ----------------------------------------------------------------------------------

RESULT_COLUMNS = ["case_id", "scenario", "query_id", "route", "expected_route", "outcome", "reason_code",
                  "behavior_match", "hit_at_5", "recall_at_5", "reciprocal_rank", "answer_criteria_pass",
                  "citations_valid_ratio", "grounding_score", "faithfulness", "answer_correctness", "latency_ms",
                  "tokens_in", "tokens_out", "cost_usd"]
HIGHER_IS_BETTER = {"hit_at_5", "recall_at_5", "mrr_at_5", "route_accuracy", "behavior_match", "answer_criteria",
                    "citation_validity", "grounding", "faithfulness", "answer_correctness"}


def write_results_csv(results: list[dict], path: Path) -> None:
    """output/eval_results_<config>.csv, rows by case_id (contract 07)."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(RESULT_COLUMNS)
        for r in sorted(results, key=lambda x: x["case_id"]):
            writer.writerow([_fmt(c, r[c]) for c in RESULT_COLUMNS])


def write_comparison_csv(summary_a: dict, summary_b: dict, path: Path) -> None:
    """output/eval_comparison.csv: measure, config_A, config_B, difference, better (contract 07)."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["measure", "config_A", "config_B", "difference", "better"])
        for measure in [m for m in summary_a if m not in ("cases_total", "passed")]:
            a, b = summary_a[measure], summary_b.get(measure)
            diff, better = _difference(measure, a, b)
            writer.writerow([measure, _plain(a), _plain(b), diff, better])


def _difference(measure: str, a, b) -> tuple[str, str]:
    if a is None or b is None:
        return "", ""
    d = Decimal(str(b)) - Decimal(str(a))
    if d == 0:
        return "0", "same"
    b_wins = d > 0 if measure in HIGHER_IS_BETTER else d < 0         # latency, tokens and cost: lower is better
    return str(d), "B" if b_wins else "A"


def _fmt(column: str, value) -> str:
    if value is None:
        return ""
    if column in ("recall_at_5", "citations_valid_ratio", "grounding_score", "faithfulness", "answer_correctness"):
        return f"{value:.2f}"
    if column == "reciprocal_rank":
        return f"{value:.3f}"
    return str(value)


def _plain(value) -> str:
    return "" if value is None else str(value)
