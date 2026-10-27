<!-- Contract 15. Owner: all (Arka keeps it current). Status: DRAFT until the design review, then FROZEN v1.0. -->
# 15 Requirements trace: every case requirement, where it is met, who owns it

Version: 1.0 · Status: DRAFT · Owner: all · Source: `cases/AI_Powered_Enterprise_Knowledge_Intelligence_Assistant.docx`

Checked line by line on 27 October 2026. **Met** = the design covers it. **Fixed today** = a gap we found in this check
and closed in the named contract. Nothing in the case is left unmet; two items are deliberately MAY (marked).

## Section 3: Objectives

| # | Requirement (case words, short) | Where in our design | Owner | Status |
|---|---|---|---|---|
| O1 | Answer from approved PDF, DOCX, TXT, scanned and handwritten documents, plus a structured data source | 10 (X1 to X9), 13, 14 | Myank, Sinngam | Met |
| O2 | Concise answers with document, page or section references and tool-result provenance | 04 A2, A3; 05 citations; 13 section 5 | Arka | Met |
| O3 | Hybrid retrieval and reranking for meaning and for exact terms, IDs, policy names | 04 H1 to H4; 10 X9 ID-aware tokenizer | Arka, Myank | Met |
| O4 | Use conversation context **safely** for follow-ups | 04 M1: last 3 turns, blocked turns skipped, PII masked | Arka | Fixed today (04 M1) |
| O5 | Detect insufficient, conflicting or malicious evidence and respond safely | 04 G1, C1 (with other-version fetch), S2, V4 | Arka | Fixed today (C1 other versions, V4) |
| O6 | Measure retrieval quality, answer correctness, grounding, safety, latency, tokens, cost, reliability | 11 sections 4 to 8 | Sinngam, Arka | Met |
| O7 | Central dashboard with KPIs and query-level drill-down | 11 section 9; 12 WP-UI4, WP-UI5 | Hemant, Sinngam | Met |
| O8 | Modular Python, APIs, validation, tests, logging, reproducibility, cloud readiness | 08; 05; tests in 10, 11, 13, 14; Docker | Sinngam | Met |

## Section 4.1: In scope

| # | Requirement | Where | Owner | Status |
|---|---|---|---|---|
| S1 | Upload and process PDF, DOCX, TXT, scanned and handwritten documents | 10 X1, X2, X5 | Myank | Met |
| S2 | Extract, **clean**, chunk; keep document, page, section metadata | 10 X4 step 2 (cleaning), X8 | Myank | Fixed today (cleaning rules) |
| S3 | Embeddings and vector index | 10 X9; config `embed.*` | Myank | Fixed today (embedding config keys) |
| S4 | BM25, vector, fusion, reranking | 04 H1 to H4 | Arka | Met |
| S5 | Metadata filters: document, category, version, effective status | 04 H1 filters, `current_only`; 05 `filters`; 12 WP-UI1 filter controls | Arka, Hemant | Fixed today (filters in the chat screen) |
| S6 | Multi-turn questions with controlled context | 04 M1 | Arka | Met |
| S7 | SQL or approved API tools on a synthetic business dataset | 13; 14 section 6 | Sinngam | Met (REST API tool is MAY) |
| S8 | Grounded generation, citations, citation validation, insufficient-evidence fallback | 04 A1 to A4, V1, V2, G1 | Arka | Met |
| S9 | Prompt-injection detection; retrieved content is untrusted data | 04 S1, S2, A1, V4; 10 X5 prompt rule 4 | Arka, Myank | Met |
| S10 | Feedback capture, automated evaluation, query observability dashboard | 05 `/feedback`; 11 | Sinngam, Arka, Hemant | Met |
| S11 | Containerised local or cloud-compatible deployment | 08; 12 WP-BE1 Docker Compose | Sinngam | Met |

## Section 4.2: Out of scope (we respect it)

Training or fine-tuning (none: 06), enterprise identity (admin password only: 01, 09), real-time ingestion from many
platforms (no connectors: 13 section 6), confidential or personal data (synthetic only: 02, 13), voice (none), full
computer-vision pipelines (one vision-model call per page: 10 X5; assumptions 4).

## Section 5: Functional requirements

