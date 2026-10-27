"""Our agent against Sinngam's real QueryRecorder (backend/), so the two parts cannot drift apart unnoticed.

Runs when backend/ sits next to model/ (on main after a merge); skipped on a branch without it.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if not (BACKEND / "app" / "observability" / "recorder.py").exists():
    pytest.skip("backend/ is not in this checkout", allow_module_level=True)
# appended, not inserted: our own `tests` package must win over backend/tests (review #25)
sys.path.append(str(BACKEND))
try:
    from app.observability import store                    # noqa: E402
    from app.observability.recorder import QueryRecorder   # noqa: E402
except ImportError as missing:                             # backend/ is here but its requirements are not installed
    pytest.skip(f"backend requirements not installed ({missing.name})", allow_module_level=True)

from agent.answer import ANSWER_PROMPT_VERSION          # noqa: E402
from agent.service import Agent                        # noqa: E402
from agent.stubs import FakeLLM, StubSearch, StubTools  # noqa: E402
from agent.types import Hit                             # noqa: E402
from tests.test_answer_checks import P104               # noqa: E402

BOTH = {"route": "BOTH", "standalone_query": "q", "tool": "budget_status", "tool_args": {"project_id": "P-104"}}
ANSWER = {"answer_markdown": "Yes [T1]; the department head approves [E1].",
          "claims": [{"text": "P-104 spent ₹4,35,500 against a travel budget of ₹4,00,000.", "citations": ["T1"]},
                     {"text": "Spend above the approved project budget needs department head approval.", "citations": ["E1"]}]}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "observability.db"
    store.init_db(path)
    store.seed_prices(path, store.load_price_file())
    return path


def _run(db, corpus, table_reranker, question, replies):
    agent = Agent(StubSearch(corpus, vector=[Hit("c_v2_overrun", 0.8, 1)]),
                  StubTools(results={"budget_status": P104}), FakeLLM(replies), table_reranker({"Spend above": 0.9}))
    recorder = QueryRecorder.start(question, "s1", "B", db_path=db)
    response = agent.answer(question, "s1", recorder)
    con = sqlite3.connect(db)
    stored = con.execute("SELECT outcome, reason_code, citations_valid FROM query_event WHERE query_id = ?",
                         (recorder.query_id,)).fetchone()
    calls = con.execute("SELECT purpose, prompt_version FROM llm_call WHERE query_id = ?", (recorder.query_id,)).fetchall()
    tools = con.execute("SELECT tool, status, result_summary FROM tool_call WHERE query_id = ?", (recorder.query_id,)).fetchall()
    return response, stored, calls, tools


def test_every_query_is_stored_with_its_calls(db, corpus, table_reranker):
    response, stored, calls, tools = _run(db, corpus, table_reranker, "Is P-104 over budget and who approves under the policy?",
                                          {"route": [BOTH], "answer": [ANSWER]})
    assert stored == (response.outcome, response.reason_code, 2)
    assert calls == [("route", "route-v1"), ("answer", ANSWER_PROMPT_VERSION)]
    assert tools[0][:2] == ("budget_status", "OK") and "4,35,500" in tools[0][2]


def test_repair_is_stored_as_an_answer_call(db, corpus, table_reranker):
    _, stored, calls, _ = _run(db, corpus, table_reranker, "Is P-104 over budget and who approves under the policy?",
                               {"route": [BOTH], "answer": ["not json"], "repair": [ANSWER]})
    assert stored is not None
    assert [c[1] for c in calls] == ["route-v1", ANSWER_PROMPT_VERSION, f"{ANSWER_PROMPT_VERSION}-repair"]


def test_stored_outcome_equals_the_users_outcome_for_small_talk(db, corpus, table_reranker):
    """One copy of the outcome rules (CHANGES DC-1): finish() stores the agent's own outcome."""
    response, stored, _, _ = _run(db, corpus, table_reranker, "Hello!", {})
    assert stored[:2] == (response.outcome, response.reason_code)
