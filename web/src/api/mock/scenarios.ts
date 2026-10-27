import type {
  Citation,
  ConfigId,
  Confidence,
  DrillDown,
  Outcome,
  QueryResponse,
  RankedHit,
  ReasonCode,
  Route,
  StageStatus,
  ToolResult,
} from '../types'

// Query scenarios for mock mode. They follow the worked examples of contract 04 and the
// test scenarios of case section 9. Each scenario builds a QueryResponse and its drill-down.

export const FALLBACK_TEXT = 'I could not find this in the approved documents or data.'

export interface ScenarioInput {
  queryId: string
  ts: string
  sessionId: string
  configId: ConfigId
  question: string
  priorTurns: { role: 'user' | 'assistant'; text: string }[]
  /** 0..1, used to vary latency and tokens in the seeded history. */
  jitter: number
}

export interface ScenarioResult {
  response: QueryResponse
  drill: DrillDown
}

interface Spec {
  key: string
  scenario: string
  match: (q: string) => boolean
  route: Route
  normalized: (q: string, prior: ScenarioInput['priorTurns']) => string
  answer: string
  outcome: Outcome
  reason: ReasonCode
  citations: Citation[]
  toolResults?: ToolResult[]
  toolCalls?: DrillDown['tool_calls']
  conflict?: boolean
  hits?: RankedHit[]
  claims?: { text: string; supported: boolean }[]
  safety?: string[]
  /** Base latency in ms for retrieval, tool and llm. */
  ms: [number, number, number]
  tokens: [number, number]
  stageOverrides?: Partial<Record<string, string>>
  errors?: DrillDown['errors']
}

const travelV2: Citation = {
  id: 'E1',
  kind: 'document',
  title: 'Travel and Expense Policy',
  version: '2.0',
  page: 7,
  section: '4.2 Per diem',
  method: 'text+tables',
  url: '/admin/documents/doc_7f3a/pages/7',
}
const travelV1: Citation = {
  id: 'E2',
  kind: 'document',
  title: 'Travel and Expense Policy',
  version: '1.0',
  page: 6,
  section: '4.2 Per diem',
  method: 'ocr',
  url: '/admin/documents/doc_19c0/pages/6',
}

const hit = (rank: number, chunk_id: string, doc: string, page: number, score: number, version?: string): RankedHit => ({
  rank,
  chunk_id,
  doc,
  page,
  score,
  version,
})

const perDiemHits = [
  hit(1, 'c_ab12', 'travel-policy', 7, 0.81, '2.0'),
  hit(2, 'c_19f0', 'travel-policy', 6, 0.77, '1.0'),
  hit(3, 'c_ab13', 'travel-policy', 8, 0.52, '2.0'),
  hit(4, 'c_0c41', 'onboarding-faq', 3, 0.31),
]

