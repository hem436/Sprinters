<!-- Contract 05. Owner: P4 with P1, P2, P3. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 05 API contract

Version: 1.0 · Status: DRAFT · Owner: P4 with P1, P2, P3 · Case section(s): 6 (Service layer), 12

## Conventions

- FastAPI. Every response has header `X-Request-Id` (= `query_id` for queries). OpenAPI at `/docs`.
- Admin routes: existing `require_admin` (HTTP basic). Chat routes: no login, `session_id` in the body.
- Errors: `{"error": {"code": "UPPER_SNAKE", "message": "...", "fields": [{"field": "...", "problem": "..."}]}}`.
- Money: JSON string with up to 6 decimals for cost (`"0.000360"`). Times: ISO 8601 with offset.

## Endpoints

| Method and path | Who | Part | Request | Success | Errors |
|---|---|---|---|---|---|
| POST /documents | admin | P1 | multipart: `file`, `title`, `category`, `version`, `effective_date`, `doc_key?` | 202 `{document_id, job_id, status: "QUEUED"}` | 422 UNSUPPORTED_TYPE, FILE_TOO_LARGE, CORRUPT_FILE, ENCRYPTED_PDF, INVALID_METADATA, TOO_MANY_PAGES; 409 DUPLICATE_DOCUMENT |
| GET /documents | admin | P1 | `?category&status` | list with status, pages, chunks, ocr cost | |
| GET /documents/{id} | admin | P1 | | document + ExtractionReport | 404 |
| GET /documents/{id}/pages/{n} | admin | P1 | | page text, class, method, quality, flags, status, `image_url` | 404 |
| GET /documents/{id}/pages/{n}/image | admin | P1 | | PNG render for the preview | 404 |
| POST /documents/{id}/pages/{n}/review | admin | P1 | `{decision: "APPROVE"|"REJECT", comment?}` | page with new status | 409 ILLEGAL_MOVE |
| POST /documents/{id}/reindex, DELETE /documents/{id} | admin | P1 | | 202 / 204 | 404, 409 |
| GET /jobs | admin | P1 | | ingest jobs with progress (`stage`, `done`, `total`) | |
| POST /query | anyone | P2 | `{question, session_id, filters?: {category?, doc_key?, current_only?}, config_id?}` | QueryResponse below | 422 EMPTY_QUESTION, 503 LLM_UNAVAILABLE (only if even the fallback text fails) |
| POST /query/stream | anyone | P2 | same | SSE events: status, citations, token, done (done carries the QueryResponse) | same, as an `error` event |
| POST /feedback | anyone | P3 | `{query_id, helpful, comment?}` | 201 | 404, 409 FEEDBACK_EXISTS |
| POST /queries/{id}/review | reviewer | P3 | `{comment}` | 201 | 404 |
| GET /metrics/summary | admin, reviewer | P3 | `?from&to&config_id&route&outcome` | KPI object (contract 11 section 9) | |
| GET /queries | admin, reviewer | P3 | same filters + `page`, `outcome` | list rows: id, ts, question_masked, route, outcome, reason, latency, cost, feedback | |
| GET /queries/{id} | admin, reviewer | P3 | | drill-down object (contract 11 section 9) | 404 |
| POST /eval/runs | reviewer | P3 | `{config_id: "A"|"B", case_ids?}` | 202 `{run_id}` | 409 RUN_IN_PROGRESS |
| GET /eval/runs, GET /eval/runs/{id} | reviewer | P3 | | run summary and per-case results | 404 |
| GET /health | anyone | P2 | | `{status, qdrant, llm, ocr_available, reranker, db}` | |

## JSON examples

**QueryResponse** (`POST /query`):

```json
{
  "query_id": "01JB7Z3K9QW",
  "answer_markdown": "The daily meal allowance in Mumbai is ₹2,000 under policy v2.0 (effective 1 Apr 2026) [E1]. Version 1.0 said ₹1,500 [E2].",
  "outcome": "SUCCESS", "reason_code": "OK_CONFLICT", "confidence": "HIGH", "route": "DOCS",
  "citations": [
    {"id": "E1", "kind": "document", "title": "Travel and Expense Policy", "version": "2.0", "page": 7,
     "section": "4.2 Per diem", "method": "text+tables", "url": "/documents/doc_7f3a/pages/7"},
    {"id": "E2", "kind": "document", "title": "Travel and Expense Policy", "version": "1.0", "page": 6,
     "section": "4.2 Per diem", "method": "ocr", "url": "/documents/doc_19c0/pages/6"}
  ],
  "tool_results": [],
  "conflict": true,
  "usage": {"tokens_in": 2410, "tokens_out": 96, "cost_usd": "0.000420", "estimated": false},
  "latency_ms": 3120
}
```

A tool citation looks like `{"id": "T1", "kind": "tool", "tool": "expense_total", "args": {"project_id": "P-104"}, "row_count": 1}`.

**Drill-down** (`GET /queries/{id}`), shortened:

```json
{
  "identity": {"query_id": "01JB7Z3K9QW", "ts": "2026-10-27T14:02:11+05:30", "session_id": "s-91",
               "app_version": "0.3.0", "config_id": "B"},
  "question": {"original_masked": "...", "normalized": "...", "route": "DOCS"},
  "execution": [{"stage": "retrieve_vector", "status": "OK", "latency_ms": 310}],
  "outcome": {"outcome": "SUCCESS", "reason_code": "OK_CONFLICT"},
  "retrieval": {"vector": [{"rank": 1, "chunk_id": "c_ab12", "doc": "travel-policy", "page": 7, "score": 0.81}],
                "bm25": [], "fused": [], "reranked": []},
  "context_turns": [{"turn_index": 1, "role": "user", "chars": 41}],
  "tool_calls": [],
  "generation": {"model": "openai/gpt-oss-120b", "prompt_version": "answer-v1", "validation": "OK"},
  "citations": [{"id": "E1", "valid": true}],
  "grounding": {"score": 1.0, "claims": [{"text": "...", "supported": true}]},
  "safety": {"flags": []},
  "performance": {"retrieval_ms": 640, "tool_ms": 0, "llm_ms": 2100, "total_ms": 3120},
  "usage": {"calls": [{"purpose": "route", "tokens_in": 380, "tokens_out": 40},
                      {"purpose": "answer", "tokens_in": 2030, "tokens_out": 56}],
            "cost_usd": "0.000420", "usage_source": "PROVIDER"},
  "feedback": null,
  "errors": []
}
```
