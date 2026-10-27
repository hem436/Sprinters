// Types for the service contracts. Source: output/design/05_api_contract.md,
// 10_extraction_pipeline.md (ExtractionReport), 11_observability_eval.md (outcomes, KPIs),
// 13_sql_tools.md (tools) and 14_financial_tables.md (tables, metric map).
// Field names match the JSON exactly. Do not rename them here.

export type Outcome = 'SUCCESS' | 'PARTIAL' | 'FAILED'

export type ReasonCode =
  | 'SYSTEM_ERROR'
  | 'LLM_ERROR'
  | 'OUTPUT_INVALID'
  | 'BLOCKED_SAFETY'
  | 'NO_EVIDENCE'
  | 'TOOL_FAILED'
  | 'UNGROUNDED_ANSWER'
  | 'UNSUPPORTED_CLAIMS'
  | 'OK'
  | 'OK_CONFLICT'

export type Confidence = 'HIGH' | 'MEDIUM' | 'LOW'
export type Route = 'DOCS' | 'SQL' | 'BOTH' | 'CONVERSATIONAL' | 'BLOCKED'
export type ConfigId = 'A' | 'B'

/** Money is a decimal string with up to 6 decimals, or null when no price is set. */
export type Money = string | null

export interface QueryFilters {
  category?: string
  doc_key?: string
  current_only?: boolean
}

export interface QueryRequest {
  question: string
  session_id: string
  filters?: QueryFilters
  config_id?: ConfigId
}

export interface DocumentCitation {
  id: string
  kind: 'document'
  title: string
  version: string
  page: number
  section?: string
  method: string
  url: string
}

export interface ToolCitation {
  id: string
  kind: 'tool'
  tool: string
  args: Record<string, unknown>
  row_count: number
}

export type Citation = DocumentCitation | ToolCitation

export interface ToolResult {
  id: string
  tool: string
  status: string
  summary?: string
  rows?: Record<string, unknown>[]
}

export interface Usage {
  tokens_in: number
  tokens_out: number
  cost_usd: Money
  estimated: boolean
}

export interface QueryResponse {
  query_id: string
  answer_markdown: string
  outcome: Outcome
  reason_code: ReasonCode
  confidence: Confidence
  route: Route
  citations: Citation[]
  tool_results: ToolResult[]
  conflict: boolean
  usage: Usage
  latency_ms: number
}

/** Events of POST /query/stream. */
export type StreamEvent =
  | { event: 'status'; data: { stage: string } }
  | { event: 'citations'; data: { citations: Citation[] } }
  | { event: 'token'; data: { text: string } }
  | { event: 'done'; data: QueryResponse }
  | { event: 'error'; data: ApiErrorBody['error'] }

export interface FeedbackRequest {
  query_id: string
  helpful: boolean
  comment?: string
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    fields?: { field: string; problem: string }[]
  }
}

// ---------- Dashboard (contract 11 section 9) ----------

export interface MetricsFilters {
  from?: string
  to?: string
  config_id?: ConfigId | ''
  route?: Route | ''
  outcome?: Outcome | ''
}

export interface LatencyStat {
  p50: number
  p95: number
}

export interface MetricsSummary {
  total_queries: number
  outcomes: Record<Outcome, number>
  outcome_over_time: ({ bucket: string } & Record<Outcome, number>)[]
  retrieval_success_rate: number
  hit_at_5: number | null
  grounding_rate: number
  citation_support: { valid: number; total: number }
  tool_success: { ok: number; total: number }
  safety_events: Record<string, number>
  latency_ms: { total: LatencyStat; retrieval: LatencyStat; tool: LatencyStat; llm: LatencyStat }
  usage: {
    tokens_in: number
    tokens_out: number
    total_cost_usd: Money
    cost_per_query_usd: Money
    cost_per_route: { route: Route; cost_usd: Money; queries: number }[]
    ingestion_cost_per_document: { document_id: string; title: string; cost_usd: Money }[]
  }
  feedback: { helpful: number; not_helpful: number }
  dropped_events: number
}

export interface QueryListRow {
  query_id: string
  ts: string
  question_masked: string
  route: Route
  outcome: Outcome
  reason_code: ReasonCode
  latency_ms: number
  cost_usd: Money
  feedback: 'HELPFUL' | 'NOT_HELPFUL' | null
}

export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface StageStatus {
  stage: string
  status: string
  latency_ms: number
  detail?: string
}

export interface RankedHit {
  rank: number
  chunk_id: string
  doc: string
  page: number
  score: number
  version?: string
  section?: string
}