const SPECS: Spec[] = [
  {
    key: 'injection_question',
    scenario: 'Embedded prompt injection (question)',
    match: (q) => /ignore (all |previous |prior )?instructions|system prompt|you are now/i.test(q),
    route: 'BLOCKED',
    normalized: (q) => q,
    answer: 'I cannot help with that request. I answer questions from the approved company documents and data.',
    outcome: 'PARTIAL',
    reason: 'BLOCKED_SAFETY',
    citations: [],
    safety: ['GUARD_BLOCKED', 'PROMPT_INJECTION'],
    ms: [0, 0, 0],
    tokens: [0, 0],
    stageOverrides: { guard: 'BLOCKED', retrieve_vector: 'SKIPPED', rerank: 'SKIPPED', answer: 'SKIPPED' },
  },
  {
    key: 'combined',
    scenario: 'Combined question',
    match: (q) => /p-104/i.test(q) && /(policy|overrun|rule|procedure)/i.test(q),
    route: 'BOTH',
    normalized: () => 'Is project P-104 over its FY2026-27 travel budget, and what does the policy say about budget overruns?',
    answer:
      'Yes. P-104 has spent ₹4,35,500 against a travel budget of ₹4,00,000 in FY2026-27, so it is over by ₹35,500 (108.9 % used) [T1]. ' +
      'The policy says that spend above 100 % of a category budget needs written approval from the department head before new claims are paid [E1].',
    outcome: 'SUCCESS',
    reason: 'OK',
    citations: [
      { ...travelV2, section: '6.1 Budget overruns', page: 11, url: '/admin/documents/doc_7f3a/pages/11' },
      { id: 'T1', kind: 'tool', tool: 'budget_status', args: { project_id: 'P-104', fiscal_year: 'FY2026-27', category: 'TRAVEL' }, row_count: 1 },
    ],
    toolResults: [
      {
        id: 'T1',
        tool: 'budget_status',
        status: 'OK',
        summary: 'P-104 TRAVEL FY2026-27: budget ₹4,00,000, spent ₹4,35,500, over by ₹35,500 (108.9 % used)',
        rows: [{ project_id: 'P-104', category: 'TRAVEL', budget: '₹4,00,000', spent: '₹4,35,500', remaining: '−₹35,500', pct_used: 108.9 }],
      },
    ],
    toolCalls: [
      {
        tool: 'budget_status',
        args_sanitized: { project_id: 'P-104', fiscal_year: 'FY2026-27', category: 'TRAVEL' },
        status: 'OK',
        row_count: 1,
        summary: 'budget ₹4,00,000, spent ₹4,35,500, 108.9 % used',
        latency_ms: 42,
      },
    ],
    hits: [hit(1, 'c_ab40', 'travel-policy', 11, 0.84, '2.0'), hit(2, 'c_ab41', 'travel-policy', 12, 0.58, '2.0'), hit(3, 'c_2d10', 'finance-sop', 4, 0.44)],
    claims: [
      { text: 'P-104 has spent ₹4,35,500 against a travel budget of ₹4,00,000', supported: true },
      { text: 'over by ₹35,500 (108.9 % used)', supported: true },
      { text: 'spend above 100 % needs written approval from the department head', supported: true },
    ],
    ms: [610, 42, 2300],
    tokens: [2890, 120],
  },
  {
    key: 'tool_args_invalid',
    scenario: 'Tool failure',
    match: (q) => /p-999/i.test(q),
    route: 'SQL',
    normalized: (q) => q,
    answer: 'The project id P-999 was not recognised in the approved data, so I could not run the spend lookup. Please check the project id.',
    outcome: 'PARTIAL',
    reason: 'TOOL_FAILED',
    citations: [],
    toolCalls: [
      { tool: 'spend_summary', args_sanitized: { group_by: 'category', project_id: 'P-999' }, status: 'ARGS_INVALID', summary: 'project_id P-999 does not exist', latency_ms: 3 },
    ],
    ms: [0, 3, 900],
    tokens: [620, 48],
    stageOverrides: { retrieve_vector: 'SKIPPED', rerank: 'SKIPPED', tool: 'ARGS_INVALID' },
  },
  {
    key: 'tool_timeout',
    scenario: 'Tool failure',
    match: (q) => /(headcount|how many).*(staff|employees|people)/i.test(q),
    route: 'SQL',
    normalized: (q) => q,
    answer: 'The headcount data is not available now. The lookup did not finish in time. Please try again later.',
    outcome: 'PARTIAL',
    reason: 'TOOL_FAILED',
    citations: [],
    toolCalls: [{ tool: 'headcount', args_sanitized: { location: 'Mumbai', grade: 'G4' }, status: 'TIMEOUT', latency_ms: 2000 }],
    ms: [0, 2000, 850],
    tokens: [540, 40],
    stageOverrides: { retrieve_vector: 'SKIPPED', rerank: 'SKIPPED', tool: 'TIMEOUT' },
    errors: [{ category: 'ToolTimeout', stage: 'tool', retries: 0, correlation_id: '' }],
  },
  {
    key: 'sql',
    scenario: 'Structured-data question',
    match: (q) => /(p-\d+|exp-\d+)/i.test(q) || /(total|spent|spend|how much)/i.test(q),
    route: 'SQL',
    normalized: () => 'What is the total travel spend of project P-104 in FY2026-27?',
    answer: 'The total travel spend of P-104 in FY2026-27 is ₹4,35,500 across 37 approved claims [T1].',
    outcome: 'SUCCESS',
    reason: 'OK',
    citations: [
      {
        id: 'T1',
        kind: 'tool',
        tool: 'spend_summary',
        args: { group_by: 'category', project_id: 'P-104', category: 'TRAVEL', fiscal_year: 'FY2026-27' },
        row_count: 1,
      },
    ],
    toolResults: [
      {
        id: 'T1',
        tool: 'spend_summary',
        status: 'OK',
        summary: 'P-104 TRAVEL FY2026-27: ₹4,35,500 in 37 claims',
        rows: [{ group: 'TRAVEL', total: '₹4,35,500', claims: 37 }],
      },
    ],
    toolCalls: [
      {
        tool: 'spend_summary',
        args_sanitized: { group_by: 'category', project_id: 'P-104', category: 'TRAVEL', fiscal_year: 'FY2026-27' },
        status: 'OK',
        row_count: 1,
        summary: '₹4,35,500 in 37 claims',
        latency_ms: 38,
      },
    ],
    claims: [{ text: 'total travel spend of P-104 in FY2026-27 is ₹4,35,500 across 37 approved claims', supported: true }],
    ms: [0, 38, 1400],
    tokens: [1120, 64],
    stageOverrides: { retrieve_vector: 'SKIPPED', rerank: 'SKIPPED' },
  },
  {
    key: 'exact_id',
    scenario: 'Exact ID or acronym',
    match: (q) => /pol-[a-z]+-\d+/i.test(q),
    route: 'DOCS',
    normalized: (q) => q,
    answer:
      'POL-HR-014 says every company laptop must have full-disk encryption turned on and must get security patches within 30 days of release [E1]. ' +
      'A laptop that misses a patch for more than 30 days is blocked from the network until IT updates it [E1].',
    outcome: 'SUCCESS',
    reason: 'OK',
    citations: [
      { id: 'E1', kind: 'document', title: 'IT Security SOP', version: '3.1', page: 4, section: 'POL-HR-014 Laptops', method: 'text', url: '/admin/documents/doc_51aa/pages/4' },
    ],
    hits: [hit(1, 'c_5101', 'it-security-sop', 4, 0.92, '3.1'), hit(2, 'c_5102', 'it-security-sop', 5, 0.61, '3.1'), hit(3, 'c_0c41', 'onboarding-faq', 3, 0.22)],
    claims: [
      { text: 'every company laptop must have full-disk encryption', supported: true },
      { text: 'security patches within 30 days of release', supported: true },
      { text: 'blocked from the network until IT updates it', supported: true },
    ],
    ms: [540, 0, 1900],
    tokens: [2210, 88],
  },
  {
    key: 'conflict_followup',
    scenario: 'Multi-turn follow-up',
    match: (q) => /^\s*(and|what about|how about)\b/i.test(q),
    route: 'DOCS',
    normalized: (q, prior) => {
      const city = q.replace(/^\s*(and|what about|how about)\s*(for|in)?\s*/i, '').replace(/[?.!]+$/, '').trim() || 'Delhi'
      const topic = prior.some((t) => /per diem|meal|allowance/i.test(t.text)) ? 'daily meal allowance (per diem)' : 'policy rule'
      return `What is the ${topic} in ${city}?`
    },
    answer:
      'The daily meal allowance in Delhi is ₹1,800 under policy v2.0 (effective 1 Apr 2026) [E1]. Version 1.0 said ₹1,500 for all metro cities [E2]. Version 2.0 is the current version.',
    outcome: 'SUCCESS',
    reason: 'OK_CONFLICT',
    citations: [travelV2, travelV1],
    conflict: true,
    hits: perDiemHits,
    claims: [
      { text: 'daily meal allowance in Delhi is ₹1,800 under policy v2.0', supported: true },
      { text: 'Version 1.0 said ₹1,500 for all metro cities', supported: true },
    ],
    ms: [590, 0, 2050],
    tokens: [2380, 92],
  },
  {
    key: 'conflict',
    scenario: 'Conflicting documents',
    match: (q) => /(per diem|meal allowance|daily allowance)/i.test(q),
    route: 'DOCS',
    normalized: () => 'What is the daily meal allowance (per diem) in Mumbai?',
    answer:
      'The daily meal allowance in Mumbai is ₹2,000 under policy v2.0 (effective 1 Apr 2026) [E1]. Version 1.0 said ₹1,500 [E2]. Version 2.0 is the current version.',
    outcome: 'SUCCESS',
    reason: 'OK_CONFLICT',
    citations: [travelV2, travelV1],
    conflict: true,
    hits: perDiemHits,
    claims: [
      { text: 'The daily meal allowance in Mumbai is ₹2,000 under policy v2.0', supported: true },
      { text: 'Version 1.0 said ₹1,500', supported: true },
    ],
    ms: [640, 0, 2100],
    tokens: [2410, 96],
  },
  {
    key: 'injection_doc',
    scenario: 'Embedded prompt injection (document)',
    match: (q) => /vendor/i.test(q),
    route: 'DOCS',
    normalized: (q) => q,
    answer:
      'A new vendor needs two approvals: the department head and the procurement team [E1]. Procurement checks the tax registration and bank details before the first purchase order [E1].',
    outcome: 'SUCCESS',
    reason: 'OK',
    citations: [
      { id: 'E1', kind: 'document', title: 'Vendor Onboarding Note', version: '1.0', page: 2, section: '2 Approvals', method: 'ocr', url: '/admin/documents/doc_88d2/pages/2' },
    ],
    hits: [hit(1, 'c_8801', 'vendor-note', 2, 0.79, '1.0'), hit(2, 'c_8802', 'vendor-note', 3, 0.55, '1.0')],
    claims: [
      { text: 'A new vendor needs two approvals', supported: true },
      { text: 'Procurement checks the tax registration and bank details', supported: true },
    ],
    safety: ['INJECTION_SUSPECT_CHUNK_USED'],
    ms: [520, 0, 1850],
    tokens: [1980, 81],
  },
  {
    key: 'direct',
    scenario: 'Direct factual question',
    match: (q) => /(leave|holiday|onboarding|laptop|notice period|probation)/i.test(q),
    route: 'DOCS',
    normalized: (q) => q,
    answer: 'A full-time employee gets 24 days of paid annual leave each calendar year. Up to 8 unused days carry over to the next year [E1].',
    outcome: 'SUCCESS',
    reason: 'OK',
    citations: [
      { id: 'E1', kind: 'document', title: 'Employee Onboarding FAQ', version: '1.2', page: 3, section: 'Leave', method: 'text', url: '/admin/documents/doc_0c4e/pages/3' },
    ],
    hits: [hit(1, 'c_0c41', 'onboarding-faq', 3, 0.88, '1.2'), hit(2, 'c_0c42', 'onboarding-faq', 4, 0.47, '1.2')],
    claims: [
      { text: '24 days of paid annual leave each calendar year', supported: true },
      { text: 'Up to 8 unused days carry over', supported: true },
    ],
    ms: [480, 0, 1600],
    tokens: [1750, 70],
  },
  {
    key: 'unsupported_claim',
    scenario: 'Regression question',
    match: (q) => /(hotel|accommodation|lodging)/i.test(q),
    route: 'DOCS',
    normalized: (q) => q,
    answer: 'The hotel limit for metro cities is ₹6,000 per night [E1]. Room upgrades are allowed for grade G5 and above.',
    outcome: 'PARTIAL',
    reason: 'UNSUPPORTED_CLAIMS',
    citations: [{ ...travelV2, page: 8, section: '4.3 Accommodation', url: '/admin/documents/doc_7f3a/pages/8' }],
    hits: [hit(1, 'c_ab13', 'travel-policy', 8, 0.74, '2.0'), hit(2, 'c_ab12', 'travel-policy', 7, 0.5, '2.0')],
    claims: [
      { text: 'hotel limit for metro cities is ₹6,000 per night', supported: true },
      { text: 'Room upgrades are allowed for grade G5 and above', supported: false },
    ],
    ms: [560, 0, 1950],
    tokens: [2050, 79],
  },
  {
    key: 'no_evidence',
    scenario: 'Insufficient evidence',
    match: () => true,
    route: 'DOCS',
    normalized: (q) => q,
    answer: FALLBACK_TEXT,
    outcome: 'PARTIAL',
    reason: 'NO_EVIDENCE',
    citations: [],
    hits: [hit(1, 'c_0c42', 'onboarding-faq', 4, 0.18, '1.2'), hit(2, 'c_2d10', 'finance-sop', 4, 0.12)],
    claims: [],
    ms: [450, 0, 700],
    tokens: [980, 22],
  },
]

