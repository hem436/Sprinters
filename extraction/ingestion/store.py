"""SQLite `knowledge.db`: tables document, page, chunk (contract 02, contract 10 section 9).

SQLite is the source of truth. Qdrant and BM25 can always be rebuilt from the `chunk` table.
One connection per call, so the worker thread and the API threads never share a connection.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ingestion.types import Chunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS document (
  document_id    TEXT PRIMARY KEY,
  doc_key        TEXT NOT NULL,
  title          TEXT NOT NULL,
  category       TEXT NOT NULL,
  version        TEXT NOT NULL,
  effective_date TEXT NOT NULL,
  file_name      TEXT NOT NULL,
  file_type      TEXT NOT NULL,
  size_bytes     INTEGER NOT NULL,
  content_hash   TEXT NOT NULL UNIQUE,
  status         TEXT NOT NULL CHECK (status IN
                   ('QUEUED','EXTRACTING','INDEXED','PARTIAL_REVIEW','FAILED','SUPERSEDED','DELETED')),
  page_count     INTEGER,
  chunk_count    INTEGER,
  ocr_cost_usd   TEXT,
  uploaded_by    TEXT,
  uploaded_at    TEXT,
  indexed_at     TEXT,
  stored_path    TEXT NOT NULL,          -- our copy of the file, for page images and re-index
  report_json    TEXT,                   -- the ExtractionReport (contract 10 section 8)
  error          TEXT                    -- why the job failed, for the admin page
);
CREATE INDEX IF NOT EXISTS ix_document_key ON document (doc_key);

CREATE TABLE IF NOT EXISTS page (
  document_id    TEXT NOT NULL REFERENCES document (document_id),
  page           INTEGER NOT NULL,
  printed_page   TEXT,
  section_label  TEXT,                   -- DOCX / TXT locator
  class          TEXT NOT NULL CHECK (class IN ('TEXT','TABLE_HEAVY','MIXED','SCANNED','GARBLED','BLANK')),
  method         TEXT NOT NULL,
  quality        REAL NOT NULL,
  flags          TEXT NOT NULL DEFAULT '[]',
  status         TEXT NOT NULL CHECK (status IN ('INDEXED','NEEDS_REVIEW','APPROVED','REJECTED','SKIPPED')),
  text           TEXT NOT NULL DEFAULT '',
  ocr_json       TEXT,                   -- model, tokens, latency, cost, prompt version
  reviewed_by    TEXT,
  reviewed_at    TEXT,
  review_comment TEXT,
  PRIMARY KEY (document_id, page)
);

CREATE TABLE IF NOT EXISTS chunk (
  chunk_id          TEXT PRIMARY KEY,
  document_id       TEXT NOT NULL REFERENCES document (document_id),
  doc_key           TEXT NOT NULL,
  title             TEXT NOT NULL,
  version           TEXT NOT NULL,
  effective_date    TEXT NOT NULL,
  category          TEXT NOT NULL,
  page              INTEGER,
  ordinal           INTEGER NOT NULL,
  section           TEXT NOT NULL DEFAULT '',
  block_types       TEXT NOT NULL DEFAULT '[]',
  method            TEXT NOT NULL,
  quality           REAL NOT NULL,
  searchable        INTEGER NOT NULL,
  current           INTEGER NOT NULL DEFAULT 1,     -- 0 when a newer version of the doc_key exists (contract 03)
  text              TEXT NOT NULL,
  index_text        TEXT NOT NULL,
  injection_suspect INTEGER NOT NULL DEFAULT 0,     -- rule S2 (contract 04)
  pii_found         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_chunk_document ON chunk (document_id);
CREATE INDEX IF NOT EXISTS ix_chunk_key_version ON chunk (doc_key, version);
CREATE INDEX IF NOT EXISTS ix_chunk_searchable ON chunk (searchable);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

CHUNK_COLUMNS = ("chunk_id", "document_id", "doc_key", "title", "version", "effective_date", "category", "page",
                 "ordinal", "section", "block_types", "method", "quality", "searchable", "current", "text",
                 "index_text", "injection_suspect", "pii_found")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class KnowledgeStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()          # one writer at a time; SQLite also locks, this avoids busy errors
        self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False) if self.db_path == ":memory:" else None
        with self.tx() as c:
            c.executescript(SCHEMA)
        from ingestion.fin_store import FIN_SCHEMA  # contract 14 tables live in the same file
        with self.tx() as c:
            c.executescript(FIN_SCHEMA)

    # ---- connections -------------------------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def tx(self):
        """A write transaction: commit on success, roll back on error."""
        with self._lock:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._memory_conn is None:
                    conn.close()

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self.tx() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    # ---- meta ----------------------------------------------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        rows = self.query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                      (key, value))

    # ---- documents -----------------------------------------------------------------------------------------------
    def insert_document(self, row: dict) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self.tx() as c:
            # a DELETED document with the same bytes is replaced (same id: the id comes from the hash)
            c.execute("DELETE FROM chunk WHERE document_id = ?", (row["document_id"],))
            c.execute("DELETE FROM page WHERE document_id = ?", (row["document_id"],))
            c.execute("DELETE FROM document WHERE document_id = ? AND status = 'DELETED'", (row["document_id"],))
            c.execute(f"INSERT INTO document ({cols}) VALUES ({marks})", list(row.values()))

    def get_document(self, document_id: str) -> dict | None:
        rows = self.query("SELECT * FROM document WHERE document_id = ?", (document_id,))
        return rows[0] if rows else None

    def find_by_hash(self, content_hash: str) -> dict | None:
        rows = self.query("SELECT * FROM document WHERE content_hash = ? AND status != 'DELETED'", (content_hash,))
        return rows[0] if rows else None

    def list_documents(self, category: str | None = None, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM document WHERE 1 = 1"
        params: list = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        if status:
            sql += " AND status = ?"
            params.append(status)
        return self.query(sql + " ORDER BY uploaded_at DESC, document_id", params)

    def update_document(self, document_id: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE document SET {sets} WHERE document_id = ?", [*fields.values(), document_id])

    def versions_of(self, doc_key: str) -> list[dict]:
        """All live versions of a document, newest effective date first."""
        return self.query("SELECT * FROM document WHERE doc_key = ? AND status IN "
                          "('INDEXED','PARTIAL_REVIEW','SUPERSEDED') ORDER BY effective_date DESC, uploaded_at DESC",
                          (doc_key,))

    # ---- pages ---------------------------------------------------------------------------------------------------
    def replace_pages_and_chunks(self, document_id: str, pages: list[dict], chunks: list[dict]) -> None:
        """Write one document's pages and chunks in one transaction (re-index deletes the old ones first)."""
        with self.tx() as c:
            c.execute("DELETE FROM chunk WHERE document_id = ?", (document_id,))
            c.execute("DELETE FROM page WHERE document_id = ?", (document_id,))
            for p in pages:
                cols = ", ".join(p)
                c.execute(f"INSERT INTO page ({cols}) VALUES ({', '.join('?' for _ in p)})", list(p.values()))
            for ch in chunks:
                values = [ch[k] for k in CHUNK_COLUMNS]
                c.execute(f"INSERT INTO chunk ({', '.join(CHUNK_COLUMNS)}) VALUES ({', '.join('?' for _ in values)})",
                          values)

    def get_pages(self, document_id: str) -> list[dict]:
        return [_page_out(r) for r in self.query("SELECT * FROM page WHERE document_id = ? ORDER BY page",
                                                 (document_id,))]

    def get_page(self, document_id: str, page: int) -> dict | None:
        rows = self.query("SELECT * FROM page WHERE document_id = ? AND page = ?", (document_id, page))
        return _page_out(rows[0]) if rows else None

    def update_page(self, document_id: str, page: int, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE page SET {sets} WHERE document_id = ? AND page = ?", [*fields.values(), document_id, page])

    # ---- chunks --------------------------------------------------------------------------------------------------
    def chunk_rows(self, document_id: str | None = None, page: int | None = None,
                   searchable_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM chunk WHERE 1 = 1"
        params: list = []
        if document_id:
            sql += " AND document_id = ?"
            params.append(document_id)
        if page is not None:
            sql += " AND page = ?"
            params.append(page)
        if searchable_only:
            sql += " AND searchable = 1"
        return [_chunk_out(r) for r in self.query(sql + " ORDER BY document_id, page, ordinal", params)]

    def index_rows(self) -> list[dict]:
        """What BM25 is built from: searchable chunks of live documents."""
        sql = ("SELECT c.chunk_id, c.index_text, c.category, c.doc_key, c.version, c.current, c.searchable "
               "FROM chunk c JOIN document d ON d.document_id = c.document_id "
               "WHERE c.searchable = 1 AND d.status IN ('INDEXED','PARTIAL_REVIEW','SUPERSEDED') "
               "ORDER BY c.chunk_id")
        return [_chunk_out(r) for r in self.query(sql)]

    def chunks_by_ids(self, chunk_ids: list[str]) -> list[dict]:
        if not chunk_ids:
            return []
        marks = ", ".join("?" for _ in chunk_ids)
        return [_chunk_out(r) for r in self.query(f"SELECT * FROM chunk WHERE chunk_id IN ({marks})", chunk_ids)]

    def section_chunks(self, doc_key: str, section: str) -> list[dict]:
        """Rule C1 (contract 04): the same section in every live version; only searchable chunks."""
        sql = ("SELECT c.* FROM chunk c JOIN document d ON d.document_id = c.document_id "
               "WHERE c.doc_key = ? AND c.section = ? AND c.searchable = 1 "
               "AND d.status IN ('INDEXED','PARTIAL_REVIEW','SUPERSEDED') "
               "ORDER BY c.effective_date DESC, c.page, c.ordinal")
        return [_chunk_out(r) for r in self.query(sql, (doc_key, section))]

    def set_chunks_searchable(self, document_id: str, page: int, searchable: bool) -> list[str]:
        with self.tx() as c:
            c.execute("UPDATE chunk SET searchable = ? WHERE document_id = ? AND page = ?",
                      (int(searchable), document_id, page))
            return [r[0] for r in c.execute("SELECT chunk_id FROM chunk WHERE document_id = ? AND page = ?",
                                            (document_id, page))]

    def set_chunks_current(self, document_id: str, current: bool) -> None:
        with self.tx() as c:
            c.execute("UPDATE chunk SET current = ? WHERE document_id = ?", (int(current), document_id))

    def delete_chunks(self, document_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM chunk WHERE document_id = ?", (document_id,))


def _page_out(row: dict) -> dict:
    row = dict(row)
    row["flags"] = json.loads(row.get("flags") or "[]")
    row["ocr"] = json.loads(row.pop("ocr_json")) if row.get("ocr_json") else None
    return row


def _chunk_out(row: dict) -> dict:
    row = dict(row)
    if "block_types" in row:
        row["block_types"] = json.loads(row["block_types"] or "[]")
    for key in ("searchable", "current", "injection_suspect", "pii_found"):
        if key in row:
            row[key] = bool(row[key])
    return row


def to_chunk(row: dict) -> Chunk:
    """The record the agent reads (Arka's agent.types.Chunk has the same fields)."""
    return Chunk(chunk_id=row["chunk_id"], document_id=row["document_id"], doc_key=row["doc_key"], title=row["title"],
                 version=row["version"], effective_date=row["effective_date"], page=row["page"],
                 section=row["section"], method=row["method"], text=row["text"],
                 injection_suspect=bool(row["injection_suspect"]))