export interface DrillDown {
  identity: { query_id: string; ts: string; session_id: string; app_version: string; config_id: ConfigId }
  question: { original_masked: string; normalized: string; route: Route; route_reason?: string }
  execution: StageStatus[]
  outcome: { outcome: Outcome; reason_code: ReasonCode }
  retrieval: { vector: RankedHit[]; bm25: RankedHit[]; fused: RankedHit[]; reranked: RankedHit[] }
  evidence_quality?: { relevant: boolean; top_score?: number; expected_match?: boolean | null }
  context_turns: { turn_index: number; role: 'user' | 'assistant'; chars: number; text_masked?: string }[]
  tool_calls: {
    tool: string
    args_sanitized: Record<string, unknown>
    status: string
    row_count?: number
    summary?: string
    latency_ms: number
  }[]
  generation: { model: string; prompt_version: string; validation: string; raw_output?: string }
  citations: { id: string; valid: boolean; reason?: string }[]
  grounding: { score: number | null; claims: { text: string; supported: boolean }[] }
  safety: { flags: string[]; pii_masked?: boolean; fallback?: boolean }
  performance: { retrieval_ms: number; tool_ms: number; llm_ms: number; total_ms: number }
  usage: {
    calls: { purpose: string; tokens_in: number; tokens_out: number; cached_tokens?: number }[]
    cost_usd: Money
    usage_source: string
  }
  feedback: { helpful: boolean; comment?: string } | null
  reviewer_comments?: string[]
  errors: { category: string; stage: string; retries: number; correlation_id: string }[]
}

// ---------- Evaluation (contracts 07 and 11 section 7) ----------

export interface EvalCaseResult {
  case_id: string
  scenario: string
  query_id: string
  route: Route
  expected_route: Route
  outcome: Outcome
  reason_code: ReasonCode
  behavior_match: 0 | 1
  hit_at_5: 0 | 1 | null
  grounding_score: number | null
  latency_ms: number
  cost_usd: Money
}

export interface EvalRun {
  run_id: string
  config_id: ConfigId
  status: 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED'
  started_at: string
  finished_at?: string
  cases_done: number
  cases_total: number
  summary?: Record<string, number | null>
  results?: EvalCaseResult[]
}

// ---------- Documents and review (contracts 10 and 14) ----------

export type DocumentStatus = 'QUEUED' | 'PROCESSING' | 'INDEXED' | 'PARTIAL_REVIEW' | 'FAILED'
export type PageStatus = 'INDEXED' | 'NEEDS_REVIEW' | 'APPROVED' | 'REJECTED'

export interface DocumentRow {
  document_id: string
  title: string
  doc_key: string
  category: string
  version: string
  effective_date: string
  status: DocumentStatus
  pages: number
  chunks: number
  ocr_cost_usd: Money
}

export interface ExtractionPage {
  page: number
  class: string
  method: string
  chars?: number
  tables?: number
  quality: number
  flags: string[]
  status: PageStatus
  ocr?: { model: string; input_tokens: number; output_tokens: number; latency_ms: number; cost_usd: Money }
}

export interface ExtractionReport {
  document_id: string
  status: DocumentStatus
  pages: ExtractionPage[]
  chunks: number
  ocr_cost_usd: Money
  duration_ms: number
}

export interface DocumentDetail extends DocumentRow {
  report: ExtractionReport
}

export interface PageDetail {
  page: number
  text: string
  class: string
  method: string
  quality: number
  flags: string[]
  status: PageStatus
  image_url: string
}

export interface Job {
  job_id: string
  document_id: string
  title: string
  stage: string
  done: number
  total: number
  status: 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED'
}

export interface UploadMetadata {
  title: string
  category: string
  version: string
  effective_date: string
  doc_key?: string
}

export interface FinTable {
  table_id: string
  document_id: string
  statement: 'PL' | 'BS' | 'CF' | 'SEGMENT' | 'OTHER'
  basis: string
  unit: string
  scale: number
  pages: number[]
  checks_passed: boolean
  checks: { name: string; passed: boolean; detail?: string }[]
  status: 'NEEDS_REVIEW' | 'APPROVED' | 'REJECTED'
}

export interface MetricMapRow {
  line_label: string
  metric: string
  proposed_by: 'DICTIONARY' | 'LLM'
  approved_by: string | null
  approved_on: string | null
}

export interface ToolInfo {
  name: string
  version: number
  source: string
  description: string
  argument_schema: Record<string, { type: string; required?: boolean; enum?: string[]; example?: unknown }>
  approved: boolean
  success_rate: number | null
}

export interface ToolTryResult {
  rows: Record<string, unknown>[]
  summary: string
  provenance: { tool: string; version: number; source: string; latency_ms: number; row_count: number }
}

export interface Health {
  status: 'ok' | 'degraded' | 'down'
  qdrant: boolean
  llm: boolean
  ocr_available: boolean
  reranker: boolean
  db: boolean
}

export type ReviewDecision = 'APPROVE' | 'REJECT'
