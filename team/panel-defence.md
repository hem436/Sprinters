# Panel defence: Enterprise Knowledge Assistant design

**Who answers:** Myank (P1 extraction and indexing), Hemant (P4 front end; also owns the repo and merges every branch), Arka (P2 agent, LangGraph, evaluation), Sinngam (P3 back end, SQL and facts tools, event store, cost). Each person practises their own groups and the "Everyone" group, and can give a short answer for their buddy's group (Myank with Hemant, Arka with Sinngam).

Made with the `defend-this` skill on `output/design/` (contracts 00 to 12), with hard questions from Codex
(`prompt/codex/20261027-120719-brainstorm.md`), each checked against the contracts. Each owner practises their own
part, and the "Everyone" questions. Say the answers in your own words; do not read them.

## 0. Gaps found (fix these or have the answer ready)

| # | Gap | Where | What we do |
|---|---|---|---|
| G1 | There is no way for an admin to connect a SQL source or add a table. Only one seeded `business.db` exists. | 02, 04 T1 to T4, 05 | **Designed now: contract 13** (tool registry, `GET /tools`, `POST /tools/{name}/try`). Defence in section 7. |
| G2 | The router rule forces SQL when a project id appears, even in a document question ("what does the policy say about P-104?"). Invalid planner JSON falls back to DOCS silently. | 04 R1 | **Fixed in contract 04 R1:** BOTH when the question also has document words; a fallback is recorded as `ROUTE_FALLBACK`. |
| G3 | Config A has no rerank step, so "top rerank score" in G1 fallback and "retrieval relevant" is undefined for A. | 04 G1, 11 s.6 | For config A use the top cosine score with its own threshold `obs.relevance_min_vector`. **Fixed in contract 04 G1 and 11 section 6.** |
| G4 | MRR is defined over the top 10, but the final list has 5. | 11 s.7 | Use MRR over the final top 5 (MRR@5), same list as hit@5. **Fixed in contract 11 section 7.** |
| G5 | The recorder drops a failed write, so "every query is recorded" is not guaranteed. | 11 s.3 | Count dropped writes and show the count on the dashboard. **Fixed in contract 11 section 3.** |
| G6 | The conflict rule sees only versions that reach the top 5. | 04 C1 | When a top chunk has a `doc_key` with other versions, also fetch the same section of the other versions. **Fixed in contract 04 C1.** |
| G7 | A confident but wrong OCR digit can pass the quality gate. | 10 X6, X7 | Rule: any **OCR page with a table** goes to review, whatever its score. Text-layer tables do not. **Fixed in contract 10 X7.** |
| G8 | `session_id` comes from the client, so one user could read another session's chat. | 01 | Accepted for the demo: case 4.2 puts identity out of scope. Say so. |
| G9 | The contracts say DRAFT. | all | Freeze them (v1.0) at the design review. G1 to G7 are already in the contracts; contract 15 traces every case requirement. |

## 1. The idea in two sentences

Employees ask questions and get a short answer with "document, page or section references and tool-result
provenance" (case section 3), or an honest "not found". Every query is recorded so the dashboard can "distinguish
execution success from AI-quality success" (case section 8).

## 2. What each API does

All endpoints are in contract 05. "Inside" names the rules from contracts 04, 10 and 11.

### Documents (Myank's logic; Sinngam's routes)

| Endpoint | Who calls it | What it does, in plain words | Inside |
|---|---|---|---|
| `POST /documents` | admin page | Uploads one file with its title, category, version and effective date. Returns at once with a job id; reading happens in the background. | X1 checks (type by first bytes, size, duplicate hash, metadata) → 202, or 422 / 409 with a code |
| `GET /jobs` | admin page, every 2 s | Shows each upload's progress, for example "OCR page 3 of 7". | single worker queue |
| `GET /documents` | admin page | Lists documents with status, pages, chunks and OCR cost. | `document` table |
| `GET /documents/{id}` | admin page | One document with its ExtractionReport: each page's class, method, quality and cost. | ExtractionReport |
| `GET /documents/{id}/pages/{n}` | admin page, citation links | The text we extracted from one page, with its class, quality and flags. | `page` table |
| `GET /documents/{id}/pages/{n}/image` | admin preview | A picture of the page, so a person can compare it with the extracted text. | pypdfium2 render |
| `POST /documents/{id}/pages/{n}/review` | admin | Approves or rejects a low-quality page. Approved pages become searchable. | X7; 409 ILLEGAL_MOVE if the page is not waiting for review |
| `POST /documents/{id}/reindex` | admin | Reads the document again (after a rule or threshold change). Same chunk ids, so nothing is duplicated. | delete old chunks, then X2 to X9 |
| `DELETE /documents/{id}` | admin | Removes the document's chunks and vectors; keeps the row for history. | status DELETED |

