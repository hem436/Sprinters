<!-- Contract 11. Owner: P3. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 11 Observability, cost and evaluation

Version: 1.0 · Status: DRAFT · Owner: P3 · Case section(s): 5 (FR-11, FR-12), 8, 9, 10

## 1. Principle

The case says an HTTP 200 is not a success. So we record two things separately for every query:

- **Execution status**: did each stage run without error (system view).
- **Outcome**: was the answer good: evidence found, citations valid, claims supported (AI-quality view).

Every number on the dashboard comes from one store: SQLite tables written by a `QueryRecorder`. Logfire and
LangSmith stay on for deep traces, but the dashboard never depends on them (the existing in-memory counters
reset on every restart; the case needs history and drill-down).

## 2. Event store (SQLite, `observability.db`)

| Table | One row per | Key columns |
|---|---|---|
| `query_event` | query | `query_id` (ULID), `ts`, `session_id`, `app_version`, `config_id`, `question_masked`, `normalized_query`, `route` (DOCS, SQL, BOTH, CONVERSATIONAL, BLOCKED), `answer`, `outcome` (SUCCESS, PARTIAL, FAILED), `reason_code`, `confidence` (HIGH, MEDIUM, LOW), `retrieval_relevant` (bool), `grounding_score` (0 to 1), `citations_valid` / `citations_total`, `safety_flags` (JSON list), `latency_ms_total`, `tokens_in`, `tokens_out`, `tokens_cached`, `cost_usd` (TEXT, Decimal), `cost_estimated` (bool), `error_category`, `correlation_id` |
| `query_stage` | stage of a query | `query_id`, `stage` (guard, plan, retrieve_vector, retrieve_bm25, fuse, rerank, tool, generate, validate), `status` (OK, SKIPPED, ERROR, TIMEOUT), `latency_ms`, `retries`, `detail` (JSON) |
| `retrieval_hit` | candidate chunk per list | `query_id`, `list` (vector, bm25, fused, reranked), `rank`, `chunk_id`, `document_id`, `page`, `score` |
| `llm_call` | model call | `query_id` or `document_id`, `purpose` (route, answer, judge, ocr, embed), `model`, `prompt_version`, `tokens_in`, `tokens_out`, `tokens_cached`, `cache_hit`, `latency_ms`, `cost_usd`, `usage_source` (PROVIDER, ESTIMATED) |
| `tool_call` | SQL tool call | `query_id`, `tool`, `args_sanitized` (JSON), `status`, `row_count`, `latency_ms`, `error_category` |
| `citation` | cited item | `query_id`, `citation_id`, `chunk_id` or `tool_call_id`, `valid` (bool), `reason` |
| `context_turn` | prior turn sent to the model | `query_id`, `turn_index`, `role`, `chars` |
| `feedback` | feedback | `query_id`, `helpful` (bool), `comment`, `reviewer_comment`, `ts` |
| `model_price` | model | `model`, `usd_per_1m_in`, `usd_per_1m_out`, `usd_per_1m_cached`, `source_url`, `checked_on` |
| `eval_run`, `eval_result` | run / case per run | section 7 |

## 3. QueryRecorder (interface P2 to P3)

```python
rec = QueryRecorder.start(question, session_id, config_id)    # assigns query_id, masks PII
with rec.stage("retrieve_vector"):                             # times it; status ERROR on exception
    hits = vector_search(...)
rec.hits("vector", hits)
rec.llm_call(purpose="answer", model=m, usage=resp.usage, latency_ms=t, prompt_version="answer-v1")
rec.tool_call(tool="expense_total", args=args, status="OK", row_count=3, latency_ms=40)
rec.citations(validated)                                      # list of {citation_id, chunk_id|tool_call_id, valid}
rec.finish(answer, route, grounding_score)                    # applies the outcome rules, writes all rows
```

Rules: the recorder never raises into the answer path (a failed write is logged and dropped, as the existing
`record_query` does). Writes happen once in `finish()`, in one transaction.

## 4. Tokens and cost

- **Source of the numbers:** the provider's `usage` object on each response (`prompt_tokens`,
  `completion_tokens`, cached tokens where given). For Gemini OCR and embeddings: `usage_metadata`.
