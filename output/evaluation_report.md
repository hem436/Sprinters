# Evaluation report: config A against config B

Case section 10, contract 11 section 8, contract 07. Owner: Arka (P2). Written 27 Oct 2026 from the files in this folder.

## 1. What we compared

| | Config A | Config B |
|---|---|---|
| Retrieval | vector search, top 5 | vector top 20 + BM25 top 20, Reciprocal Rank Fusion (k = 60) into 20, FlashRank rerank, top 5 |
| Relevance gate (answer or "could not find") | cosine score at least 0.6 | rerank score at least the gate (run 1: 0.01 with TinyBERT-L-2) |
| Everything else | the same agent: router, tools, answer prompt v2, citation and grounding checks, outcome rules | same |

Both configs ran the same 29 cases (`evals/eval_set.jsonl`, all 10 scenarios of case section 9) through the real agent on
the running demo, through `POST /eval/runs`. Each question is stored like a user's question, so every case opens in the
query drill-down by its query id.

**Demo conditions, read the numbers with these in mind:**
- The demo has no embedding API, so vectors are offline word-hash vectors (`EMBEDDER=hashing`). This hurts config A most,
  because A has only the vector list and a cosine gate.
- Models: Groq free tier. Answers `openai/gpt-oss-120b`, planner `openai/gpt-oss-20b`, fallbacks `qwen/qwen3.8-27b` and
  `openai/gpt-oss-safeguard-20b`.
- The index also holds two unrelated uploads (`algoassignment-1`, 253 chunks, and an IITGN letter) next to the 9 demo
  documents. Both configs searched the same index.

## 2. Result (run 1, 27 Oct 17:04 to 17:13 IST, demo code `ecbe89d`)

Files: `eval_results_A.csv`, `eval_results_B.csv`, `eval_summary_A.json`, `eval_summary_B.json`, `eval_comparison.csv`
(copies in `eval_history/run1_*`). Run ids `eval-A-5676ce` and `eval-B-f8e997`. No query in this run hit the daily token limit (section 6).

| Measure | Config A | Config B | Better |
|---|---|---|---|
| Cases passed | 13 of 29 | **24 of 29** | B |
| Behaviour match (right outcome and reason) | 0.517 | **0.897** | B |
| Answer criteria (must and must-not words) | 0.448 | **0.897** | B |
| Route accuracy | 0.931 | **1.000** | B |
| hit@5 | 0.882 | **0.941** | B |
| recall@5 | 0.824 | **0.941** | B |
| MRR@5 | **0.804** | 0.776 | A |
| Citation validity | 1.000 | 1.000 | same |
| Grounding score | **1.000** | 0.984 | A |
| Latency p50 | **2,107 ms** | 2,761 ms | A |
| Latency p95 | **8,121 ms** | 8,989 ms | A |
| Tokens per query | **2,950** | 3,571 | A |
| Cost per priced query | **$0.000421** (29 of 29 priced) | $0.000458 (27 of 29 priced) | A |

Two B queries were answered by `qwen/qwen3.8-27b` after a per-minute limit, and that model has no price in the price
file, so B's cost is the mean of the 27 priced queries. The summary file shows B's cost as empty for that reason: one
unpriced query makes the total "price not set" instead of a low number (contract 11 section 4).

## 3. What changed and what it did

- **Quality went up a lot.** B passes 24 cases against 13. Behaviour match and answer criteria both rise from about 0.5
  to 0.9.
- **Why A fails.** 11 of A's 16 failures are "could not find" while the right chunk was in A's top 5 (hit@5 = 1). The
  cosine gate of 0.6 rejects them, because word-hash vectors give low cosine scores. B's cross-encoder scores relevance
  directly, so its gate keeps the right chunk. A also routed the CEO question to small talk (N01, query
  `01M5YJB7339VK6M0JGS8M1CBPE`), and in one case (B01) the planner chose DOCS where BOTH was right.
- **Recall.** BM25 finds exact ids and policy names that the vectors miss: recall@5 goes from 0.824 to 0.941.
- **MRR is a little lower in B** (0.776 against 0.804), because the TinyBERT reranker put the right chunk second or lower in
  five cases (B01, B02, M01, T02, X03).
- **Latency and cost.** B costs about 650 ms more at the median and 21 % more tokens per query, because it sends more
  evidence to the model. At $0.0005 a query, the cost difference is small.
- **Complexity.** B adds a BM25 index, the fusion step and a local reranker model (about 30 ms per chunk on the workstation
  CPU with MiniLM-L-12). All three run locally, with no extra API.

## 4. Failure cases (config B, run 1)