### Questions (Arka's logic; Sinngam's routes and tools)

| Endpoint | Who calls it | What it does | Inside |
|---|---|---|---|
| `POST /query` | chat, eval runner | Takes a question and returns the answer, citations, outcome, confidence, tokens and cost in one response. | S1 guard → M1 window → R1 route → H1 to H4 search or T1 to T4 tool → A1 to A4 answer → V1 to V3 checks → G1 fallback → outcome |
| `POST /query/stream` | chat | The same pipeline, but sends progress, then citations, then the answer word by word (Server-Sent Events), so the user waits about 1 s for the first sign of life. | same as `/query`, same prompt |
| `GET /tools` | admin page | Lists the approved data tools: name, version, which database, what it answers, its arguments, who approved it, and its success rate. | tool registry (contract 13) |
| `POST /tools/{name}/try` | admin page | Runs one approved tool with sample arguments, so the admin can see its rows and summary before users rely on it. Read-only. | same checks as a real call; 422 ARGS_INVALID, 504 TIMEOUT |
| `GET /health` | anyone, start-up check | Says whether Qdrant, the LLM, OCR, the reranker and the databases are reachable. | live checks; reports `model_not_found` clearly |

### Feedback, metrics and evaluation (Sinngam; evaluation runs are Arka's)

| Endpoint | Who calls it | What it does | Inside |
|---|---|---|---|
| `POST /feedback` | chat | Saves helpful or not helpful, with an optional comment, for one query. | `feedback` table; 409 if already given |
| `POST /queries/{id}/review` | reviewer | Adds a reviewer's comment to a query. | `feedback.reviewer_comment` |
| `GET /metrics/summary` | dashboard | All KPI tiles for a time range, config, route or outcome. | one SQL query per KPI on `observability.db` |
| `GET /queries` | dashboard | A list of queries with outcome, reason, time, cost and feedback. | `query_event` |
| `GET /queries/{id}` | dashboard drill-down | Everything about one query: stages, the four ranked lists, tool calls, citations, grounding, tokens, cost, errors. | all event tables, joined by `query_id` |
| `POST /eval/runs` | reviewer | Runs the test set with config A or B in the background. | runner calls `/query` per case, then scores |
| `GET /eval/runs`, `/eval/runs/{id}` | dashboard | Results of each run, and A against B. | `eval_run`, `eval_result` |

## 3. Walk-throughs (example values from our facts sheet)

**A. An admin uploads the scanned policy v1.0 (8 pages, all scanned).**

1. `POST /documents` with title "Travel and Expense Policy", version 1.0, effective 2025-04-01. The first bytes are
   `%PDF`, the size is under 50 MB, and the hash is new, so the response is 202 with `job_id`.
2. X3 sees almost no text layer and a full-page image on every page: class SCANNED for all 8.
3. X5 renders each page at 1600 px and calls Gemini vision. Page 6 returns the per diem table with ₹1,500,
   `illegible_count` 0: quality 1.0. Page 8 has a handwritten note in the margin with 9 of 60 words illegible:
   quality 0.85 minus 0.10 for medium confidence = 0.75.
4. Page 8 goes to NEEDS_REVIEW (under 0.85); the other 7 pages are chunked and searchable at once. Page 6 is an OCR
   page with a table, so with fix G7 it also waits for review.
5. The ExtractionReport shows OCR tokens and cost per page, and the dashboard shows the cost of this document.

**B. A user asks "Is project P-104 over its travel budget, and what does the policy say about overruns?"**

1. `POST /query`. S1 finds no blocked phrase. M1: this is the first turn.
2. R1: the rule sees `P-104` and "budget"; the question also has "policy", so the route is BOTH (fix G2).
3. Documents: vector top 20 and BM25 top 20, merged by RRF, reranked to 5. Top passage: policy v2.0, page 7,
   section 4.5 Overruns.
