# model/: the agent (P2, Arka)

Question in, checked answer out. Built with LangGraph to contracts 04, 06 and 11 sections 5 to 8. Branch `arka/agent`.

## Run the tests

```bash
cd model
pip install -r requirements.txt
python -m pytest -q          # 53 tests, no network, no keys: search, tools and the model are stubs
```

## Where each rule lives

| File | Rules (contract 04 unless named) |
|---|---|
| `agent/safety.py` | S1 guard, S2 injection check, S3 PII masking, V4 output check (canary, injected sentences, PII) |
| `agent/context.py` | M1 conversation window: last 3 turns, blocked turns skipped, masked, cut to 600 characters |
| `agent/router.py`, `prompts/route-v1.txt` | R1 and R1b: greeting rule, planner JSON, rule override (SQL or BOTH), `ROUTE_FALLBACK` |
| `agent/retrieval.py` | H1 to H4: vector + BM25, RRF (k = 60), rerank to 5; config A (vector top 5) and B; C1 conflicts |
| `agent/numbers.py` | exact numbers in text (Indian grouping, brackets as negatives) for C1 and V2 |
| `agent/answer.py`, `prompts/answer-v1.txt` | A1 evidence tags, A2 answer JSON, A4 token budget, G1 fixed texts, V3 one repair |
| `agent/validate.py` | V1 citations in evidence, V2 grounding (numbers by value, half the content words) |
| `agent/outcome.py` | contract 11 section 5 outcome rules in order, confidence, relevance threshold per config |
| `agent/graph.py` | the LangGraph graph: guard, plan, retrieve, tool, generate, validate |
| `agent/service.py` | `Agent.answer(...)`, the in-memory session store, the QueryResponse of contract 05 |
| `agent/llm.py` | OpenAI-compatible client (Groq or Portkey), standard library only, usage from the provider |
| `agent/ports.py`, `agent/stubs.py` | what the agent needs from Myank and Sinngam, and stand-ins until they are ready |
| `agent/config.py` | every threshold, with the contract key it comes from |

## For Sinngam (back end): how `/query` calls the agent

```python
from agent.service import Agent
from agent.llm import llm_from_env
from agent.retrieval import FlashRankReranker

agent = Agent(search=<Myank's search>, tools=<your tool registry>, llm=llm_from_env(), reranker=FlashRankReranker())

recorder = QueryRecorder.start(...)            # yours; must have .query_id and the methods in agent/ports.py
response = agent.answer(question, session_id, recorder, filters=filters, config_id=None)   # -> QueryResponse
return response.model_dump()                   # the body of POST /query (contract 05)
```

Streaming (`POST /query/stream`): `agent.answer_stream(question, session_id, recorder, filters, config_id)` yields
`(event, data)` pairs; write each as `event: <event>` and `data: <json>`. Order: `status` per stage (`guard`,
`context`, `route`, `retrieve_vector`, `retrieve_bm25`, `fuse`, `rerank`, `tool`, `answer`, `validate`, each with a
`label`), then `citations`, then `token` (the checked answer, word by word), then `done` (the QueryResponse). If a part
fails (Qdrant down, a tool raises), the agent does not raise: you get `error` (`SYSTEM_ERROR`, with the query id) and
`done` with outcome FAILED, and the recorder gets `error_category`. `answer()` runs the same path and returns the
`done` response.

Your `run_tool(name, args)` must return `agent.types.ToolResult` with a status from contract 13 section 5 and a
`summary` sentence that holds the exact numbers. `list_tools()` returns name, description and argument schema only.

The agent calls your `QueryRecorder` exactly as written in `backend/app/observability/recorder.py` (contract 11
section 3): `stage`, `hits` (rows with chunk id, rank, score, document and page), `llm_call` (provider usage, or
`estimate=` when the provider sent none), `tool_call`, `citations`, `context_turns`, then `finish(...)` once. It reads
`cost_usd` and `cost_estimated` from your `FinishResult` and puts them in the response. All translation is in
`agent/recording.py`. `tests/test_integration_recorder.py` runs the agent against your real recorder whenever
`backend/` is next to `model/` (on `main`), so a change on either side that breaks the other fails a test.

## For Myank (extraction): what search must provide

`vector_search`, `bm25_search` (return `Hit(chunk_id, score, rank)`, ranks from 1), `get_chunks(ids)` (return
`agent.types.Chunk`), and `get_section_versions(doc_key, section)` for conflict rule C1. Filters: `category`,
`doc_key`, `version`, `current_only`. Only searchable chunks (contract 10 X7).

## Model settings

Copy `.env.example` to `.env`. Groq directly: `LLM_BASE_URL=https://api.groq.com/openai/v1` and `LLM_API_KEY`.
Through Portkey: `LLM_BASE_URL=https://api.portkey.ai/v1`, `PORTKEY_API_KEY` and `PORTKEY_CONFIG_SLUG` (the saved
config decides the model there). Check the model names on the provider's list on the day.

## Choices to know for the panel

- The outcome rules run in code, not in the model; the model never writes SQL and never does arithmetic.
- A fixed text answers when there is no usable evidence, so no tokens are spent and nothing is guessed.
- A greeting gets reason code `OK_SMALLTALK` (added to contract 11's list: small talk has no evidence to cite).
- A conflict counts only when the answer shows both versions; if code found one the answer hid, `conflict_not_shown`
  goes to the drill-down.

## Open items between the parts

1. **One copy of the outcome rules** (Sinngam and Arka). `backend/app/observability/outcome.py` repeats ours without
   `OK_SMALLTALK` (CHANGES DC-1), so a greeting is SUCCESS for the user and FAILED on the dashboard. Proposal:
   `finish()` takes `outcome`, `reason_code` and `confidence` from the agent when given, and uses its own rules only
   when the agent did not run (a system error before the agent). The integration test marks this as a known failure.
2. **The API image must contain `model/`** (Sinngam). `docker-compose.yml` builds only `./backend`. Proposal: build
   context at the repo root, the Dockerfile copies `model/` and installs `model/requirements.txt`, `PYTHONPATH`
   includes `/app/model`.
3. **Model names in one place** (Sinngam and Arka). `config/app.yaml` has `llm.route_model` and `llm.answer_model`;
   `llm_from_env` reads `LLM_MODEL`. Proposal: names from `app.yaml`, keys only in `.env`; add an `agent:` section
   with the keys of `agent/config.py`.
4. **Search** (Myank): done. `extraction/ingestion/search.py` `SearchService` fits `SearchPort`; checked by ingesting
   two policy PDFs with his pipeline and asking the agent (conflict found, both versions cited with page and section).
5. **Front end** (Hemant): add `OK_SMALLTALK` to `ReasonCode`; `page` can be null for DOCX and TXT sources.

## Next

WP-AG6 eval set and runner, WP-AG7 A and B runs and the demo script, and a streaming generator for `/query/stream`.
