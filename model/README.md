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

Your `run_tool(name, args)` must return `agent.types.ToolResult` with a status from contract 13 section 5 and a
`summary` sentence that holds the exact numbers. `list_tools()` returns name, description and argument schema only.
The recorder gets `stage`, `hits`, `llm_call`, `tool_call`, `citations` and, once at the end, `finish(response, details)`;
`details` has `question_masked`, `normalized_query`, `route_reason`, `context_turns`, `grounding_detail`,
`safety_flags`, `conflicts`, `conflict_not_shown` and the outcome `facts`. Cost: price the `LLMReply` rows you get in
`llm_call` (tokens in, out, cached; `usage_source`).

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

## Next

WP-AG6 eval set and runner, WP-AG7 A and B runs and the demo script, and a streaming generator for `/query/stream`.