4. Tool: the planner picks `budget_status(project_id="P-104", fiscal_year="FY2026-27", category="TRAVEL")`.
   Pydantic checks that P-104 exists and the category is allowed. The read-only query returns budget ₹4,00,000
   and spent ₹4,35,500.
5. Answer JSON: two claims, cited `T1` and `E1`. V1: both ids are in this query's evidence. V2: "4,35,500" and
   "4,00,000" appear in T1's result. Outcome SUCCESS, reason OK.
6. The recorder writes one `query_event` row, 9 stage rows, the ranked lists, 2 LLM calls with tokens and cost,
   1 tool call and 2 citations.

## 4. Why this way (the decisions the panel will push on)

| Decision | Options we did not take | Trade-off | Ties to |
|---|---|---|---|
| Approved SQL templates | text-to-SQL; a generic SQL agent | safe, testable, explainable; fewer questions answerable | case FR-07 "approved SQL or API tool", section 6 Tools |
| Page-by-page extraction | per document; one layout model for all pages | exact page citations, OCR only where needed; more records | FR-02, section 3 "page or section references" |
| Hybrid search + RRF + rerank | vector only (config A); weighted score sum | finds exact IDs; more latency, which we measure | FR-04, FR-05, section 10 |
| Rules in code for live grounding | an LLM judge on every query | no extra cost or delay; weaker on paraphrase, so the judge runs on the test set | section 8 grounding rate, NFR cost |
| SQLite event store | Logfire only; OpenTelemetry stack | history and simple SQL for the dashboard; one writer | FR-12, section 8.2 |
| Quality gate with human review | index everything; reject low-quality files | no misread number in answers; a manual step | section 3 "approved documents" |

## 5. What breaks it

| Situation | Effect | Covered by a planned test? |
|---|---|---|
| Score exactly 0.85 | rule says "under 0.85" goes to review, so 0.85 is searchable | add `test_quality_at_threshold` |
| Same file uploaded twice | 409 DUPLICATE_DOCUMENT | yes, `test_duplicate_is_409` |
| Same content, new file name | same hash, so still 409 | yes (hash, not name) |
| Two admins approve the same page at once | second gets 409 ILLEGAL_MOVE | add a test |
| Gemini quota ends during OCR | failed pages go to review, document PARTIAL_REVIEW | yes, stub test |
| Groq retires the model | `/health` shows `model_not_found`; queries FAILED `LLM_ERROR` after the fallback model | partly: no test for the health check |
| Portkey cache returns an old answer | `cache_hit` true, cost 0; looks fine even if the model is down | not covered; say so |
| Project id in a policy question | routed BOTH after fix G2 | add `test_doc_question_with_project_id` |
| Question no tool covers ("average claim per city") | must answer "not found in the data", not a near answer | add a case; gap in contract 04 |
| A document with an injected instruction | ignored, safety flag | yes, `test_injection_ignored` |
| Recorder database locked | answer still returns; write dropped and counted (fix G5) | yes, `test_recorder_never_raises` |

## 6. Panel questions and short answers

### Everyone

**E1. Explain your system in 30 seconds.** We read every file page by page, so each answer can cite an exact page.
A question goes to document search, approved SQL tools, or both, and the answer is checked in code before the user
sees it. Every query is recorded with its outcome, tokens and cost, and we measure accuracy on a fixed test set.

**E2. Why is an HTTP 200 not a success?** A 200 only says the code ran. Our outcome rules mark a 200 as FAILED when
no citation points at real evidence, and as PARTIAL when some claims are not supported.

**E3. Why did you not use a managed RAG service?** The case asks us to show each stage, the routing and the
evaluation ourselves, and a managed service hides those stages. We have not measured a managed service, so we do
not claim ours is better on cost or quality.

**E4. What if the load is 10 times higher?** We have not tested it, so we do not claim it. The first limits are
the single ingest worker, the in-process BM25 index, SQLite for events with one writer, and the provider rate
limits. The path is more workers, a search engine for BM25 such as OpenSearch, and Postgres for events.

### SQL and the data tool (Sinngam; routing questions S6 and S14 are Arka's; everyone knows S1)

**S1. How does an admin connect a SQL database?** In our design the admin does not connect databases from the
screen, by choice. A developer adds the connection string to the configuration, using a read-only database user,
and adds approved queries to the tool registry with argument checks and tests. Then the router can use them. The
case puts "real-time ingestion from numerous enterprise platforms" out of scope (4.2), and a database the model can
query freely is a security risk.

