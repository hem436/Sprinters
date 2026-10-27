<!-- Contract 02. Owners: Myank (P1) documents and financial tables, Sinngam (P3) business data and events. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 02 Data model

Version: 1.0 · Status: DRAFT · Owners: Myank (P1) knowledge and financial tables, Sinngam (P3) business and event tables · Case section(s): 4.1, 6, 12

Three stores, each with one owner:

| Store | Holds | Owner |
|---|---|---|
| SQLite `knowledge.db` + Qdrant collection | documents, pages, chunks (text + vectors); BM25 is rebuilt from `chunk` | P1 |
| SQLite `business.db` | the synthetic business data the SQL tools read (read-only connection) | P2 |
| SQLite `observability.db` | query events, eval runs (contract 11 section 2) | P3 |

Separate files so the SQL tools can open `business.db` read-only and can never touch documents or logs.

## ER diagram (knowledge and business)

```mermaid
erDiagram
  DOCUMENT ||--o{ PAGE : has
  PAGE ||--o{ CHUNK : split_into
  DOCUMENT }o--|| DOC_KEY : "version of"
  DEPARTMENT ||--o{ PROJECT : owns
  DEPARTMENT ||--o{ EMPLOYEE : employs
  DEPARTMENT ||--o{ IT_ASSET : holds
  PROJECT ||--o{ BUDGET : has
  PROJECT ||--o{ EXPENSE_CLAIM : charged_to
  EMPLOYEE ||--o{ EXPENSE_CLAIM : submits
```

## Knowledge tables (P1)

### document

| Column | Type | Null | Notes |
|---|---|---|---|
| document_id | TEXT PK | no | `doc_` + 8 hex of the content hash |
| doc_key | TEXT | no | stable name across versions, for conflict rules (C1) |
| title, category | TEXT | no | from the upload form |
| version | TEXT | no | "1.0", "2.0" |
| effective_date | TEXT (ISO date) | no | for "current version" filter |
| file_name, file_type, size_bytes | | no | |
| content_hash | TEXT UNIQUE | no | duplicate check (X1) |
| status | TEXT CHECK in (QUEUED, EXTRACTING, INDEXED, PARTIAL_REVIEW, FAILED, SUPERSEDED, DELETED) | no | contract 03 |
| page_count, chunk_count | INTEGER | yes | |
| ocr_cost_usd | TEXT (Decimal) | yes | from the ExtractionReport |
| uploaded_by, uploaded_at, indexed_at | | | |

### page

| Column | Type | Null | Notes |
|---|---|---|---|
| document_id, page | TEXT, INTEGER | no | PK together; for DOCX and TXT `page` is the section ordinal |
| printed_page | TEXT | yes | the number printed on the page, if found |
| class | TEXT CHECK in (TEXT, TABLE_HEAVY, MIXED, SCANNED, GARBLED, BLANK) | no | X3 |
| method | TEXT | no | text, text+tables, text_pypdf, ocr, text+ocr, ocr_tesseract |
| quality | REAL | no | X6 |
| flags | TEXT (JSON) | no | HANDWRITTEN, HAS_TABLE, NUMBER_SUSPECT, OCR_FAILED... |
| status | TEXT CHECK in (INDEXED, NEEDS_REVIEW, APPROVED, REJECTED, SKIPPED) | no | X7 |
| text | TEXT | no | full extracted page text, for the preview page |
| reviewed_by, reviewed_at | | yes | |

### report, fin_table, fin_fact, metric_map

Numbers from financial tables, one row per value, with unit, scale, basis, period and page. Full definition, view `v_fact_current` and checks in **contract 14**.

### chunk

Columns exactly as the chunk record in contract 10 section 9, plus `injection_suspect` (bool, rule S2) and
`pii_found` (bool). Index on `(document_id)`, `(doc_key, version)`, `(searchable)`.

The Qdrant point id is `uuid5(chunk_id)`; its payload copies the chunk record without `text` duplication beyond
`index_text`. SQLite is the source of truth; Qdrant and BM25 can always be rebuilt from it.

## Business tables (P2, `business.db`)

The full schema, the two views that hold the business meaning (`v_spend`, `v_budget_status`), the approved tools and how a source is connected are in **contract 13**. Tables: `department`, `employee`, `project`, `budget`, `expense_claim`, `it_asset`. Money there is INTEGER paise (exact sums in SQLite), shown as `Decimal` rupees. No personal data: people are codes such as `E1042`.

## Input files to tables

| Input | Loads into | Idempotency key | Validation |
|---|---|---|---|
| uploaded file | document, page, chunk, Qdrant | `content_hash`; `chunk_id` | contract 10 X1 |
| `scripts/make_business_data.py` | business tables | drop and recreate (seeded) | foreign keys on |
| `evals/eval_set.jsonl` | eval_result rows per run | `(run_id, case_id)` | schema check before a run |
