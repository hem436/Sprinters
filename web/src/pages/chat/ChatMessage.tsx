import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Citation, QueryResponse } from '../../api/types'
import { Answer } from '../../components/Answer'
import { CitationChip } from '../../components/CitationChip'
import { FeedbackBar } from '../../components/FeedbackBar'
import { Badge, ConfidenceBadge, ErrorBanner, OutcomeBadge, RouteBadge } from '../../components/ui'
import { useAuth } from '../../hooks/useAuth'
import { formatCost, formatMs } from '../../lib/format'

export interface Turn {
  id: string
  question: string
  status: 'streaming' | 'done' | 'error' | 'stopped'
  stage?: string
  partial: string
  citations: Citation[]
  response?: QueryResponse
  error?: unknown
}

const STAGE_LABEL: Record<string, string> = {
  guard: 'Checking the question',
  context: 'Reading the conversation',
  route: 'Choosing documents or data',
  retrieve_vector: 'Searching documents',
  retrieve_bm25: 'Searching exact terms',
  fuse: 'Combining results',
  rerank: 'Ranking evidence',
  tool: 'Querying business data',
  answer: 'Writing the answer',
  validate: 'Checking citations',
}

export function ChatMessage({ turn, onRetry }: { turn: Turn; onRetry: () => void }) {
  const { user } = useAuth()
  const [showTools, setShowTools] = useState(false)
  const r = turn.response
  const isFallback = r?.reason_code === 'NO_EVIDENCE'
  const isBlocked = r?.reason_code === 'BLOCKED_SAFETY'
  const citations = r?.citations ?? turn.citations

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 text-sm text-white shadow-sm">{turn.question}</div>
      </div>

      <div className="flex">
        <div className="card w-full max-w-[92%] space-y-3 rounded-2xl rounded-bl-sm px-4 py-3">
          {turn.status === 'streaming' && !turn.partial ? (
            <p className="flex items-center gap-2 text-sm text-slate-500" role="status">
              <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
              {STAGE_LABEL[turn.stage ?? ''] ?? 'Working'}…
            </p>
          ) : null}

          {r && (isFallback || isBlocked) ? (
            <div className={`rounded-lg border px-3 py-2 text-sm ${isBlocked ? 'border-rose-300 bg-rose-50 dark:border-rose-500/40 dark:bg-rose-500/10' : 'border-amber-300 bg-amber-50 dark:border-amber-500/40 dark:bg-amber-500/10'}`}>
              <Answer markdown={r.answer_markdown} />
            </div>
          ) : turn.partial || r ? (
            <Answer markdown={r?.answer_markdown ?? turn.partial} />
          ) : null}

          {turn.status === 'stopped' ? <p className="text-xs text-slate-500">You stopped this answer.</p> : null}
          {turn.status === 'error' ? <ErrorBanner error={turn.error} onRetry={onRetry} /> : null}

          {r?.conflict ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
              <strong>Sources disagree.</strong> Two versions give different values. The answer shows both and names the current version.
            </div>
          ) : null}

          {citations.length > 0 ? (
            <div>
              <p className="label">{isFallback ? 'Closest sources' : 'Sources'}</p>
              <div className="flex flex-wrap gap-1.5">
                {citations.map((c) => (
                  <CitationChip key={c.id} citation={c} />
                ))}
              </div>
            </div>
          ) : null}

          {r && r.tool_results.length > 0 ? (
            <div>
              <button type="button" className="text-xs text-indigo-600 hover:underline" onClick={() => setShowTools((s) => !s)}>
                {showTools ? 'Hide' : 'Show'} data used ({r.tool_results.length})
              </button>
              {showTools
                ? r.tool_results.map((t) => (
                    <div key={t.id} className="mt-2 rounded-lg bg-slate-50 p-2 text-xs dark:bg-slate-800/60">
                      <p className="mb-1">
                        <strong>{t.id}</strong> <code>{t.tool}</code> · {t.status}
                        {t.summary ? <span className="block text-slate-600 dark:text-slate-300">{t.summary}</span> : null}
                      </p>
                      {t.rows && t.rows.length > 0 ? (
                        <div className="overflow-x-auto">
                          <table className="text-left">
                            <thead>
                              <tr>
                                {Object.keys(t.rows[0]).map((k) => (
                                  <th key={k} className="pr-3 font-semibold">
                                    {k}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {t.rows.map((row, i) => (
                                <tr key={i}>
                                  {Object.values(row).map((v, j) => (
                                    <td key={j} className="pr-3">
                                      {String(v)}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                    </div>
                  ))
                : null}
            </div>
          ) : null}

          {r ? (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-2 dark:border-slate-800">
              <ConfidenceBadge confidence={r.confidence} />
              <OutcomeBadge outcome={r.outcome} reason={r.reason_code} />
              <RouteBadge route={r.route} />
              {r.conflict ? <Badge tone="amber">Conflict</Badge> : null}
              <span className="ml-auto flex items-center gap-2 text-[11px] text-slate-500">
                <span>{formatMs(r.latency_ms)}</span>
                <span>
                  {r.usage.tokens_in + r.usage.tokens_out} tokens · {formatCost(r.usage.cost_usd)}
                  {r.usage.estimated ? ' (estimated)' : ''}
                </span>
                {user ? (
                  <Link to={`/queries/${r.query_id}`} className="text-indigo-600 hover:underline">
                    Drill-down
                  </Link>
                ) : (
                  <span title="Query id">{r.query_id}</span>
                )}
              </span>
            </div>
          ) : null}

          {r ? <FeedbackBar queryId={r.query_id} /> : null}
        </div>
      </div>
    </div>
  )
}