**S2. Then how would the client add a new table?** A new table is not visible to the model by itself. A developer
writes an approved query for it, with a name, a description the router reads, typed arguments and a test, and the
registry makes it available after review. The business meaning (for example, which claim statuses count as spend)
lives in that query, not in the model's guess.

**S3. Could you add a "connect database" screen later?** Yes: an admin form that stores a connection string as a
secret, tests it with a read-only user, and lists the tables. But it would still only enable the approved queries
for that source, so a person must approve each new query. We would also need real login and roles first.

**S4. Can a user make the SQL tool delete data?** No. The model never writes SQL; it only fills arguments that
Pydantic checks, the queries are fixed text with parameters, and the connection is opened read-only with a time
limit. Table and column names are fixed in the template, never taken from the question.

**S5. Why not text-to-SQL? It answers more questions.** It does, but then every generated query needs a parser
check, a table allow-list and a test of its meaning, and a wrong but valid query returns a confident wrong number.
We chose 4 safe templates and accept fewer answerable questions; text-to-SQL with a SELECT-only check is our next step.

**S6. How does the router decide between documents and SQL?** A rule runs first: an ID like `P-104` or words like
"total" or "spent" mean the data is needed. Then the LLM planner returns JSON with the route and the tool arguments.
If the question also asks about policy, the route is BOTH, and our test set checks the route of every case.

### Extraction (Myank; Hemant backs up)

**X1. How do you handle a PDF that is half text and half scanned?** We decide per page, not per document. Text
pages use the text layer, and only the scanned pages go to the vision model, so we pay for OCR only where needed.

**X2. How accurate is your OCR on handwriting?** We measure it: character error rate against pages we typed by
hand. Two notes are a small sample, so we report the number with that limit, and every low-quality page waits for
a person before it is searchable.

**X3. What if the OCR reads a 6 as an 8 with high confidence?** The score cannot catch that, so we do not trust
it for numbers. Every OCR page with a table goes to human review, and our extraction check measures numeric recall
on gold pages.

**X4. Why Gemini and not Tesseract?** Tesseract is poor on handwriting and on tables, and needs system packages.
Gemini reads both and returns JSON; the cost is a network call per page and data leaving the machine, so we use
synthetic and public documents only.

**X5. How do you keep financial tables correct?** A table becomes one Markdown chunk with its caption and unit, and
numbers stay exactly as printed. A chunk never cuts a table, and if a table is too long, each piece repeats the
header row.

### Retrieval and answers (Arka; Sinngam backs up)

**R1. Why both BM25 and vectors?** Vectors find meaning but miss exact IDs like `POL-HR-014`; BM25 finds exact words
but misses paraphrases. We merge them by rank with RRF, so their different score scales do not matter.

**R2. What happens when two policy versions disagree?** The answer shows both values with their versions and
effective dates and says which is current. We also fetch the same section of other versions when one version
reaches the top 5, so a conflict is not missed.

**R3. How do follow-up questions work?** We send at most the last 3 turns, each cut to 600 characters, and the
planner rewrites the follow-up into a full question. The drill-down shows which turns were used.

### Observability and evaluation (O1 and O3 Arka; O2 Sinngam)

**O1. How do you measure retrieval accuracy?** On a fixed test set of about 25 questions where we know the right
document and page: hit@5, recall@5 and MRR@5. On live questions we have no answer key, so we show the top score
only as a signal.

**O2. How is cost calculated?** Tokens come from the provider's usage numbers on each call, multiplied by a price
table that records its source and date. If the provider gives no counts we estimate and label it, and a model
without a price shows "price not set", never zero.

**O3. Did hybrid search actually help?** We do not know until the A and B runs. We report whatever we find,
including the extra latency and tokens, with three failure cases.

### Front end (Hemant; Myank backs up)

**F1. Why React and not Streamlit?** The case allows either; we chose React because our existing app already uses
it and the dashboard needs a drill-down page per query. It costs more front-end work.

**F2. What does a user see when there is no answer?** A fixed sentence, "I could not find this in the approved
documents or data", plus the closest sources if any, and a LOW confidence badge.

## 7. The SQL part, end to end (contract 13; Sinngam)

**In one breath:** the model never writes SQL. It picks one of 6 approved tools and fills its arguments; code checks
them, runs fixed SQL on a read-only connection, does all the maths in SQL, and the answer cites the result as `T1`.

