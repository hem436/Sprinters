import type { Citation, Confidence, QueryResponse } from '../../api/types'
import { Answer } from '../../components/Answer'
import { FeedbackBar } from '../../components/FeedbackBar'
import { ErrorBanner } from '../../components/ui'

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

const CONFIDENCE_LABEL: Record<Confidence, string> = { HIGH: 'High confidence', MEDIUM: 'Medium confidence', LOW: 'Low confidence' }

const tag = 'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium'

/** Short label for a source button: document title, version and page, or the tool name. */
export function sourceLabel(c: Citation): string {
  return c.kind === 'document' ? `${c.title} · v${c.version} · p.${c.page}` : `${c.tool} · ${c.row_count} ${c.row_count === 1 ? 'row' : 'rows'}`
}

export function ChatMessage({
  turn,
  selectedId,
  onSelect,
  onRetry,
}: {
  turn: Turn
  selectedId?: string | null
  onSelect?: (citationId: string) => void
  onRetry: () => void
}) {
  const r = turn.response
  const isFallback = r?.reason_code === 'NO_EVIDENCE' || r?.reason_code === 'BLOCKED_SAFETY'
  const citations = r?.citations ?? turn.citations

  return (
    <div className="flex flex-col gap-3">
      <div className="max-w-[80%] self-end rounded-2xl rounded-br-md bg-slate-900 px-4 py-2.5 text-sm text-white dark:bg-indigo-600">{turn.question}</div>

      <div className="flex max-w-[92%] flex-col gap-2.5 self-start">
        <div
          className={`flex flex-col gap-2.5 rounded-2xl rounded-bl-md px-4 py-3 ${
            isFallback ? 'border border-dashed border-slate-300 bg-slate-50 dark:border-slate-600 dark:bg-slate-800/50' : 'bg-slate-100 dark:bg-slate-800'
          }`}
        >
          {turn.status === 'streaming' && !turn.partial ? (
            <p className="flex items-center gap-2 text-sm text-slate-500" role="status">
              <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
              {STAGE_LABEL[turn.stage ?? ''] ?? 'Working'}…
            </p>
          ) : null}
          {turn.partial || r ? <Answer markdown={r?.answer_markdown ?? turn.partial} /> : null}
          {turn.status === 'stopped' ? <p className="text-xs text-slate-500">You stopped this answer.</p> : null}
          {turn.status === 'error' ? <ErrorBanner error={turn.error} onRetry={onRetry} /> : null}

          {r && !isFallback ? (
            <div className="flex flex-wrap gap-1.5">
              <span className={`${tag} ${r.confidence === 'LOW' ? 'border-amber-300 text-amber-800 dark:border-amber-500/50 dark:text-amber-200' : 'border-slate-300 text-slate-700 dark:border-slate-600 dark:text-slate-200'}`}>
                {CONFIDENCE_LABEL[r.confidence]}
              </span>
              {r.conflict ? (
                <span className={`${tag} border-dashed border-amber-400 text-amber-800 dark:border-amber-500/60 dark:text-amber-200`} title="Two versions give different values. The answer shows both and names the current one.">
                  Two versions disagree
                </span>
              ) : null}
            </div>
          ) : null}
        </div>

        {citations.length > 0 ? (
          <div className="flex flex-wrap gap-1.5" aria-label={isFallback ? 'Closest sources' : 'Sources'} role="group">
            {citations.map((c) => {
              const active = c.id === selectedId
              return (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelect?.(c.id)}
                  className={`inline-flex min-h-[34px] max-w-full items-center gap-1.5 rounded-full border px-3 text-xs transition ${
                    active
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-800 dark:bg-indigo-500/15 dark:text-indigo-200'
                      : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800'
                  }`}
                >
                  <strong>{c.id}</strong>
                  <span className="truncate">{sourceLabel(c)}</span>
                </button>
              )
            })}
          </div>
        ) : null}

        {r ? (
          // The chat is the user view: no links into admin pages. Admins open a query from the dashboard.
          <FeedbackBar queryId={r.query_id} />
        ) : null}
      </div>
    </div>
  )
}
