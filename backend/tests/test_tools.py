"""WP-BE2: business data and the six approved tools (contract 13 section 8), and the /tools routes.

test_route_both_for_policy_and_project is the router's (Arka's): model/tests/test_router.py.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tools import base
from app.tools.registry import ToolRegistry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_business_data  # noqa: E402

ADMIN = ("admin", "s3cret")
P104_TRAVEL = {"project_id": "P-104", "fiscal_year": "FY2026-27", "category": "TRAVEL"}


@pytest.fixture
def business_db(config) -> Path:
    path = config.paths.resolve(config.paths.business_db)
    make_business_data.build(path)
    return path


@pytest.fixture
def tools(business_db) -> ToolRegistry:
    return ToolRegistry(business_db)


# Contract 13 section 8 -------------------------------------------------------

def test_budget_status_p104(tools, business_db):
    result = tools.run_tool("budget_status", P104_TRAVEL)
    assert result.status == "OK"
    conn = sqlite3.connect(business_db)
    budget, spent = conn.execute(
        "SELECT budget_paise, spent_paise FROM v_budget_status "
        "WHERE project_id = 'P-104' AND fiscal_year = 'FY2026-27' AND category = 'TRAVEL'").fetchone()
    assert (budget, spent) == (40000000, 43550000)
    assert result.rows[0]["pct_used"] == 108.9
    assert result.summary == ("P-104 TRAVEL FY2026-27: budget ₹4,00,000, spent ₹4,35,500, "
                              "over by ₹35,500 (108.9 % used).")


def test_spend_counts_approved_and_paid_only(business_db):
    conn = sqlite3.connect(business_db)
    statuses = {s for (s,) in conn.execute("SELECT DISTINCT status FROM v_spend")}
    assert statuses == {"APPROVED", "PAID"}
    pending = conn.execute("SELECT COUNT(*) FROM expense_claim WHERE status IN ('SUBMITTED', 'REJECTED')").fetchone()
    assert pending[0] > 0


def test_readonly_connection(business_db):
    conn = base.connect_readonly(business_db)
    with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
        conn.execute("DELETE FROM expense_claim")


def test_unknown_project_args_invalid(tools, monkeypatch):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("the tool SQL ran")

    monkeypatch.setattr("app.tools.budget_status.query", must_not_run)
    result = tools.run_tool("budget_status", {"project_id": "P-999", "fiscal_year": "FY2026-27"})
    assert result.status == "ARGS_INVALID" and "P-999" in result.message


def test_group_by_not_injectable(tools):
    result = tools.run_tool("spend_summary", {"group_by": "city; DROP TABLE x"})
    assert result.status == "ARGS_INVALID"
    assert tools.run_tool("spend_summary", {"group_by": "city"}).status == "OK"   # the table is still there


def test_empty_result_is_success(tools):
    result = tools.run_tool("claims_list", {"project_id": "P-104", "min_amount": 10_000_000})
    assert result.status == "EMPTY" and result.rows == [] and result.summary


def test_timeout_controlled(business_db):
    slow = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT COUNT(*) FROM n"
    conn = base.connect_readonly(business_db)
    with pytest.raises(base.ToolTimeout):
        base.query(conn, slow, {}, max_rows=20, timeout_ms=50)


def test_timeout_is_a_tool_status(tools, monkeypatch):
    def slow(*_args, **_kwargs):
        raise base.ToolTimeout("the query took longer than 2000 ms")

    monkeypatch.setattr("app.tools.headcount.query", slow)
    assert tools.run_tool("headcount", {}).status == "TIMEOUT"


def test_headcount_never_lists_people(tools):
    result = tools.run_tool("headcount", {"location": "Mumbai"})
    assert result.status == "OK"
    assert [set(r) for r in result.rows] == [{"headcount"}]
    assert "E1" not in result.summary


# The other tools and the registry ---------------------------------------------

def test_project_info_p104(tools):
    result = tools.run_tool("project_info", {"project_id": "P-104"})
    assert result.status == "OK" and "Operations" in result.summary


def test_claims_list_pending_p104(tools):
    result = tools.run_tool("claims_list", {"project_id": "P-104", "status": "SUBMITTED", "category": "TRAVEL",
                                            "order": "largest"})
    assert [r["amount"] for r in result.rows] == ["₹27,500", "₹18,000"]


def test_asset_compliance_finance_laptops(tools):
    result = tools.run_tool("asset_compliance", {"dept_id": "D-FIN", "asset_type": "LAPTOP"})
    assert result.rows[0]["not_encrypted"] == 3 and "3 not encrypted" in result.summary


def test_unknown_tool_and_simulated_failure(business_db):
    assert ToolRegistry(business_db).run_tool("drop_tables", {}).status == "NO_TOOL"
    failing = ToolRegistry(business_db, simulate_failure=True)
    assert failing.run_tool("budget_status", P104_TRAVEL).status == "TIMEOUT"


def test_planner_sees_names_descriptions_and_args_only(tools):
    catalogue = tools.list_tools()
    assert [t["name"] for t in catalogue] == ["project_info", "budget_status", "spend_summary", "claims_list",
                                              "asset_compliance", "headcount"]
    assert all(set(t) == {"name", "description", "args"} for t in catalogue)
    assert catalogue[2]["args"]["group_by"]["enum"] == ["project", "department", "category", "city"]


def test_inr_indian_grouping():
    assert [base.inr(p) for p in (43550000, -3550000, 1000000000, 150025)] == [
        "₹4,35,500", "-₹35,500", "₹1,00,00,000", "₹1,500.25"]


def test_make_business_data_is_repeatable(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    make_business_data.build(a)
    make_business_data.build(b)
    dump = lambda p: list(sqlite3.connect(p).iterdump())  # noqa: E731
    assert dump(a) == dump(b)


def test_agent_uses_the_real_tools(tools):
    """Arka's Agent with these tools (his stubs for search and the model): the budget numbers reach the answer."""
    from agent.service import Agent
    from agent.stubs import FakeLLM, NullRecorder, StubSearch

    llm = FakeLLM({
        "route": [{"route": "SQL", "standalone_query": "Is P-104 over its travel budget?", "tool": "budget_status",
                   "tool_args": P104_TRAVEL}],
        "answer": [{"answer_markdown": "Yes, P-104 spent ₹4,35,500 against ₹4,00,000 [T1].",
                    "claims": [{"text": "P-104 spent ₹4,35,500 against a travel budget of ₹4,00,000.",
                                "citations": ["T1"]}]}],
    })
    agent = Agent(StubSearch({}), tools, llm, reranker=None)
    response = agent.answer("Is P-104 over its travel budget?", "s1", NullRecorder())
    assert (response.route, response.outcome) == ("SQL", "SUCCESS")
    assert response.tool_results[0]["status"] == "OK" and "₹4,35,500" in response.tool_results[0]["summary"]
    assert "budget_status" in llm.calls[0][1]          # the planner saw the real tool list


