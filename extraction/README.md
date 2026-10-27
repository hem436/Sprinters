# extraction/: P1 extraction and indexing (Myank)

Files in, cited evidence out. Built to contracts 10 (extraction pipeline), 14 (financial tables) and 03 (lifecycle).
Branch `data_injection_pipeline`.

## Run the tests

```bash
cd extraction
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q          # no network, no keys: OCR and embeddings are fakes, Qdrant runs in memory
.venv/bin/python -m pytest -m live     # 2 tests against the real Gemini models (needs GEMINI_API_KEY in .env)
```

The test PDFs, Word files and photos are built in code (`tests/files.py`), so there are no binary fixtures.

## Ingest files by hand

```bash
cp .env.example .env                   # add GEMINI_API_KEY; leave QDRANT_URL empty for local Qdrant on disk
.venv/bin/python -m ingestion ingest policy.pdf --title "Travel and Expense Policy" --category "HR policy" \
    --version 2.0 --effective-date 2026-04-01
.venv/bin/python -m ingestion list
.venv/bin/python -m ingestion report doc_7f3a1c2d
.venv/bin/python -m ingestion search "POL-HR-014" --bm25
```

## Where each rule lives

| File | Rules (contract 10 unless named) |
|---|---|
| `ingestion/validate.py` | X1: type by extension and first bytes, size, opens, encrypted, metadata, page and OCR-page limits |
| `ingestion/loaders/pdf.py` | X2 per-page split, X3 routing, X4 text and tables, X5 OCR only for the pages that need it |
| `ingestion/classify.py` | X3 signals (`chars`, `cid_ratio`, `image_cover`, `tables`, `num_ratio`) and the 6 classes in order |
| `ingestion/layout.py`, `clean.py` | X4: reading order, two-column rule, headings and section path, paragraphs, header/footer removal, hyphen joins |
| `ingestion/tables.py` | X4 step 1: tables to Markdown with caption and unit; numbers never changed |
| `ingestion/ocr.py`, `loaders/image.py` | X5: render at 1600 px, Gemini JSON schema, prompt `ocr-v1`, retries, key rotation, tokens and cost; EXIF fix |
| `ingestion/loaders/docx.py`, `text.py` | X2 for DOCX (section under a heading) and TXT (heading, or `lines a-b`) |
| `ingestion/quality.py` | X6 score and X7 review gate (an OCR page with a table is always reviewed: gap G7) |
| `ingestion/chunker.py` | X8: blocks to chunks, 400 / 700 tokens, overlap, never across a page, tables whole, context header |
| `ingestion/safety.py` | contract 04 S2: `injection_suspect`; `pii_found` |
| `ingestion/embedding.py`, `index_vector.py` | X9 vector index in Qdrant: deterministic point ids, payload, filters, one embedder per collection |
| `ingestion/index_bm25.py` | X9 BM25 with the ID-aware tokenizer |
| `ingestion/store.py`, `fin_store.py` | `knowledge.db`: document, page, chunk (contract 02); report, fin_table, fin_fact, metric_map, `v_fact_current` (contract 14) |
| `ingestion/fin_parse.py` | contract 14 F3 to F6: numbers (brackets, Indian grouping, dashes), unit and scale, periods, basis, statement, label dictionary |
| `ingestion/fin_tables.py` | contract 14 F1 to F7(a): collect tables, join continued tables, headers, facts, totals check |
| `ingestion/fin_ai.py` | contract 14 F1 vision tables (JSON) and F6 label proposals, with Gemini |
| `ingestion/fin_facts.py` | contract 14: writes report, fin_table, fin_fact, metric_map; restatements; table review and mapping services |
| `ingestion/pipeline.py` | one document from file to index; the ExtractionReport |
| `ingestion/service.py`, `jobs.py` | the services the routes call; document lifecycle (contract 03); the single ingest worker |
| `ingestion/search.py` | the search interface the agent calls |

## For Arka (agent): search

```python
from ingestion.search import SearchService
agent = Agent(search=SearchService(), tools=..., llm=..., reranker=...)
```

