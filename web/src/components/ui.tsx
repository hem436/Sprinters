import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { Confidence, Outcome, ReasonCode, Route } from '../api/types'

type Tone = 'green' | 'amber' | 'red' | 'blue' | 'slate' | 'violet'

const TONES: Record<Tone, string> = {
  green: 'bg-emerald-100 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-500/15 dark:text-emerald-300',
  amber: 'bg-amber-100 text-amber-800 ring-amber-600/20 dark:bg-amber-500/15 dark:text-amber-300',
  red: 'bg-rose-100 text-rose-800 ring-rose-600/20 dark:bg-rose-500/15 dark:text-rose-300',
  blue: 'bg-indigo-50 text-indigo-800 ring-indigo-600/20 dark:bg-indigo-500/15 dark:text-indigo-200',
  violet: 'bg-slate-900 text-white ring-slate-900/20 dark:bg-slate-200 dark:text-slate-900',
  slate: 'bg-slate-100 text-slate-700 ring-slate-500/20 dark:bg-slate-700/40 dark:text-slate-300',
}

export function Badge({ tone = 'slate', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </span>
  )
}

export const OUTCOME_TONE: Record<Outcome, Tone> = { SUCCESS: 'green', PARTIAL: 'amber', FAILED: 'red' }

/** Outcome colors follow contract 11 section 5. The reason code is always shown with it. */
export function OutcomeBadge({ outcome, reason }: { outcome: Outcome; reason?: ReasonCode }) {
  return (
    <Badge tone={OUTCOME_TONE[outcome]}>
      {outcome}
      {reason ? <span className="font-normal opacity-80">· {reason}</span> : null}
    </Badge>
  )
}

const CONFIDENCE_TONE: Record<Confidence, Tone> = { HIGH: 'green', MEDIUM: 'blue', LOW: 'amber' }

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <Badge tone={CONFIDENCE_TONE[confidence]} title="Confidence category (contract 11 section 5)">{confidence} confidence</Badge>
}

const ROUTE_TONE: Record<Route, Tone> = { DOCS: 'blue', SQL: 'violet', BOTH: 'violet', CONVERSATIONAL: 'slate', BLOCKED: 'red' }

export function RouteBadge({ route }: { route: Route }) {
  return <Badge tone={ROUTE_TONE[route]}>{route}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Tone = /^(OK|DONE|INDEXED|APPROVED)$/.test(status)
    ? 'green'
    : /^(SKIPPED|QUEUED)$/.test(status)
      ? 'slate'
      : /(REVIEW|RUNNING|PROCESSING|EMPTY|PARTIAL)/.test(status)
        ? 'amber'
        : 'red'
  return <Badge tone={tone}>{status}</Badge>
}

export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title || actions ? (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-2.5 dark:border-slate-800">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p> : null}
      </div>
      {actions}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" />
      {label}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">{children}</p>
}

/** Shows the contract 05 error envelope: code, message, field problems and the request id. */
export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null
  const e = error instanceof ApiError ? error : null
  return (
    <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          {e ? <code className="mr-2 font-semibold">{e.code}</code> : null}
          {e ? e.message : error instanceof Error ? error.message : 'Something went wrong.'}
        </span>
        {onRetry ? (
          <button type="button" className="btn-secondary !py-0.5" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </div>
      {e && e.fields.length > 0 ? (
        <ul className="mt-1 list-disc pl-5">
          {e.fields.map((f) => (
            <li key={f.field}>
              <code>{f.field}</code>: {f.problem}
            </li>
          ))}
        </ul>
      ) : null}
      {e?.requestId ? <p className="mt-1 text-xs opacity-70">Request id: {e.requestId}</p> : null}
    </div>
  )
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500 dark:text-slate-400">{k}</dt>
          <dd className="min-w-0 break-words">{v ?? <span className="text-slate-400">n/a</span>}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Table({ head, children, empty }: { head: ReactNode[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i} className="th">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">{children}</tbody>
      </table>
      {empty ? <Empty>No rows.</Empty> : null}
    </div>
  )
}
