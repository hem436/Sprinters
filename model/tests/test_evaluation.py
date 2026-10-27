"""WP-AG6: the eval set file, the measures, the runner and the output files (contracts 07, 11 section 7)."""
import csv
import dataclasses
from collections import Counter
from pathlib import Path

from agent.answer import NO_EVIDENCE_TEXT
from agent.evaluation import (RESULT_COLUMNS, EvalCase, criteria_ok, hit_at_k, load_cases, recall_at_k,
                              reciprocal_rank, run_eval, write_comparison_csv, write_results_csv)
from agent.service import Agent
from agent.stubs import FakeLLM, NullRecorder, StubSearch, StubTools
from agent.types import Hit

from tests.test_answer_checks import P104

EVAL_SET = Path(__file__).resolve().parents[2] / "evals" / "eval_set.jsonl"
WEB_FIELDS = {"case_id", "scenario", "query_id", "route", "expected_route", "outcome", "reason_code",
              "behavior_match", "hit_at_5", "grounding_score", "latency_ms", "cost_usd"}     # web EvalCaseResult


def test_eval_set_file_is_valid():
    cases = load_cases(EVAL_SET)
    per_scenario = Counter(c.scenario for c in cases)
    assert len(cases) == 29
    assert all(n >= 2 for s, n in per_scenario.items() if s != "small_talk")
    assert {c.id for c in cases if c.regression} == {"D01", "X01", "S01"}
    for c in cases:
        if c.expected_behavior == "FALLBACK":
            assert all(s.lower() in NO_EVIDENCE_TEXT.lower() for s in c.answer_must_include), c.id


def test_measures():
    found = [{"doc_key": "a", "version": "1", "page": 2}, {"doc_key": "b", "version": "1", "page": 7}]
    expected = [{"doc_key": "b", "page": 7}, {"doc_key": "c"}]
    assert hit_at_k(found, expected) == 1 and recall_at_k(found, expected) == 0.5
    assert reciprocal_rank(found, expected) == 0.5
    assert hit_at_k(found, []) is None and reciprocal_rank(found, [{"doc_key": "z"}]) == 0.0
    assert hit_at_k(found * 3, [{"doc_key": "b"}], k=1) == 0        # only the top k counts
    assert criteria_ok("Over by ₹35,500 [T1].", ["35,500"], ["APPROVED"])
    assert not criteria_ok("APPROVED", [], ["APPROVED"])


def test_run_eval_end_to_end(corpus, table_reranker):
    cases = [
        EvalCase("X01", "exact_id", ["What does POL-HR-014 say about laptops?"], "DOCS", "ANSWER",
                 [{"doc_key": "it-sop", "page": 3}], answer_must_include=["30 days"]),
        EvalCase("S01", "structured_data", ["Is P-104 over its travel budget?"], "SQL", "ANSWER",
                 expected_tool="budget_status", answer_must_include=["4,35,500"]),
        EvalCase("T01", "tool_failure", ["Is P-104 over its travel budget?"], "SQL", "TOOL_ERROR_HANDLED",
                 expected_tool="budget_status", simulate_tool_failure=True),
        EvalCase("N01", "insufficient_evidence", ["What is the CEO's salary?"], "DOCS", "FALLBACK",
                 answer_must_include=["could not find"]),
    ]
    sql = {"route": "SQL", "standalone_query": "q", "tool": "budget_status", "tool_args": {"project_id": "P-104"}}
    llm = FakeLLM({
        "route": [{"route": "DOCS", "standalone_query": "POL-HR-014 laptops"}, sql, sql,
                  {"route": "DOCS", "standalone_query": "CEO salary"}],
        "answer": [{"answer_markdown": "Encrypted and patched within 30 days [E1].",
                    "claims": [{"text": "Every laptop must be encrypted and patched within 30 days.", "citations": ["E1"]}]},
                   {"answer_markdown": "Yes, ₹4,35,500 against ₹4,00,000 [T1].",
                    "claims": [{"text": "P-104 spent ₹4,35,500 against a budget of ₹4,00,000.", "citations": ["T1"]}]}],
    })

    class Search(StubSearch):
        def vector_search(self, query, k, filters=None):
            return [Hit("c_sop_laptop", 0.8, 1)] if "POL" in query else [Hit("c_v2_perdiem", 0.1, 1)]

    search, tools = Search(corpus), StubTools(results={"budget_status": P104})
    agent = Agent(search, tools, llm, table_reranker({"POL-HR-014": 0.9}))
    stored = []
    run = run_eval(agent, search, cases, "B", lambda q, s, c: NullRecorder(cost_usd="0.000400"),
                   on_case=stored.append)

    by_id = {r["case_id"]: r for r in run["results"]}
    assert [r["passed"] for r in run["results"]] == [1, 1, 1, 1], run["results"]
    assert by_id["X01"]["hit_at_5"] == 1 and by_id["X01"]["reciprocal_rank"] == 1.0
    assert by_id["S01"]["hit_at_5"] is None and by_id["S01"]["tool_ok"] == 1
    assert by_id["T01"]["reason_code"] == "TOOL_FAILED"
    assert agent.tools is tools and tools.run_tool("budget_status", {}).status == "OK"   # users' tools untouched
    assert by_id["N01"]["reason_code"] == "NO_EVIDENCE"
    assert WEB_FIELDS <= set(by_id["X01"]) and len(stored) == 4
    s = run["summary"]
    assert (s["cases_total"], s["passed"], s["hit_at_5"], s["mrr_at_5"]) == (4, 4, 1.0, 1.0)
    assert s["cost_per_query_usd"] == "0.000400"


def test_output_files(tmp_path):
    row = {c: None for c in RESULT_COLUMNS} | {"case_id": "X01", "reciprocal_rank": 0.5, "recall_at_5": 1.0,
                                               "latency_ms": 900}
    write_results_csv([row], tmp_path / "eval_results_B.csv")
    lines = list(csv.reader((tmp_path / "eval_results_B.csv").open(encoding="utf-8")))
    assert lines[0] == RESULT_COLUMNS and lines[1][RESULT_COLUMNS.index("reciprocal_rank")] == "0.500"

    a = {"cases_total": 2, "passed": 1, "hit_at_5": 0.5, "latency_p50_ms": 900, "cost_per_query_usd": None}
    b = {"cases_total": 2, "passed": 2, "hit_at_5": 1.0, "latency_p50_ms": 1200, "cost_per_query_usd": None}
    write_comparison_csv(a, b, tmp_path / "eval_comparison.csv")
    rows = {r[0]: r for r in csv.reader((tmp_path / "eval_comparison.csv").open(encoding="utf-8"))}
    assert rows["hit_at_5"][3:] == ["0.5", "B"]
    assert rows["latency_p50_ms"][3:] == ["300", "A"]            # slower is worse
    assert rows["cost_per_query_usd"][3:] == ["", ""]
