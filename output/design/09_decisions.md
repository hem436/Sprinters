<!-- Contract 09. Owner: all. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 09 Technology decisions

Version: 1.0 · Status: DRAFT · Owner: all · Case section(s): 6, 11

One row per choice. Every owner can say their rows from memory.

| Decision | Options considered | Chosen | Why, for this case | Trade-off | We would change it when |
|---|---|---|---|---|---|
| Base code | start fresh; the team's `chatbot` repo | `chatbot` repo | it already has LangGraph, Qdrant, rerank, OCR, guardrails, RAGAS, React; we add what the case needs | we inherit its choices (Portkey, Gemini) and must explain them | never today |
| Extraction unit (P1) | per document; per page | per page with a class | mixed PDFs and exact page citations need it; OCR cost only where needed | more records, more code | |
| OCR (P1) | Tesseract; PaddleOCR; Gemini vision; Azure Document Intelligence | Gemini vision, JSON output | reads handwriting and tables; no system packages; key already in the repo | network call per page, cost, data leaves the machine (synthetic data only) | data must stay on premises: a local vision model |
| Tables (P1) | pypdf text; pdfplumber; Camelot | pdfplumber `find_tables` to Markdown | pure Python, already a dependency, keeps rows and columns | misses tables without ruling lines; those fall back to text | Camelot stream mode if the reports need it |
| DOCX (P1) | unstructured; python-docx | python-docx | lighter, gives heading levels for section citations | we handle numbering ourselves | |
| Chunking (P1) | fixed 1500 chars (existing); blocks with token target | blocks, 400 tokens, tables whole, no page crossing, context header | exact citations; tables stay readable | more chunks | |
| Keyword search (P1/P2) | Qdrant sparse vectors; OpenSearch; `rank_bm25` | `rank_bm25` in process | tiny corpus; one line to explain; ID-aware tokenizer | rebuilt on each ingest; not for millions of chunks | corpus over about 100k chunks |
| Fusion (P2) | weighted score sum; RRF | RRF k = 60 | scores of BM25 and cosine are on different scales; RRF uses ranks only | ignores score gaps | |
| Rerank (P2) | none; FlashRank; hosted reranker | FlashRank (existing) | local, fast, no cost | small model | |
| SQL tool (P2) | text-to-SQL (as in our `ecommerce-chatbot`); approved templates | approved parameterised templates, read-only DB | the case says "approved tools"; no SQL injection; testable | fewer questions answerable | MAY: text-to-SQL with a SELECT-only parser check |
| Vector DB | Qdrant Cloud (existing); local Qdrant; Chroma; FAISS | Qdrant, local container for the demo | same client code; no cloud dependency on campus Wi-Fi | one more container | |
| Event store (P3) | Logfire only; OpenTelemetry stack; SQLite tables | SQLite tables + Logfire for traces | the dashboard needs SQL queries and history that survive restarts; zero setup | not for many writers | Postgres when there are several API workers |
| Online grounding (P3) | LLM judge per query; deterministic check | deterministic (numbers exact, word overlap); LLM judge offline only | no extra cost or latency per query; numbers are where errors hurt | weaker than a judge on paraphrase | |
| Numbers in financial tables (P1/P2) | answer from table chunks; a facts table with approved tools | both: chunks for search and citation, `fin_fact` + 4 tools for numbers | exact comparisons across reports; units, basis and restatements handled in code | extraction, mapping and review work | if only one report and no comparisons are needed |
| Security | no auth; full login; admin password + server-side checks | admin password (existing `require_admin`), read-only DB user for tools, secrets only in `.env`, PII masking before any hosted call | case 4.2 puts enterprise identity out of scope; the rest closes the real risks | no per-user access control | real users and roles arrive |
| UI (P4) | Streamlit; React | React (existing `web/`) | the repo has it; a product-like chat and dashboard | more work than Streamlit | |
| Orchestration (P2) | custom Python; LangGraph | LangGraph (existing) | explicit nodes and routing are easy to draw and explain | a library to learn | |