- **Streaming:** request `stream_options: {"include_usage": true}` and read the usage on the last chunk.
  **To check on the day:** whether Portkey to Groq passes it through. If not, count tokens locally with a
  tokenizer, store `usage_source = ESTIMATED`, and the dashboard shows "estimated".
- **Cost** = `tokens_in × usd_per_1m_in ÷ 10^6 + tokens_out × usd_per_1m_out ÷ 10^6` (cached tokens at their own
  price if set), as `Decimal`, summed over all `llm_call` rows of the query. Prices live in the `model_price`
  table with the URL and the date we read them. If a model has no price, cost shows "price not set", not 0.
- **Cache hits** (Portkey caching is on): `cache_hit = true`, cost 0, still counted as a query.
- **Ingestion cost** is separate: OCR and embedding calls carry `document_id`, so the dashboard shows cost per
  document and cost per page type.

## 5. Outcome rules (deterministic; evaluated in this order, first match wins)

| Order | Outcome | Reason code | Condition |
|---|---|---|---|
| 1 | FAILED | `SYSTEM_ERROR` | an unhandled exception, no answer returned |
| 2 | FAILED | `LLM_ERROR` | answer generation failed on primary and fallback model |
| 3 | FAILED | `OUTPUT_INVALID` | the model's JSON fails the answer schema after 1 repair attempt |
| 4 | PARTIAL | `BLOCKED_SAFETY` | the guardrail blocked the question (an expected result for attack questions) |
| 5 | PARTIAL | `NO_EVIDENCE` | the fallback "not enough evidence" was returned (rule G1 in contract 04) |
| 6 | PARTIAL | `TOOL_FAILED` | route needed the SQL tool, the tool failed, the answer used documents only and says so |
| 7 | FAILED | `UNGROUNDED_ANSWER` | an answer with 0 valid citations |
| 8 | PARTIAL | `UNSUPPORTED_CLAIMS` | `grounding_score` < `obs.grounding_min` (0.8) or any citation invalid (removed) |
| 9 | SUCCESS | `OK` or `OK_CONFLICT` | otherwise; `OK_CONFLICT` when versions disagree and the answer shows both |

**Confidence category** (shown to the user): HIGH when SUCCESS and the top rerank score ≥
`obs.relevance_high` (0.7); MEDIUM when SUCCESS otherwise; LOW for PARTIAL.

## 6. Online checks per query (cheap, no extra LLM call)

| Check | How | Feeds |
|---|---|---|
| Retrieval relevant | top reranked score ≥ `obs.relevance_min` (0.3); a proxy, because live questions have no ground truth | `retrieval_relevant`, Retrieval success KPI |
| Citation valid | every citation id in the answer JSON is in this query's evidence set (reranked chunks or tool results) | `citation`, Citation support KPI |
| Grounding score | per claim: every number in the claim appears in its cited text (exact string or the same value after parsing) and at least 50 % of its content words appear there; score = supported claims ÷ claims | `grounding_score`, Grounding rate KPI |
| Safety | guardrail result, `injection_suspect` chunks used, PII in the question | `safety_flags`, Safety events KPI |
| PII masking | regex for e-mail, phone, PAN, Aadhaar, card numbers; masked before writing `question_masked` and before any hosted call | dashboard shows masked text only |

Offline we add the LLM-judge measures (RAGAS faithfulness and answer correctness) on the eval set only, because
they cost tokens and the existing setup is limited by Groq's rate limits.

## 7. Evaluation set and runner (case sections 9 and 10)

`evals/eval_set.jsonl`, at least 2 cases per scenario, about 25 in total. One case:

```json
{"id": "E07", "scenario": "conflicting_documents",
 "turns": ["What is the daily meal allowance in Mumbai?"],
 "expected_evidence": [{"doc_key": "travel-policy", "version": "1.0", "page": 6},
                       {"doc_key": "travel-policy", "version": "2.0", "page": 7}],
 "expected_route": "DOCS", "expected_behavior": "CONFLICT",
 "answer_must_include": ["1,500", "2,000"], "answer_must_not_include": []}
```