| FR | Requirement | Where | Owner | Status |
|---|---|---|---|---|
| FR-01 | Validate type, size, metadata; reject unsupported or corrupted | 10 X1 | Myank | Met |
| FR-02 | Extract and clean; keep source, page, section, category, version | 10 X2, X4, chunk record | Myank | Fixed today (cleaning) |
| FR-03 | Configurable chunking and embeddings; repeatable indexing | 10 X8, X9, config keys; deterministic `chunk_id` | Myank | Fixed today (embedding keys) |
| FR-04 | Hybrid retrieval | 04 H1 to H3 | Arka | Met |
| FR-05 | Rerank before the prompt | 04 H4 | Arka | Met |
| FR-06 | Follow-ups without unlimited history | 04 M1 | Arka | Met |
| FR-07 | Route to documents, SQL or API tool, or both | 04 R1, R1b; 13; 14 section 7 | Arka (routing), Sinngam (tools) | Met |
| FR-08 | Answer only from evidence and name the sources | 04 A1 to A3, V1, V2 | Arka | Met |
| FR-09 | Show conflicts between versions or sources | 04 C1; 14 section 5 (restated numbers) | Arka, Sinngam | Fixed today (other-version fetch) |
| FR-10 | Insufficient-evidence or controlled-error answers | 04 G1, T4; 13 section 5 statuses | Arka, Sinngam | Met |
| FR-11 | Helpful / not helpful feedback with reviewer comments | 05 `/feedback`, `/queries/{id}/review` | Sinngam, Hemant | Met |
| FR-12 | Aggregate monitoring and drill-down for every query | 11 sections 2, 9 | Sinngam, Hemant | Met |

## Section 6: Reference architecture (every layer present)

| Layer | Case components | Ours | Owner |
|---|---|---|---|
| Experience | chat, monitoring dashboard | React chat, admin, dashboard (12 WP-UI1 to WP-UI5) | Hemant |
| Service | FastAPI ingest, query, feedback, metrics, health; contracts, validation, errors, request ids | 05; 12 WP-BE1, WP-BE6, WP-BE7 | Sinngam |
| Orchestration | router, context manager, prompt template, output validator | 04 R1, M1, A1 to A4, V1 to V4 (LangGraph) | Arka |
| Knowledge | parser, chunker, metadata store, BM25, vector DB, reranker | 10; 04 H4 | Myank, Arka |
| Tools | SQLite / SQL service, optional REST API | 13, 14 section 6 (REST: MAY) | Sinngam |
| Model | hosted LLM or open model | 06 (Groq via Portkey, Gemini) | Arka |
| Safety | injection controls, PII checks, citation verifier, fallback policy | 04 S1 to S3, V1, V4, G1 | Arka |
| Evaluation | test dataset, retrieval / answer / safety evaluators, regression runner | 11 sections 7, 8 | Arka |
| Observability | event store, logs, traces, usage and cost | 11 sections 2 to 4; Logfire | Sinngam |

## Section 7: Workflow (12 steps)

| Step | Case expects | Where | Status |
|---|---|---|---|
| 1 to 3 | intake, preparation, indexing | 10 | Met |
| 4 | normalise, resolve context, assign a query id | 04 M1, R1; 11 `query_id` | Met |
| 5 | route | 04 R1, R1b | Met |
| 6 | hybrid search, fusion, metadata filter, rerank | 04 H1 to H4 | Met |
| 7 | validated tool calls with status, count, latency | 13 section 5 | Met |
| 8 | grounded prompt from approved evidence only | 04 A1, A4; 10 X7 | Met |
| 9 | check citations, unsupported claims, output schema **and safety conditions** | 04 V1 to V4 | Fixed today (V4 output safety) |
| 10 | answer, citations, confidence, fallback | 05 QueryResponse; 11 confidence | Met |
| 11 | stage-level events | 11 `query_stage` | Met |
| 12 | feedback and evaluation | 05; 11 section 7 | Met |

## Section 8: Dashboard

**8.1 KPIs:** total queries, overall outcome, retrieval success, grounding rate, citation support, tool success, safety
events, latency, usage and cost, user feedback: all ten are in 11 section 9. **Met.** The case's rule "a 200 is not
automatically a success" is 11 section 5. **Met.**

**8.2 drill-down:**

