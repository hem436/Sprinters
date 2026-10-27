"""The SQL each tool ran, kept for the drill-down (interpretability): registry, store and the query detail."""

import sqlite3
import sys
from pathlib import Path

from app.observability import store
from app.tools.registry import ToolRegistry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_business_data  # noqa: E402

P104 = {"project_id": "P-104", "fiscal_year": "FY2026-27", "category": "TRAVEL"}


def test_result_carries_the_sql_that_ran(tmp_path):
    db = tmp_path / "business.db"
    make_business_data.build(db)
    result = ToolRegistry(db).run_tool("budget_status", P104)
    assert result.status == "OK" and len(result.sql) == 1
    ran = result.sql[0]
    assert ran["sql"].startswith("SELECT project_id, category, budget_paise") and "FROM v_budget_status" in ran["sql"]
    assert ran["params"]["project_id"] == "P-104" and "\n" not in ran["sql"]


def test_no_sql_when_the_arguments_fail(tmp_path):
    db = tmp_path / "business.db"
    make_business_data.build(db)
    result = ToolRegistry(db).run_tool("budget_status", {"project_id": "104"})
    assert result.status == "ARGS_INVALID" and result.sql == []


def test_an_older_store_gets_the_sql_column(tmp_path):
    db = tmp_path / "observability.db"
    store.init_db(db)
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE tool_call DROP COLUMN sql_text")        # a store made before the column existed
    con.close()
    store.init_db(db)
    con = sqlite3.connect(db)
    assert "sql_text" in {r[1] for r in con.execute("PRAGMA table_info(tool_call)")}
    con.close()