`SearchService` has the four methods of `model/agent/ports.py` `SearchPort`: `vector_search`, `bm25_search`
(`Hit(chunk_id, score, rank)`, ranks from 1), `get_chunks` (objects with the fields of `agent.types.Chunk`), and
`get_section_versions(doc_key, section)` for rule C1. Filters: `category`, `doc_key`, `version` (a value or a list),
`current_only`. Only searchable chunks are returned (X7). Checked against `retrieve()` and `find_conflicts()` of
`arka/agent`.

## For Sinngam (back end): services

```python
from ingestion import service
service.submit_document(path, meta, file_name=upload.filename, uploaded_by=admin)   # 202 body
service.list_documents(category, status); service.get_document(id); service.get_report(id)
service.get_page(id, n); service.page_image(id, n)  # PNG bytes
service.review_page(id, n, "APPROVE" | "REJECT", admin, comment)
service.reindex(id); service.delete_document(id); service.list_jobs()
```

Financial reports (contract 14): upload with the optional fields `company` (turns on fact extraction),
`report_type` (ANNUAL or QUARTERLY) and `fiscal_year` (FY2024-25; default: the year before the effective date).

```python
service.list_tables(id)                                   # GET  /documents/{id}/tables
service.get_table(table_id)                               # one table with its facts
service.review_table(table_id, "APPROVE" | "REJECT", admin, comment)   # POST /tables/{id}/review
service.list_metric_map(pending=True)                     # GET  /metric-map?pending=true
service.approve_mapping(line_label, metric, admin)        # POST /metric-map/approve (422 UNKNOWN_METRIC)
```

Facts tools read `v_fact_current`: only APPROVED tables and mapped metrics, newest report wins, `restated` with the
older value (`prev_value_printed`, `prev_report_id`, `prev_page`). `value_num` is an integer in the base unit: rupees
(AMOUNT), basis points (PERCENT), paise per share (PER_SHARE, for EPS), or a count (COUNT).

Each raises `ingestion.errors.IngestError` with `code`, `http_status` and `to_dict()` for the contract 05 error body.
`v_fact_current` and the contract 14 tables are in the same `knowledge.db` (`EXTRACTION_DATA_DIR`).

## Choices to know for the panel

- **Per page, not per document.** A text report with scanned annexures gets OCR only on the annexures.
- **OCR model `gemini-3.5-flash`, thinking level `low`, 60 s timeout.** The `gemini-flash-latest` alias timed out
  (504 after 45 s) on a one-line page on 27 Oct 2026; the fixed name with low thinking took 3 to 20 s. A fixed name
  also keeps results repeatable. Change it with `ocr.model` and `ocr.thinking_level`.
- **OCR renders at 1600 px of the long edge.** The old code capped the render scale at 1, which gives only 842 px for
  an A4 page, because PDF sizes are in points, not pixels.
- **A failed OCR page does not reject the document.** It goes to review (`OCR_FAILED`); the good pages are searchable.
- **Running headers:** a line is removed when the same text repeats at the top or bottom of more than half of the
  pages. A line whose number changes per page ("Page 3 of 10") is removed only when it is short (6 words or fewer) and
  not a heading, so "Section 3 Travel rules" at the top of a page stays.
- **BM25 IDF** uses the Lucene form, which is always positive; the classic form can give an exact ID a score of 0 in
  a small corpus.
- **Cost:** OCR cost is a Decimal string, or empty ("price not set") when `ocr.price_*` is not configured, never 0.
- **One embedder per collection.** The collection stores the embedder name and refuses another, so vectors of two
  models never mix.

- **Financial tables are stored twice** (contract 14): as a Markdown chunk for search and citation, and as one
  `fin_fact` row per number for the facts tools. A table goes to review when a total does not add up, the basis or
  unit is unknown, a number does not parse, a label is unmapped, or the table was read by a vision model.
- **Totals check:** at a "Total ..." row, the shortest run of rows (or subtotals) just above it that adds up to it is
  replaced by the total. So "Total assets" is checked against the two subtotals without knowing the layout. A total
  line with no rows of its own above it is recorded as unverified, not as a failure.

## Not done yet

- WP-EX7 demo documents, gold set and `extraction_eval.py`; WP-EX8 ingest of the demo corpus.
- Tesseract fallback (MAY in contract 10).