| Scenario (case 9) | Cases | `expected_behavior` |
|---|---|---|
| Direct factual question | 3 | ANSWER |
| Exact ID or acronym | 3 | ANSWER |
| Multi-turn follow-up | 2 (2 to 3 turns each) | ANSWER |
| Structured-data question | 3 | ANSWER, route SQL |
| Combined question | 2 | ANSWER, route BOTH |
| Insufficient evidence | 3 | FALLBACK |
| Conflicting documents | 2 | CONFLICT |
| Embedded prompt injection | 2 | IGNORE_INJECTION |
| Tool failure (runner sets `tools.simulate_failure`) | 2 | TOOL_ERROR_HANDLED |
| Regression question | 3 (taken from the others) | same as source |
| Handwritten / scanned source | 2 | ANSWER with an OCR page cited |
| Financial tables (contract 14) | 4: two-report comparison, restated figure, crore against million, metric not in the reports | ANSWER route SQL; FALLBACK for the missing metric |

**Measures per run** (`evals/run_eval.py --config A|B`, writes `eval_run` and `eval_result` and the CSVs in contract 07):

| Measure | Definition |
|---|---|
| hit@5 | expected (doc_key, version, page) present in the top 5 reranked chunks; for cases with evidence |
| recall@5 | expected evidence items found in the top 5 ÷ expected items |
| MRR | mean of 1 ÷ rank of the first expected item (0 if absent from top 10) |
| Route accuracy | `route` equals `expected_route` |
| Behaviour match | outcome and reason code match `expected_behavior` (for example FALLBACK means PARTIAL + NO_EVIDENCE) |
| Answer criteria | every `answer_must_include` string present and no `answer_must_not_include` string |
| Citation validity, grounding score | as section 6, averaged |
| Faithfulness, answer correctness | RAGAS with the judge key, on the cases with expected evidence |
| Latency p50 / p95, tokens, cost | from the event store, per run |

## 8. Configuration experiment (case section 10)

| | Config A | Config B |
|---|---|---|
| Retrieval | vector top 5 | vector top 20 + BM25 top 20, Reciprocal Rank Fusion (k = 60), FlashRank rerank to top 5 |
| Everything else | same prompt, model, temperature 0.1, same eval set | same |

Report (`output/evaluation_report.md`): what changed, every measure side by side, the latency and cost difference,
3 failure cases with their query ids (open in the drill-down), and our recommended config with the reason.

## 9. Dashboard (P4 builds the screens to this list)

**Aggregate view**, filter by time range, config, route and outcome. Each tile is one SQL query on the store.

| KPI (case 8.1) | Definition we use |
|---|---|
| Total queries | count of `query_event` |
| Overall outcome | count and rate of SUCCESS, PARTIAL, FAILED, with a stacked bar over time |
| Retrieval success | rate of `retrieval_relevant`; on eval runs also hit@5 |
| Grounding rate | rate of `grounding_score` ≥ 0.8 among answers |
| Citation support | `sum(citations_valid) ÷ sum(citations_total)` |
| Tool success | `tool_call.status = OK` ÷ tool calls |
| Safety events | count by flag |
| Latency | p50 and p95 of total, retrieval, tool and LLM stage |
| Usage and cost | tokens in and out, cost per query, total cost, cost per route; ingestion cost per document |
| User feedback | helpful and not-helpful counts and rate |

**Drill-down** (`/queries/{id}`), one panel per case 8.2 category: Identity, Question (original masked,
normalized, route), Execution (stage table with status and time), Outcome (code and reason), Retrieval (the four
ranked lists side by side with scores), Evidence quality (and expected-evidence match on eval queries),
Conversation context (turns sent), Tool calls, Generation (model, prompt version, raw output, validation result),
Citations (valid or not, and why), Grounding (each claim with supported or not), Safety, Performance, Usage
(tokens, cost, source of the numbers), Feedback, Errors (category, stage, retries, correlation id).

## 10. Tests

| Test | Expected |
|---|---|
| `test_outcome_order` | one fixture per row of section 5 gives that outcome and reason code |
| `test_cost_decimal` | 1,200 in and 300 out at 0.15 / 0.60 USD per 1M = `0.000360` |
| `test_missing_price_not_zero` | cost shows `null` with `price_not_set` |
| `test_citation_not_in_evidence_invalid` | a citation id not in the evidence set is invalid and removed |
| `test_grounding_number_mismatch` | claim "₹2,500" against chunk text "₹2,000" is unsupported |
| `test_recorder_never_raises` | a broken DB path still returns the answer |
| `test_hit_at_5_and_mrr` | known ranked lists give known values |
| `test_pii_masked` | phone and e-mail never reach `question_masked` |