| Category | Our field(s) | Status |
|---|---|---|
| Identity | `query_id`, `ts`, `session_id`, `app_version`, `config_id` | Met |
| Question | `question_masked`, `normalized_query`, `route` | Met |
| Execution status | `http_status`; `query_stage.status` per stage | Fixed today (`http_status`) |
| Overall outcome | `outcome`, `reason_code` | Met |
| Retrieval | `retrieval_hit` (4 lists: ids, metadata, raw, fused, reranked scores) | Met |
| Evidence quality | `retrieval_relevant`; expected-evidence match on eval queries | Met |
| Conversation context | `context_turn` with masked text, blocked turns excluded | Fixed today (`text_masked`) |
| Tool calls | `tool_call`: name, sanitised args, status, **result summary**, latency | Fixed today (`result_summary`) |
| Generation | `llm_call`: model, prompt version; answer; validation status | Met |
| Citations | `citation`: valid or not, why | Met |
| Grounding | `grounding_score` and `grounding_detail` (each claim supported or not) | Fixed today (`grounding_detail`) |
| Safety | `safety_flags`: guard, injection, PII, fallback | Met |
| Performance | stage latencies, total | Met |
| Usage | tokens in, out, cached; cost; `usage_source` | Met |
| Feedback | `feedback` | Met |
| Errors | `error_category`, stage, retries, `correlation_id` | Met |

## Section 9: Evaluation dataset

Fixed test set with questions, expected evidence, answer criteria and expected behaviour (11 section 7); all 10 case
scenarios plus handwriting and financial tables; a corpus with deliberate hard cases (scanned v1.0 against text v2.0,
injection footer, handwriting, restated figures). Owner Arka, with Myank's extraction and table cases. **Met.**

## Section 10: Configuration experiment

Config A (vector, then LLM) against config B (hybrid, RRF, rerank, then LLM) on the same set; the report says what
changed, quality, latency and cost impact, failure cases, recommendation (11 section 8, 07). Owner Arka; cost numbers
Sinngam. **Met**, with fixes today: config A has its own relevance threshold; MRR is on the final top 5.

## Section 12: Deliverables

| Deliverable | Where | Owner | Status |
|---|---|---|---|
| Working app: ingestion, conversation, grounded answers, citations | whole design | Arka, Myank | Met |
| Hybrid retrieval and reranking | 04 H1 to H4 | Arka | Met |
| At least one SQL or API tool through controlled routing | 13; 14 section 6; 04 R1 | Sinngam, Arka | Met |
| Dashboard: KPIs and drill-down | 11 section 9 | Hemant | Met |
| Query event schema; Success / Partial / Failed rules | 11 sections 2, 5 | Sinngam, Arka | Met |
| Modular code, **dependency manifest, configuration sample**, README | 07 repository deliverables; 12 WP-BE8, WP-UI6 | Sinngam, Hemant | Fixed today (listed with owners) |
| FastAPI: ingestion, query, feedback, metrics, health | 05 | Sinngam | Met |
| Eval dataset with evidence, criteria, safety cases | 11 section 7 | Arka | Met |
| Evaluation and configuration-comparison report | 07; 11 section 8 | Arka | Met |
| Automated tests for workflow and quality / status rules | tests listed in 10, 11, 13, 14 | each owner | Met |
| Architecture diagram; decisions on model, chunking, retrieval, tools, **security**, observability | 00 diagram, `architecture.png`; 09 | all | Fixed today (security row in 09) |
| Demonstration package: synthetic documents, structured data, **scripted scenarios** | 07; 12 WP-EX7, WP-BE2, WP-AG7 (`demo/script.md`, `run_demo.py`) | Myank, Sinngam, Arka | Fixed today (scripted scenarios) |
| Whole codebase in Git | `hem436/Sprinters` | Hemant (repo owner, merges; contract 01 section 4) | Met |

## Gaps closed in this check

| Gap | Case reference | Fixed in |
|---|---|---|
| No text-cleaning step | 4.1, FR-02 | 10 X4 step 2 |
| Embedding model not configurable | FR-03 | 10 section 12 |
| Context could carry blocked or personal text | 3, 8.2 | 04 M1 |
| No output safety check | 7 step 9 | 04 V4 |
| Drill-down missing HTTP status, tool result summary, claim detail, turn text | 8.2 | 11 section 2 |
| Filters not on any screen | 4.1 | 12 WP-UI1 |
| Manifest, config sample, scripted scenarios not owned | 12 | 07, 12 |
| No security decision recorded | 12 | 09 |
| Earlier defence gaps G3 to G7 (config A threshold, MRR@5, dropped events, versions outside the top 5, confident OCR digits) | 9, 10, FR-09, 8 | 04, 10, 11 |
