<!-- Contract 01. Owner: all. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 01 Team ownership, users and permissions

Version: 1.0 · Status: DRAFT · Owner: all · Case section(s): 6, 12

## 1. Two pairs, four owners

| Pair | Person | Part | Owns (builds, tests, explains to the panel) | Backup for |
|---|---|---|---|---|
| **Pair A: data in and screens** | **Myank** | **P1 Extraction and indexing** | upload checks, page classes, cleaning, text, tables and OCR, quality gate, chunking, embeddings, Qdrant and BM25 indexes, financial facts extraction (contract 14 F1 to F8), demo documents, extraction gold set and its report | Hemant's front end |
| | **Hemant** | **P4 Front end, and merging** | chat (streaming, citations, filters, feedback), admin pages (upload, jobs, page review, table review, metric-map approval, tools list), dashboard (KPIs, drill-down, eval runs), README assembly, the joined slide deck; **owns the repo and merges every branch into `main`** (section 4) | Myank's extraction |
| **Pair B: brains and service** | **Arka** | **P2 Agent (LangGraph and LangChain)** | the graph: guard, context window, router, hybrid fusion and rerank, answer prompt, validators (citations, grounding, output safety), conflicts, fallback, outcome-rule functions; evaluation set, eval runner, A vs B report; demo script | Sinngam's back end |
| | **Sinngam** | **P3 Back end, tools and observability** | FastAPI app (all endpoints, validation, errors, request ids), SQL tools and business data (contract 13), facts tools (contract 14 section 6), event store and `QueryRecorder`, metrics and drill-down API, cost and price table, Docker Compose, `/health`, config sample and dependency manifest | Arka's agent |

Pair A turns files into searchable, reviewed evidence and shows everything on screen. Pair B turns a question into a
checked answer and records it. Each person can explain their buddy's part at a high level, because the panel may ask
anyone about anything.

## 2. What each person owns: contracts, folders, work packages

| Person | Contracts they own (they approve changes) | Folders | Work packages (contract 12) |
|---|---|---|---|
| Myank | 10, 14 (sections 1 to 5, 8), parts of 02 (knowledge tables), 03 | `app/ingestion/`, `app/services/retrieval/index_*`, `demo/documents/`, `evals/extraction_gold/` | WP-EX1 to WP-EX8 |
| Hemant | 05 (screens and their API calls, with Sinngam), the dashboard list in 11 section 9; the merge checklist (section 4) | `web/`; `main` branch | WP-UI1 to WP-UI6, WP-MG |
| Arka | 04, 06, 11 sections 6 to 8 (online checks, evaluation, A vs B), 07 (eval outputs), 15 | `app/agents/`, `app/guardrails/`, `app/prompts/`, `app/services/retrieval/search*`, `evals/`, `demo/script.md` | WP-AG1 to WP-AG7 |
| Sinngam | 05 (endpoints, with Hemant), 11 sections 2 to 5 (store, recorder, cost, outcome storage), 13, 14 section 6 (tools), parts of 02 (business and event tables), 08 | `app/main.py`, `app/api/`, `app/tools/`, `app/observability/`, `scripts/make_business_data.py`, `docker-compose.yml`, `config/` | WP-BE1 to WP-BE8 |
| Everyone | 00, 09, 12, `assumptions.md` | `README.md`, `evals/facts.md` | WP-0, WP-X |

## 3. Interfaces between the owners

Each interface has one provider and a JSON or Python example in its contract. The consumer builds against that
example (a stub) until the provider is ready.

| Provider | Consumer | Interface | Contract |
|---|---|---|---|
| Myank | Arka | `Chunk` record; `vector_search(query, k, filters)`, `bm25_search(query, k, filters)` returning `list[Hit]` | 10 section 9 |
| Myank | Sinngam | `fin_fact`, `report`, `fin_table` rows and the view `v_fact_current` | 14 section 3 |
| Myank | Sinngam | ingestion services the routes call: `submit_document`, `get_report`, `review_page`, `review_table`, `approve_mapping` | 10, 14 |
| Myank | Sinngam, Hemant | `ExtractionReport` per document; page and table review states | 10 section 8, 14 F8 |
| Sinngam | Arka | tool registry: `run_tool(name, args) -> ToolResult` with status, rows, summary, provenance | 13 sections 4 and 5 |
| Sinngam | Arka | `QueryRecorder` (`stage`, `hits`, `llm_call`, `tool_call`, `citations`, `finish`) | 11 section 3 |
| Arka | Sinngam | `answer(question, session_id, filters, config_id) -> QueryResponse`, called by `POST /query` and `/query/stream` | 05 |
| Arka | Sinngam | outcome-rule function `classify(record) -> (outcome, reason_code)`; `run_eval(config_id, case_ids) -> run_id` | 11 sections 5 and 7 |
| Sinngam | Hemant | every endpoint in contract 05 with its JSON example | 05 |

