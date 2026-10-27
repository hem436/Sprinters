<!-- Contract 01. Owner: all. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 01 Team ownership, users and permissions

Version: 1.0 · Status: DRAFT · Owner: all · Case section(s): 6, 12

## Who owns which part (fill in the names)

Each part has one owner. The owner builds it with their agents and explains it to the panel. Parts talk to each
other only through the interfaces in the second table. If you need a change in another part, ask its owner; a
change to an interface goes through `CHANGES.md`.

| Part | Owner | Builds | Contracts they own | Folder in the repo |
|---|---|---|---|---|
| P1 Extraction and indexing | | intake validation, page classification, text / table / OCR extraction, quality score, chunking, embeddings, vector and BM25 indexes, extraction quality check | 10, parts of 02 (document, page, chunk) | `app/ingestion/`, `app/services/retrieval/index_*` |
| P2 Retrieval and agent | | hybrid search, fusion, rerank, router, approved SQL tools, conversation window, grounded answer, citation validator, injection and fallback handling | 04, 06, parts of 02 (business tables) | `app/agents/`, `app/tools/`, `app/services/retrieval/search*`, `app/guardrails/` |
| P3 Observability and evaluation | | query event store, outcome rules, token and cost accounting, metrics API, evaluation set, eval runner, config A versus B experiment | 11, 07, parts of 02 (event tables) | `app/observability/`, `evals/` |
| P4 Front end and dashboard | | chat with citations and feedback, admin upload with extraction preview and page review, dashboard (KPIs, drill-down, eval runs) | 05 (with P2, P3) | `web/` |
| Everyone | all four | pitch and presentation (each presents their own part), README and REPORT sections, the demo facts sheet, rehearsal | 00, 09, 12 | `output/design/`, `README.md`, `evals/facts.md` |

The work packages of each part, their order and the merge points are in contract 12.

## Interfaces between the parts (these are the contracts that let us work in parallel)

| From | To | Interface | Defined in |
|---|---|---|---|
| P1 | P2 | `Chunk` record and two search functions: `vector_search(query, k, filters)` and `bm25_search(query, k, filters)`, both returning `list[Hit]` | 02, 10 section 9 |
| P1 | P3 | `ExtractionReport` per document (pages, methods, quality, OCR tokens and cost) | 10 section 8 |
| P2 | P3 | `QueryRecorder`: one object per query; P2 calls `stage()`, `hits()`, `llm_call()`, `tool_call()`, `citations()`, `finish()` | 11 section 3 |
| P3 | P4 | `GET /metrics/summary`, `GET /queries`, `GET /queries/{id}`, `GET /eval/runs/...` | 05, 11 |
| P2 | P4 | `POST /query`, `POST /query/stream`, `POST /feedback` | 05 |
| P1 | P4 | `POST /documents`, `GET /documents`, `GET /documents/{id}/pages`, `POST /documents/{id}/review` | 05 |

Until a part is ready, the others use a stub that returns the contract's JSON example. Example: P4 builds the
dashboard against a fixture of `GET /queries/{id}` before P3's store exists.

## Users of the application (case 4.2 puts full identity out of scope)

| Role | Who it is | How it calls us |
|---|---|---|
| EMPLOYEE | asks questions | chat page, no login in the demo (session id only) |
| KNOWLEDGE_ADMIN | uploads documents, approves low-quality pages | admin page, admin password (existing `require_admin`) |
| REVIEWER | reads the dashboard and drill-down, runs evaluations, adds review comments | dashboard, same admin password in the demo |

## Permission matrix

Y = allowed; blank = 401 or 403.

| Action | EMPLOYEE | KNOWLEDGE_ADMIN | REVIEWER |
|---|---|---|---|
| Ask a question, give feedback | Y | Y | Y |
| Upload, re-index, delete a document; approve or reject pages | | Y | |
| See dashboard, drill-down, run evaluation | | Y | Y |
| Add a reviewer comment to a query | | | Y |

## Object checks

- An employee sees only their own session's history in the chat. The dashboard shows all queries, with the
  question text masked by the PII check (contract 11 section 6).
- Pages flagged low quality are not searchable until an admin approves them (contract 10 rule X7).
