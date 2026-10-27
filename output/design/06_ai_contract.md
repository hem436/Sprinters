<!-- Contract 06. Owner: P2 (P1 for OCR and embeddings). Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 06 AI components contract

Version: 1.0 · Status: DRAFT · Owner: P2, with P1 for OCR and embeddings · Case section(s): 6 (Model, Safety), 11

No model is trained or fine-tuned (case 4.2). Every AI call has a fixed input, a checked output, a timeout, a
fallback and a usage record (contract 11).

| Id | Purpose | Model (config key) | Input | Output (checked) | Timeout | Fallback | Owner |
|---|---|---|---|---|---|---|---|
| AI-1 | OCR of a page | Gemini Flash vision (`ocr.model`) | page image, prompt `ocr-v1` | JSON of contract 10 section 7 (schema-checked) | 60 s, 3 tries | page OCR_FAILED → review; Tesseract for printed pages (MAY) | P1 |
| AI-2 | Embeddings | Gemini embedding (existing; local sentence-transformers fallback) | `index_text` of a chunk; the query | vector of the collection's size | 20 s | local model; a dimension mismatch stops ingest with an error | P1 |
| AI-3 | Rerank | FlashRank cross-encoder, local ONNX | query + 20 passages | 20 scores | 5 s | fused order (existing behaviour) | P2 |
| AI-4 | Plan and route | answer LLM via Portkey (`llm.route_model`) | question + M1 window, prompt `route-v1` | JSON `{route, standalone_query, tool, tool_args}` | 10 s | route DOCS with the raw question | P2 |
| AI-5 | Answer | Portkey → Groq `openai/gpt-oss-120b`, fallback `openai/gpt-oss-20b` (the saved Portkey config decides; see the repo's CLAUDE.md) | evidence tags + tool results + question, prompt `answer-v1` | JSON of rule A2 (schema-checked, 1 repair) | 30 s | fixed G1 text; outcome FAILED LLM_ERROR | P2 |
| AI-6 | Judge (eval only) | separate judge key (`JUDGE_GROQ`) | RAGAS faithfulness and answer correctness | scores 0 to 1 | per RAGAS | case marked `judge_failed`, other measures still count | P3 |

## Prompt versions

Prompts live in `app/prompts/*.txt` with a version in the file name (`answer-v1.txt`). The version goes into every
`llm_call` row, so a regression run can show which prompt produced which result.

## Guardrails around the models

- Evidence and OCR text are data (rules A1, S2, prompt rule 4 of AI-1).
- The answer model never writes SQL and never calls a tool by itself; it only fills arguments that Pydantic checks (T1, T2).
- Only synthetic or public documents and IDs go to hosted models; the question is PII-masked first (S3).
- Model names change at the provider without notice (this happened to the existing repo). `/health` checks the
  answer model at start-up, and `model_not_found` is reported as such, not as a bad key.
