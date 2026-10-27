"""Issue #48: the stream events of contract 05, the `current` and `rows` fields, and SYSTEM_ERROR (11 section 5)."""
import dataclasses

from agent.service import SYSTEM_ERROR_TEXT, Agent
from agent.stubs import FakeLLM, NullRecorder, StubSearch, StubTools
from agent.types import Hit

from tests.test_answer_checks import P104

LAPTOP = {"answer_markdown": "Laptops must be encrypted [E1].",
          "claims": [{"text": "Every laptop must be encrypted.", "citations": ["E1"]}]}


def _agent(corpus, table_reranker, llm, search=None, tools=None):
    search = search or StubSearch(corpus, bm25=[Hit("c_sop_laptop", 9.0, 1)])
    return Agent(search, tools or StubTools(), llm, table_reranker({"POL-HR-014": 0.9}))


def test_stream_event_order_and_stage_names(corpus, table_reranker):
    llm = FakeLLM({"route": [{"route": "DOCS", "standalone_query": "Laptop rule?"}], "answer": [LAPTOP]})
    events = list(_agent(corpus, table_reranker, llm).answer_stream("Laptop rule?", "s1", NullRecorder()))
    names = [e for e, _ in events]
    stages = [d["stage"] for e, d in events if e == "status"]
    assert stages == ["guard", "context", "route", "retrieve_vector", "retrieve_bm25", "fuse", "rerank", "answer", "validate"]
    assert names[len(stages):len(stages) + 1] == ["citations"] and names[-1] == "done"
    tokens = "".join(d["text"] for e, d in events if e == "token")
    assert tokens == "Laptops must be encrypted [E1]." == events[-1][1]["answer_markdown"]
    assert all(d["label"] for e, d in events if e == "status")


def test_answer_and_stream_give_the_same_response(corpus, table_reranker):
    replies = {"route": [{"route": "DOCS", "standalone_query": "q"}], "answer": [LAPTOP]}
    one = _agent(corpus, table_reranker, FakeLLM(replies)).answer("Laptop rule?", "s1", NullRecorder())
    done = list(_agent(corpus, table_reranker, FakeLLM(replies)).answer_stream("Laptop rule?", "s1", NullRecorder()))[-1][1]
    for field in ("answer_markdown", "outcome", "reason_code", "confidence", "route", "citations"):
        assert getattr(one, field) == done[field] or [c.model_dump() for c in one.citations] == done[field]


class BrokenSearch(StubSearch):
    def bm25_search(self, query, k, filters=None):
        raise ConnectionError("qdrant is down")


def test_a_failing_part_is_answered_and_recorded(corpus, table_reranker):
    llm = FakeLLM({"route": [{"route": "DOCS", "standalone_query": "q"}]})
    recorder = NullRecorder()
    agent = _agent(corpus, table_reranker, llm, search=BrokenSearch(corpus))
    events = list(agent.answer_stream("Laptop rule?", "s1", recorder))
    assert [e for e, _ in events][-2:] == ["error", "done"]
    done = events[-1][1]
    assert (done["outcome"], done["reason_code"], done["answer_markdown"]) == ("FAILED", "SYSTEM_ERROR", SYSTEM_ERROR_TEXT)
    assert recorder.finished["error_category"] == "ConnectionError" and recorder.finished["facts"].system_error


def test_current_flag_and_tool_rows(corpus, table_reranker):
    current_chunk = dataclasses.replace(corpus["c_v2_overrun"], current=True)
    search = StubSearch({**corpus, "c_v2_overrun": current_chunk}, vector=[Hit("c_v2_overrun", 0.8, 1)])
    rows = [{"project_id": "P-104", "budget_paise": 40000000, "spent_paise": 43550000}]
    tools = StubTools(results={"budget_status": dataclasses.replace(P104, rows=rows)})
    answer = {"answer_markdown": "Over [T1]; head approves [E1].",
              "claims": [{"text": "P-104 spent ₹4,35,500 against ₹4,00,000.", "citations": ["T1"]},
                         {"text": "Spend above the approved project budget needs department head approval.", "citations": ["E1"]}]}
    llm = FakeLLM({"route": [{"route": "BOTH", "standalone_query": "q", "tool": "budget_status", "tool_args": {}}],
                   "answer": [answer]})
    agent = Agent(search, tools, llm, table_reranker({"Spend above": 0.9}))
    r = agent.answer("Is P-104 over budget and what does the policy require?", "s1", NullRecorder())
    assert r.citations[1].current is True
    assert r.tool_results[0]["rows"] == rows and r.citations[0].row_count == 1
