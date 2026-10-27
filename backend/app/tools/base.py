"""What every approved tool is made of, and how its SQL runs (contract 13 sections 4 and 5).

The model never writes SQL: it picks a tool and fills arguments. Arguments are checked by the tool's
Pydantic model, then fixed SQL runs with bound parameters on a read-only connection, with a time
limit and a row cap. All arithmetic is in SQL; summary() writes the exact numbers in one sentence.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ArgsInvalid(Exception):
    """A value failed the check; the tool does not run. fields: [{field, problem}]."""

    def __init__(self, fields: list[dict[str, str]]) -> None:
        super().__init__("; ".join(f"{f['field']}: {f['problem']}" for f in fields))
        self.fields = fields


class ToolTimeout(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    version: int
    description: str                                  # the one sentence the router reads
    args: type[BaseModel]
    run: Callable[[sqlite3.Connection, Any], list[dict[str, Any]]]
    summary: Callable[[Any, list[dict[str, Any]]], str]
    approved_by: str
    approved_on: str
    test: str
    source: str = "business"
    max_rows: int = 20
    timeout_ms: int = 2000


def connect_readonly(path: Path) -> sqlite3.Connection:
    """The connection cannot write: a DELETE fails with "attempt to write a readonly database"."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
    conn.row_factory = sqlite3.Row
    return conn


def query(conn: sqlite3.Connection, sql: str, params: dict[str, Any], max_rows: int, timeout_ms: int) -> list[dict]:
    """Bound parameters only; a progress handler stops the query after timeout_ms."""
    deadline = time.perf_counter() + timeout_ms / 1000
    conn.set_progress_handler(lambda: int(time.perf_counter() > deadline), 1000)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchmany(max_rows)]
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise ToolTimeout(f"the query took longer than {timeout_ms} ms") from exc
        raise
    finally:
        conn.set_progress_handler(None, 0)


def require_exists(conn: sqlite3.Connection, table: str, column: str, value: str | None, field: str) -> None:
    """The "id must exist" check, before any tool SQL runs. table and column are constants in the tool files."""
    if value is not None and conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)).fetchone() is None:
        raise ArgsInvalid([{"field": field, "problem": f"{value} was not recognised"}])


def inr(paise: int) -> str:
    """Indian grouping: 43550000 paise is ₹4,35,500; negative amounts get a minus sign."""
    sign, paise = ("-" if paise < 0 else ""), abs(paise)
    rupees, rest = divmod(paise, 100)
    digits = str(rupees)
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    text = ",".join(([head] if head else []) + groups + [tail])
    return f"{sign}₹{text}" + (f".{rest:02d}" if rest else "")


def show_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows as returned to the agent and the screens: *_paise columns become exact rupee strings."""
    shown = []
    for row in rows:
        out = {}
        for key, value in row.items():
            if key.endswith("_paise") and isinstance(value, int):
                out[key[: -len("_paise")]] = inr(value)
            elif isinstance(value, Decimal):
                out[key] = str(value)
            else:
                out[key] = value
        shown.append(out)
    return shown


def argument_schema(model: type[BaseModel]) -> dict[str, dict[str, Any]]:
    """{field: {type, required, enum?, example?}}: what GET /tools shows and the planner reads."""
    schema = model.model_json_schema()
    required = set(schema.get("required", []))
    fields = {}
    for name, prop in schema.get("properties", {}).items():
        options = prop.get("anyOf", [prop])
        main = next((o for o in options if o.get("type") != "null"), prop)
        entry: dict[str, Any] = {"type": main.get("type", "string"), "required": name in required}
        if "enum" in main:
            entry["enum"] = main["enum"]
        if prop.get("examples"):
            entry["example"] = prop["examples"][0]
        fields[name] = entry
    return fields
