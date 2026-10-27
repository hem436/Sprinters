<!-- Contract 08. Owner: P2. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 08 Non-functional requirements

Version: 1.0 · Status: DRAFT · Owner: P2 (all contribute) · Case section(s): 3, 6, 12

| Requirement | Target | How we meet it | How we show it |
|---|---|---|---|
| Query latency | p50 under 8 s, p95 under 15 s on the demo machine | parallel vector and BM25 search; rerank only 20; evidence capped at 6000 tokens; streaming | dashboard latency tiles per stage |
| Ingest time | a 300-page text report under 5 min; OCR about 6 to 20 s a page | background worker; OCR only pages that need it | ExtractionReport `duration_ms`, job progress |
| Reliability | no unhandled error reaches the user | timeouts and fallbacks on every AI call (contract 06); tool errors controlled (T4) | tool-failure eval cases; Errors panel |
| Reproducibility | same input, same index and same eval numbers | deterministic chunk ids; seeded business data; temperature 0.1; `config_id` and prompt versions recorded | eval run table has config and versions |
| Cost visibility | every query and every ingested document has a cost or "estimated" or "price not set" | contract 11 section 4 | cost tiles, drill-down Usage |
| Security | no secret in the repo; admin routes need auth; read-only DB for tools | `.env` (git-ignored); `require_admin`; `mode=ro` SQLite URI | code review; `/health` |
| Safety | retrieved and OCR text never acts as instructions | rules A1, S1, S2; injection eval cases | Safety KPI, eval results |
| Privacy | no personal data to hosted models | synthetic data; PII masking on questions (S3) | masked text on the dashboard |
| Engineering | modular Python, typed models, tests, logs | Pydantic schemas for every contract JSON; pytest; Ruff; structured logs with `query_id` | `pytest -q` green; Ruff clean |
| Deployment | one command start; cloud-ready | Docker Compose: api, web, qdrant (local container, so the demo does not depend on Qdrant Cloud) | `docker compose up` in the demo |
| Memory | the free-tier 512 MB limit of the existing repo does **not** bind us today | reranker and OCR on; the demo runs on the workstation | stated in `09_decisions.md` |