# Routes ---------------------------------------------------------------------

@pytest.fixture
def api(config, business_db) -> TestClient:
    return TestClient(create_app(config), raise_server_exceptions=False)


def test_get_tools_matches_the_web_app(api):
    tools = api.get("/tools", auth=ADMIN).json()
    assert len(tools) == 6
    assert set(tools[0]) >= {"name", "version", "source", "description", "argument_schema", "approved",
                             "success_rate"}
    assert tools[1]["argument_schema"]["project_id"] == {"type": "string", "required": True, "example": "P-104"}


def test_try_tool_ok(api):
    body = api.post("/tools/budget_status/try", json={"args": P104_TRAVEL}, auth=ADMIN).json()
    assert body["rows"][0]["spent"] == "₹4,35,500"
    assert body["provenance"]["tool"] == "budget_status" and body["provenance"]["row_count"] == 1


def test_try_tool_errors(api):
    assert api.post("/tools/nope/try", json={"args": {}}, auth=ADMIN).status_code == 404
    resp = api.post("/tools/budget_status/try", json={"args": {"project_id": "P-999", "fiscal_year": "FY2026-27"}},
                    auth=ADMIN)
    assert resp.status_code == 422
    assert resp.json()["error"] == {"code": "ARGS_INVALID",
                                    "message": "The arguments failed the check. The tool did not run.",
                                    "fields": [{"field": "project_id", "problem": "P-999 was not recognised"}]}


def test_tools_need_admin(api):
    assert api.get("/tools").status_code == 401