### The schema we work with (`business.db`, tested in SQLite)

| Table | Key and main columns | Pairs with which document |
|---|---|---|
| `department` | `D-ENG`; name, cost centre | all |
| `employee` | `E1042`; department, grade G1 to G6, location, join date, status | onboarding FAQ, grade entitlements |
| `project` | `P-104`; name, department, status, dates | exact-ID questions |
| `budget` | project + fiscal year (`FY2026-27`) + category; amount in paise | travel policy, overrun rule |
| `expense_claim` | `EXP-20871`; project, employee, category, city, date, fiscal year, amount in paise, status, policy version | travel and expense policy |
| `it_asset` | `LT-0457`; type, employee, department, encrypted 0 or 1, last patch date, OS | IT security SOP, `POL-HR-014` |

Two views hold the business meaning once: `v_spend` = claims APPROVED or PAID; `v_budget_status` = budget against
that spend. People are codes only; there are no names, phones or emails anywhere.

### The six tools

| Tool | Answers |
|---|---|
| `project_info` | who owns a project, its status and dates |
| `budget_status` | budget, spent, remaining, % used |
| `spend_summary` | total spend grouped by project, department, category or city |
| `claims_list` | up to 20 claims, filtered and sorted |
| `asset_compliance` | assets, not encrypted, patch overdue, per department |
| `headcount` | counts of staff, never a list of people |

### Walk-through: "Is P-104 over its travel budget?"

1. Router R1 sees `P-104` and "budget", no policy words: route SQL. The planner returns
   `budget_status(project_id="P-104", fiscal_year="FY2026-27", category="TRAVEL")`.
2. Pydantic checks the arguments: P-104 exists, the year has the right form, TRAVEL is an allowed category.
3. Code opens `business.db` read-only and runs the fixed query on `v_budget_status`, with the three values bound
   as parameters.
4. The row: budget 4,00,00,000 paise, spent 4,35,50,000 paise. Python writes the summary: "budget ₹4,00,000, spent
   ₹4,35,500, over by ₹35,500 (108.9 % used)". We ran this query on test data and got exactly these numbers.
5. The LLM writes the answer and cites `T1`; the grounding check finds ₹4,35,500 in T1's text. Outcome SUCCESS.

### More SQL questions

**S7. How does the planner know your schema?** It does not see the schema. It sees only each tool's name, a
one-sentence description and the argument types. That keeps the prompt small and the table names private.

**S8. What exactly counts as "spent"?** Claims that are APPROVED or PAID. That rule is in one view, `v_spend`, so
every tool and every test uses the same meaning; a submitted or rejected claim never counts.

**S9. Why store money as integer paise?** SQLite has no exact decimal type, and a sum over decimal-looking values
comes back as a float. Integer paise sum exactly, and Python shows them as `Decimal` rupees.

**S10. Why does the LLM not calculate the overspend itself?** Models make arithmetic mistakes, and a wrong number in
a finance answer is the worst error. SQL and Python compute every number; the model only quotes them, and the
grounding check confirms each number appears in the tool result.

**S11. What if the query returns nothing?** That is an answer, not an error: status EMPTY, and the user sees "there
are no matching claims", with the tool cited. A timeout or a database error is different: the user sees that the
data is not available now, and the outcome is PARTIAL.

**S12. What if the organisers give you their own dataset?** We load it into the same SQLite file with a loader that
checks types and keys, then write approved tools for its tables. The registry, the checks and the read-only
connection do not change.

**S13. How would this work on a real bank database?** We change the connection string to PostgreSQL with a role that
can only SELECT from the views the tools use, and set a statement timeout. The tool files stay the same because they
use standard SQL with named parameters.

**S14. Two tools could answer the same question. Which one runs?** The planner picks one from the descriptions, and
we record the choice. Our test set checks the tool name and arguments for every data question, so a wrong choice
shows up as a failed case.

**S15. A user types `P-104; DROP TABLE project`. What happens?** The argument check rejects it, because a project id
must match `P-` and three digits and must exist, so no SQL runs. Even if it got through, it would be a bound value,
not SQL text, and the connection cannot write.

**S16. Can a user find out what one employee claimed?** Only by employee code, never by name, because names are not
in the database. `headcount` returns counts only. With real data we would add row-level access by role, which needs
the real login that case 4.2 puts out of scope.