| Case | Query id | What happened | Cause | Done |
|---|---|---|---|---|
| X02 | `01M5YJGZZMNM3DE91FWM3EZ3EP` | "What does section 4.5 of the travel policy say?" gave "could not find" | the right chunk ranked first, but TinyBERT-L-2 scored it 0.007, under the gate 0.01 | reranker changed to MiniLM-L-12 (section 5) |
| F03 | `01M5YJQJ7AFWYBX0B9CMHQ76CF` | revenue by segment gave a tool error | the planner sent `metric: "revenue"`; `segment_breakdown` accepts only `"segment_revenue"` (ARGS_INVALID) | the agent now asks the planner once more with the tool's message |
| F02 | `01M5YJQ8G2XG5S82J49FG5WJPN` | "basic EPS FY2024-25" answered ₹4,567 | the tool itself returned ₹4,567; the report says ₹45.67. The model repeated the tool faithfully, so grounding passed | a scaling bug in the stored financial fact, reported to Sinngam and Myank on issue #25 |
| M01 | `01M5YJHHC9NF4E741RDFB10K8D` | "and for Delhi?" answered both versions correctly, then "The current rate is ₹1,800" | that claim's words "current rate" are not in the cited text, so the grounding check marked it unsupported (0.67 < 0.8): PARTIAL / UNSUPPORTED_CLAIMS | kept: the check is strict on purpose |
| F04 | `01M5YJQSFEPDVWPEX8SBBM7R1P` | answer correct, case failed on hit@5 = 0 | our eval set named `doc_key` `company-a-annual-report`; the real key is `company-a-annual-report-fy2024-25` | eval set fixed |

F02 shows a limit of the grounding check: it proves that the answer matches the evidence, not that the evidence is right.

## 5. Changes made from these results (on `arka/agent`, 27 Oct)

| Commit | Change | Measured reason |
|---|---|---|
| `627f506` | reranker default `ms-marco-MiniLM-L-12-v2` (setting `AGENT_RERANK_MODEL`); demo gate 0.1 | offline over the 284 indexed chunks and the 17 cases with expected evidence: expected chunk first in 11 (TinyBERT 9), MRR 0.776 (0.718), lowest top score of an answerable question 0.144 (0.003); unanswerable questions top out at 0.000 to 0.001, except the CEO question (0.703, the model then says there is no evidence) |
| `627f506` | one argument repair when a tool answers ARGS_INVALID | F03 |
| `627f506` | F04 `doc_key` corrected | F04 |
| `31c4620` | the planner's small talk stands only for real small talk | A's N01 |
| `85d460f` | while other models remain, one model gets at most 60 % of the time left | a slow primary used the whole deadline (Hemant, #25) |

## 6. Run 2: why it is not used for the comparison

Run 2 (`eval-A-92c4f1`, `eval-B-67d52c`, 17:24 to 17:33 IST, demo code `627f506` with MiniLM-L-12 and gate 0.1) ran
after run 1 and the live checks had used most of the Groq key's **daily** token limit: 200,000 tokens per model per day
for `gpt-oss-20b` and `gpt-oss-120b` (the 429 message said "Used 199010"). The planner hit that limit in 11 of A's
queries and 25 of B's, fell back to documents (ROUTE_FALLBACK, contract 06 AI-4), and the answers moved to
`qwen/qwen3.8-27b`. So run 2 measures the provider limit, not the configs: A passed 11 and B 17. Its files are kept in
`eval_history/run2_*`.

What run 2 does show: no query crashed. Every limit error became a recorded fallback with the provider's reason in the
plan stage, and the answers came from the next model. For a fair second run, use a fresh daily quota or a second key, and
run A and B within the same hour.

## 7. Extraction quality (Myank's part, `extraction_quality.csv`)

7 gold pages: text, table-heavy, scanned and handwriting. Character and word error rate 0.000 and numeric recall 1.000
on all 7; table cell accuracy 1.000 on the 4 pages with tables. The 4 OCR pages cost $0.003919 in total (1,328 to 1,338
input tokens each). The two handwriting pages are marked `stand_in = True` in the file, and the two scanned pages are
marked `needs_review = True` (they were approved in the review screen before indexing).

## 8. Recommendation

**Use config B.** It answers 24 of 29 cases correctly against 13, finds the right evidence more often (recall@5 0.941
against 0.824), and makes no routing mistakes. It costs about 0.65 s more at the median and 21 % more tokens per query,
which is small next to the quality gain. Keep the MiniLM-L-12 reranker with a gate near 0.1 (measured), and remeasure
the gate whenever the embedding model or the reranker changes. With a real embedding model, config A would improve, and
the comparison should be run again.

## 9. How to reproduce

- On the demo: Evaluation page, or `POST /api/eval/runs {"config_id": "A"}`, wait for DONE, then the same with `"B"`.
  One run at a time; about 5 minutes per run.
- Command line: `cd model && python -m agent.eval_cli --configs A B`.
- Each case's query id opens the drill-down: route and reason, every retrieval list with scores, tool calls with their
  SQL, the model's raw output, citations, grounding and the outcome.