## 4. Branches and merging (Hemant)

- **Branches:** `myank/extraction`, `hemant/web`, `arka/agent`, `sinngam/backend`. Nobody pushes to `main` except Hemant.
- **When:** at the three merge points of contract 12 (end of each iteration), and at once for an urgent fix.
- **Hemant's merge checklist, for each branch:**
  1. The owner says the branch is ready and its tests pass (`pytest -q`, `npm run build` for `web/`).
  2. **One person from the other pair** has read the diff (Pair B reviews Pair A, Pair A reviews Pair B).
  3. `contract-check`: the code matches the frozen contracts (names, fields, error codes, statuses).
  4. Merge in this order: back end and extraction first (they provide interfaces), then agent, then web.
  5. After each merge: run all tests on `main`; if red, revert that merge and tell its owner.
  6. After the last merge: `docker compose up`, run `scripts/run_demo.py`, rebuild the design document, push `main`.
- **Conflicts:** Hemant does not resolve a conflict inside another owner's folder alone; the owner resolves it with him.
- **Pair sync:** each pair talks every 30 minutes for 5 minutes; both pairs meet at each merge point.
- **Contract change:** the contract's owner proposes it (`design-change`), the consumer agrees, then `CHANGES.md` and a
  version bump. Nobody changes another owner's contract or folder; ask the owner.
- **Blocked:** use the stub and continue; tell your buddy first.

## 5. Case deliverables (section 12) and who answers for each

| Deliverable | Owner | Contributors |
|---|---|---|
| Working app: ingestion, conversational query, grounded answers, citations | Arka (answers), Myank (ingestion) | Sinngam, Hemant |
| Hybrid retrieval and reranking | Arka | Myank (indexes) |
| SQL tool through controlled routing | Sinngam (tools) | Arka (routing) |
| Observability dashboard: KPIs and drill-down | Hemant (screens) | Sinngam (data and API) |
| Query event schema; Success / Partial / Failed rules | Sinngam (schema) | Arka (rules) |
| Modular code, dependency manifest, configuration sample, README | Sinngam (manifest, config) | all; Hemant joins the README |
| FastAPI endpoints: ingestion, query, feedback, metrics, health | Sinngam | Myank (ingestion logic), Arka (query logic) |
| Evaluation dataset: questions, evidence, criteria, safety cases | Arka | Myank (extraction and table cases) |
| Evaluation and configuration-comparison report | Arka | Sinngam (latency, tokens, cost numbers) |
| Automated tests for workflow and quality / status rules | each owner for their folder | Arka checks the outcome-rule tests |
| Architecture diagram and design decisions | all (09) | Hemant draws the final diagram |
| Demonstration package: documents, structured data, scripted scenarios | Myank (documents), Sinngam (data), Arka (script) | Hemant (demo flow on screen) |
| Codebase in Git | Hemant (repo owner, merges) | all |

## 6. Users of the application (case 4.2 puts full identity out of scope)

| Role | Who it is | How it calls us |
|---|---|---|
| EMPLOYEE | asks questions | chat page, no login in the demo (session id only) |
| KNOWLEDGE_ADMIN | uploads documents, approves low-quality pages and tables, approves metric mappings, sees tools | admin page, admin password (existing `require_admin`) |
| REVIEWER | reads the dashboard and drill-down, runs evaluations, adds review comments | dashboard, same admin password in the demo |

## 7. Permission matrix

Y = allowed; blank = 401 or 403. Checked on the server, never only in the page.

| Action | EMPLOYEE | KNOWLEDGE_ADMIN | REVIEWER |
|---|---|---|---|
| Ask a question, give feedback | Y | Y | Y |
| Upload, re-index, delete a document; approve or reject pages and tables; approve metric mappings | | Y | |
| See and try approved tools | | Y | |
| See dashboard, drill-down, run evaluation | | Y | Y |
| Add a reviewer comment to a query | | | Y |

## 8. Object checks

- An employee sees only their own session's history in the chat. The dashboard shows all queries, with the
  question text masked by the PII check (contract 11 section 6).
- Pages and tables flagged for review are not used until an admin approves them (contract 10 X7, contract 14 F8).