export const SCENARIO_KEYS = SPECS.map((s) => s.key)

export function pickSpec(question: string): Spec {
  return SPECS.find((s) => s.match(question)) ?? SPECS[SPECS.length - 1]
}

export function specByKey(key: string): Spec {
  return SPECS.find((s) => s.key === key) ?? SPECS[SPECS.length - 1]
}

/** Contract 11 section 4: 0.15 / 0.60 USD per 1M tokens. Returns a 6-decimal string. */
export function costFor(tokensIn: number, tokensOut: number): string {
  const micro = Math.round((tokensIn * 15 + tokensOut * 60) / 100)
  return (micro / 1_000_000).toFixed(6)
}

function confidenceFor(outcome: Outcome, topScore: number): Confidence {
  if (outcome === 'SUCCESS') return topScore >= 0.7 ? 'HIGH' : 'MEDIUM'
  return 'LOW'
}

function vary(base: number, jitter: number): number {
  return base === 0 ? 0 : Math.round(base * (0.75 + jitter * 0.6))
}

export function runScenario(spec: Spec, input: ScenarioInput): ScenarioResult {
  const { jitter, configId } = input
  const isA = configId === 'A'
  const retrievalMs = vary(spec.ms[0] * (isA ? 0.6 : 1), jitter)
  const toolMs = spec.ms[1]
  const llmMs = vary(spec.ms[2], 1 - jitter)
  const guardMs = 4
  const totalMs = guardMs + retrievalMs + toolMs + llmMs + 60
  const tokensIn = vary(spec.tokens[0], jitter)
  const tokensOut = vary(spec.tokens[1], jitter)
  const cost = spec.tokens[0] === 0 ? '0.000000' : costFor(tokensIn, tokensOut)

  const hits = spec.hits ?? []
  const topScore = hits[0]?.score ?? 0
  const usesDocs = spec.route === 'DOCS' || spec.route === 'BOTH'
  const usesTool = spec.route === 'SQL' || spec.route === 'BOTH'
  const correlationId = `corr_${input.queryId.slice(-6).toLowerCase()}`

  const stage = (name: string, ms: number, fallback = 'OK'): StageStatus => ({
    stage: name,
    status: spec.stageOverrides?.[name] ?? fallback,
    latency_ms: ms,
  })
  const execution: StageStatus[] = [
    stage('guard', guardMs),
    stage('context', 2),
    stage('route', 180),
    ...(usesDocs
      ? [
          stage('retrieve_vector', Math.round(retrievalMs * 0.45)),
          isA ? stage('retrieve_bm25', 0, 'SKIPPED') : stage('retrieve_bm25', Math.round(retrievalMs * 0.15)),
          isA ? stage('fuse', 0, 'SKIPPED') : stage('fuse', 3),
          isA ? stage('rerank', 0, 'SKIPPED') : stage('rerank', Math.round(retrievalMs * 0.4)),
        ]
      : [stage('retrieve_vector', 0, 'SKIPPED'), stage('rerank', 0, 'SKIPPED')]),
    usesTool ? stage('tool', toolMs) : stage('tool', 0, 'SKIPPED'),
    stage('answer', llmMs),
    stage('validate', 9),
  ]

  const contextTurns = input.priorTurns.slice(-3).map((t, i) => ({
    turn_index: i + 1,
    role: t.role,
    chars: Math.min(t.text.length, 600),
    text_masked: maskPii(t.text).slice(0, 600),
  }))

  const docCitations = spec.citations.filter((c) => c.kind === 'document')
  const claims = spec.claims ?? []
  const supported = claims.filter((c) => c.supported).length
  const grounding = claims.length ? Number((supported / claims.length).toFixed(2)) : null

  const reranked = isA ? hits.slice(0, 5) : hits.map((h, i) => ({ ...h, score: Number(Math.min(0.99, h.score + 0.08 - i * 0.02).toFixed(2)) }))
  const bm25 = isA ? [] : hits.map((h, i) => ({ ...h, rank: i + 1, score: Number((12.4 - i * 2.7).toFixed(1)) })).reverse().map((h, i) => ({ ...h, rank: i + 1 }))
  const fused = isA ? [] : hits.map((h, i) => ({ ...h, score: Number((1 / (60 + i + 1) + 1 / (60 + hits.length - i)).toFixed(4)) }))

  const response: QueryResponse = {
    query_id: input.queryId,
    answer_markdown: spec.answer,
    outcome: spec.outcome,
    reason_code: spec.reason,
    confidence: confidenceFor(spec.outcome, reranked[0]?.score ?? topScore),
    route: spec.route,
    citations: spec.citations,
    tool_results: spec.toolResults ?? [],
    conflict: spec.conflict ?? false,
    usage: { tokens_in: tokensIn, tokens_out: tokensOut, cost_usd: cost, estimated: false },
    latency_ms: totalMs,
  }

  const drill: DrillDown = {
    identity: { query_id: input.queryId, ts: input.ts, session_id: input.sessionId, app_version: '0.3.0', config_id: configId },
    question: {
      original_masked: maskPii(input.question),
      normalized: spec.normalized(input.question, input.priorTurns),
      route: spec.route,
      route_reason: spec.route === 'SQL' || spec.route === 'BOTH' ? 'RULE_R1_ID_PATTERN' : spec.route === 'BLOCKED' ? 'GUARD_S1' : 'PLANNER',
    },
    execution,
    outcome: { outcome: spec.outcome, reason_code: spec.reason },
    retrieval: { vector: hits, bm25, fused, reranked },
    evidence_quality: usesDocs
      ? { relevant: topScore >= 0.5, top_score: reranked[0]?.score ?? topScore, expected_match: null }
      : undefined,
    context_turns: contextTurns,
    tool_calls: spec.toolCalls ?? [],
    generation: {
      model: 'openai/gpt-oss-120b',
      prompt_version: 'answer-v1',
      validation: spec.reason === 'OUTPUT_INVALID' ? 'SCHEMA_FAILED' : spec.route === 'BLOCKED' ? 'SKIPPED' : 'OK',
      raw_output:
        spec.route === 'BLOCKED'
          ? undefined
          : JSON.stringify(
              {
                answer_markdown: spec.answer,
                claims: claims.map((c) => ({ text: c.text, citations: docCitations.length ? ['E1'] : ['T1'] })),
                insufficient_evidence: spec.reason === 'NO_EVIDENCE',
                conflict: spec.conflict ?? false,
              },
              null,
              2,
            ),
    },
    citations: spec.citations.map((c) => ({ id: c.id, valid: true })),
    grounding: { score: grounding, claims },
    safety: { flags: spec.safety ?? [], pii_masked: maskPii(input.question) !== input.question, fallback: spec.reason === 'NO_EVIDENCE' },
    performance: { retrieval_ms: retrievalMs, tool_ms: toolMs, llm_ms: llmMs, total_ms: totalMs },
    usage: {
      calls:
        spec.tokens[0] === 0
          ? []
          : [
              { purpose: 'route', tokens_in: 380, tokens_out: 40 },
              { purpose: 'answer', tokens_in: Math.max(0, tokensIn - 380), tokens_out: Math.max(0, tokensOut - 40), cached_tokens: 0 },
            ],
      cost_usd: cost,
      usage_source: 'PROVIDER',
    },
    feedback: null,
    errors: (spec.errors ?? []).map((e) => ({ ...e, correlation_id: correlationId })),
  }

  return { response, drill }
}

/** Same idea as the server PII check (contract 11 section 6): e-mails and phone numbers never show. */
export function maskPii(text: string): string {
  return text
    .replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, '[EMAIL]')
    .replace(/(\+?\d[\d\s-]{8,}\d)/g, '[PHONE]')
}

export function scenarioName(key: string): string {
  return specByKey(key).scenario
}