## 8. Financial reports and their tables (contract 14; Myank extracts, Sinngam's tools answer)

**In one breath:** every financial table is stored twice. As a Markdown chunk, it is found and cited by search; as one
row per number in `fin_fact`, it gives exact values to four approved tools. The model never adds or compares numbers.

### Walk-through: "Compare Company A's revenue in FY2025 and FY2024, and say why it grew"

1. Route R1b: "compare", a metric and two periods give SQL; "why" adds DOCS, so the route is BOTH.
2. `metric_compare(metric="revenue", company="Company A", periods=["FY2023-24","FY2024-25"], basis="CONSOLIDATED")`.
3. The view `v_fact_current` takes only approved tables. For FY2023-24 there are two values: ₹10,000 crore in the
   FY2023-24 report and ₹10,050 crore in the FY2024-25 report. The newest report wins, so 10,050, flagged restated.
4. FY2024-25 is ₹11,256 crore. SQL computes growth: (11,256 − 10,050) ÷ 10,050 = 12.0 %. The standalone ₹9,000 crore
   row is never used, because the basis is CONSOLIDATED. We ran this on test rows and got exactly these values.
5. Text search finds the management discussion paragraph about the growth. The answer cites T1 (p.52, P&L row 3)
   for the numbers, notes the restatement, and cites the text page for the reason.

(Company A and its numbers are illustrative test data.)

### Questions

**T1. Why not let the model read the numbers from the table chunks?** It would have to pick the right column, the
right basis and the right scale from several chunks, then do the maths, and each step can go wrong silently. With
facts in SQL, each number is chosen by fixed rules, computed exactly and cited to a page and row.

**T2. How do you handle "₹ in crore" in one report and "in million" in another?** We read the unit line of every table
and store each value as an integer in rupees. So the two reports compare directly, and the tool refuses to compare
an amount with a percentage.

**T3. Standalone and consolidated figures are both in the report. How do you not mix them?** Each table gets a basis
from its title or section, and every tool filters on it, CONSOLIDATED by default. A test checks that a consolidated
comparison never returns a standalone row.

**T4. The same year's revenue differs between two reports. Which is right?** Both are stored. We answer with the
newest report, because companies restate earlier figures, and the answer says it was restated and shows the old value.

**T5. Labels differ between companies: "Revenue from operations" against "Total income from operations".** A dictionary
maps known labels to about 20 standard metrics. For an unknown label the LLM may propose a mapping, but a person
approves it; until then that row is stored but never used in a comparison.

**T6. How do you know a table was read correctly?** Components must add up to the total row, within the printed
precision, and the same number in two reports must agree or be marked restated. A failed check sends the table to
review beside the page image; we also measure cell accuracy and numeric recall on hand-typed gold tables.

**T7. What about a table that runs over two pages, or has merged headers?** If the next page starts with the same
header, or with no header and the same column count, we join them. Merged headers and tables without ruling lines go
to the vision model, which returns the table as JSON; then the same checks apply.

**T8. How are brackets and dashes handled?** `(1,234.50)` is −1,234.50, `1,23,456` is Indian grouping, and a dash or
"nil" is zero. We keep the printed text too, so the citation shows exactly what the page says.

**T9. What if a metric or year is not in any report?** The tool returns EMPTY and the answer says "not found in the
reports". It never estimates from nearby years.

**T10. What does it cost?** About one more iteration of extraction work, plus the review of new label mappings. If time
is short we build facts only for P&L and segment tables; other tables still answer through cited search.

## 9. Self-check before the panel (answer without help)

**Myank:** Why is FY2023-24 revenue taken from the newer report? Why is a page with a score of exactly 0.85
searchable, but an OCR page with a table is not? What happens to the good pages when one page fails OCR? Why do chunks
never cross a page?

**Hemant:** In which order do you merge the four branches, and why? Which endpoint gives the drill-down page its data? What do you show when the cost is "price not set"? How
does the admin approve a page and a table? How do the chat filters reach the search?

**Arka:** Which route does "what does the policy say about P-104" take, and why? Why is MRR computed on 5 results?
Which outcome does a 200 with zero valid citations get? How do you find a conflicting version that is not in the top 5?

**Sinngam:** Why is "spent" defined in a view and not in each tool? What stops the model from running its own SQL? How
is a Portkey cache hit counted in cost? What does the dashboard show when the recorder cannot write?
