import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../../api'
import type { MetricsFilters, MetricsSummary, Outcome } from '../../api/types'
import { Badge, ErrorBanner, OutcomeBadge, Spinner } from '../../components/ui'
import { CHART } from '../../lib/chart'
import { formatCost, formatMs, formatNumber, formatPct, formatTs, isoDay, ratio } from '../../lib/format'

// Admin home, like the wireframe: one time switch, four headline KPIs, six small ones, one chart and the
// recent queries. Together the tiles are the 10 KPIs of case 8.1. Kept minimal on purpose.

const tick = { fill: CHART.tick, fontSize: 11 }

const RANGES = [
  { id: 'today', label: 'Today', days: 0 },
  { id: '7d', label: '7 days', days: 6 },
  { id: '30d', label: '30 days', days: 29 },
  { id: 'all', label: 'All', days: null },
] as const
type RangeId = (typeof RANGES)[number]['id']

/** The first day of a range, in local time; null for all time. */
export function rangeStart(id: RangeId, now = new Date()): string | null {
  const range = RANGES.find((r) => r.id === id)
  if (!range || range.days === null) return null
  const d = new Date(now)
  d.setDate(d.getDate() - range.days)
  return isoDay(new Date(d.getTime() - d.getTimezoneOffset() * 60_000))
}

const segment = (on: boolean) =>
  `inline-flex min-h-[34px] items-center rounded-full px-3.5 text-sm font-medium ${
    on ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
  }`

const chip = (on: boolean) =>
  `inline-flex min-h-[32px] items-center rounded-full border px-3 text-xs font-medium ${
    on
      ? 'border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-900'
      : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800'
  }`

export function DashboardPage() {
  const [range, setRange] = useState<RangeId>('7d')
  const filters: MetricsFilters = useMemo(() => {
    const from = rangeStart(range)
    return from ? { from } : {}
  }, [range])

  const summary = useQuery({ queryKey: ['metrics', filters], queryFn: () => api.metricsSummary(filters), keepPreviousData: true })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <h1 className="m-0 mr-auto text-xl font-semibold tracking-tight">Dashboard</h1>
        <div role="group" aria-label="Time range" className="flex gap-1 rounded-full border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900">
          {RANGES.map((r) => (
            <button key={r.id} type="button" aria-pressed={range === r.id} className={segment(range === r.id)} onClick={() => setRange(r.id)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {summary.error ? <ErrorBanner error={summary.error} onRetry={() => summary.refetch()} /> : null}
      {summary.isLoading ? <Spinner /> : null}
      {summary.data ? <Kpis m={summary.data} /> : null}
      <RecentQueries filters={filters} />
    </div>
  )
}

function Big({ label, value, detail, tone }: { label: string; value: ReactNode; detail: ReactNode; tone?: 'good' | 'warn' | 'bad' }) {
  const dot = tone === 'good' ? 'bg-emerald-500' : tone === 'warn' ? 'bg-amber-500' : tone === 'bad' ? 'bg-rose-500' : null
  return (
    <div className="card flex flex-col gap-1 !rounded-2xl p-5" data-testid="kpi-tile">
      <span className="label flex items-center gap-1.5">
        {dot ? <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden /> : null}
        {label}
      </span>
      <strong className="text-3xl font-bold tabular-nums">{value}</strong>
      <span className="text-xs text-slate-500 dark:text-slate-400">{detail}</span>
    </div>
  )
}

function Small({ label, value, detail, title }: { label: string; value: ReactNode; detail: ReactNode; title?: string }) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-3" title={title} data-testid="kpi-tile">
      <span className="label">{label}</span>
      <strong className="text-lg font-semibold tabular-nums">{value}</strong>
      <span className="text-xs text-slate-500 dark:text-slate-400">{detail}</span>
    </div>
  )
}

const tone = (rate: number | null, good: number, warn: number) => (rate === null ? undefined : rate >= good ? 'good' : rate >= warn ? 'warn' : 'bad')

function Kpis({ m }: { m: MetricsSummary }) {
  const total = m.total_queries
  const success = ratio(m.outcomes.SUCCESS, total)
  const citation = ratio(m.citation_support.valid, m.citation_support.total)
  const tool = ratio(m.tool_success.ok, m.tool_success.total)
  const fbTotal = m.feedback.helpful + m.feedback.not_helpful
  const helpful = ratio(m.feedback.helpful, fbTotal)
  const safety = Object.entries(m.safety_events)
  const safetyTotal = safety.reduce((a, [, n]) => a + n, 0)
  const l = m.latency_ms
  const routeCost = m.usage.cost_per_route.map((r) => `${r.route}: ${formatCost(r.cost_usd)} over ${r.queries} queries`).join('\n')

  if (total === 0) return <p className="card m-0 !rounded-2xl p-8 text-center text-sm text-slate-500">No queries in this time range.</p>

  return (
    <>
      <section aria-label="Headline KPIs" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Big
          label="Total queries"
          value={formatNumber(total)}
          detail={`${m.outcomes.SUCCESS} success · ${m.outcomes.PARTIAL} partial · ${m.outcomes.FAILED} failed`}
        />
        <Big label="Success rate" value={formatPct(success)} tone={tone(success, 0.75, 0.5)} detail="Success outcome, not only HTTP 200" />
        <Big label="Grounding rate" value={formatPct(m.grounding_rate)} tone={tone(m.grounding_rate, 0.85, 0.6)} detail="Answers with grounding ≥ 0.8" />
        <Big
          label="Latency p95"
          value={formatMs(l.total.p95)}
          detail={`p50 ${formatMs(l.total.p50)} · retrieval ${formatMs(l.retrieval.p95)} · tool ${formatMs(l.tool.p95)} · LLM ${formatMs(l.llm.p95)}`}
        />
      </section>

      <section aria-label="More KPIs" className="card grid grid-cols-2 divide-slate-200 !rounded-2xl sm:grid-cols-3 lg:grid-cols-6 lg:divide-x dark:divide-slate-800">
        <Small label="Retrieval" value={formatPct(m.retrieval_success_rate)} detail={m.hit_at_5 !== null ? `eval hit@5 ${formatPct(m.hit_at_5)}` : 'relevant evidence'} />
        <Small label="Citations" value={formatPct(citation)} detail={`${m.citation_support.valid} of ${m.citation_support.total} valid`} />
        <Small label="Tools" value={formatPct(tool)} detail={`${m.tool_success.ok} of ${m.tool_success.total} calls OK`} />
        <Small label="Safety" value={formatNumber(safetyTotal)} detail="events" title={safety.map(([f, n]) => `${f}: ${n}`).join('\n') || 'No safety events'} />
        <Small
          label="Tokens"
          value={formatNumber(m.usage.tokens_in + m.usage.tokens_out)}
          detail={`${formatNumber(m.usage.tokens_in)} in · ${formatNumber(m.usage.tokens_out)} out · ${formatCost(m.usage.total_cost_usd)}`}
          title={`Cost ${formatCost(m.usage.total_cost_usd)}, ${formatCost(m.usage.cost_per_query_usd)} per query\n${routeCost}`}
        />
        <Small label="Feedback" value={formatPct(helpful)} detail={`${m.feedback.helpful} helpful · ${m.feedback.not_helpful} not`} />
      </section>

      <section aria-label="Outcome over time" className="card !rounded-2xl p-4">
        <h2 className="m-0 mb-3 text-sm font-semibold">Outcome over time</h2>
        <div className="h-56">
          <ResponsiveContainer>
            <BarChart data={m.outcome_over_time}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="bucket" tick={tick} tickLine={false} />
              <YAxis tick={tick} allowDecimals={false} tickLine={false} axisLine={false} width={32} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="SUCCESS" stackId="o" fill={CHART.success} />
              <Bar dataKey="PARTIAL" stackId="o" fill={CHART.partial} />
              <Bar dataKey="FAILED" stackId="o" fill={CHART.failed} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </>
  )
}

const QUICK: { id: string; label: string; outcome: Outcome | '' }[] = [
  { id: 'all', label: 'All', outcome: '' },
  { id: 'failed', label: 'Failed', outcome: 'FAILED' },
  { id: 'partial', label: 'Partial', outcome: 'PARTIAL' },
]

function RecentQueries({ filters }: { filters: MetricsFilters }) {
  const navigate = useNavigate()
  const [quick, setQuick] = useState('all')
  const outcome = QUICK.find((q) => q.id === quick)?.outcome ?? ''
  const listFilters = { ...filters, outcome }
  const list = useInfiniteQuery({
    queryKey: ['queries', listFilters],
    queryFn: ({ pageParam = 1 }) => api.listQueries({ ...listFilters, page: pageParam as number }),
    getNextPageParam: (last) => (last.page * last.page_size < last.total ? last.page + 1 : undefined),
    keepPreviousData: true,
  })
  const rows = list.data?.pages.flatMap((p) => p.items) ?? []
  const total = list.data?.pages[0]?.total ?? 0

  return (
    <section aria-label="Recent queries" className="card !rounded-2xl">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <h2 className="m-0 mr-auto text-sm font-semibold">Recent queries</h2>
        <div role="group" aria-label="Quick filter" className="flex flex-wrap gap-1.5">
          {QUICK.map((q) => (
            <button key={q.id} type="button" aria-pressed={quick === q.id} className={chip(quick === q.id)} onClick={() => setQuick(q.id)}>
              {q.label}
            </button>
          ))}
        </div>
      </div>
      {list.error ? (
        <div className="px-4 pb-4">
          <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
        </div>
      ) : null}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-t border-slate-200 dark:border-slate-800">
              {['Time', 'Question (masked)', 'Outcome', 'Latency', 'Tokens', 'Feedback'].map((h) => (
                <th key={h} className="th">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((q) => (
              <tr
                key={q.query_id}
                className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                onClick={() => navigate(`/queries/${q.query_id}`)}
              >
                <td className="td whitespace-nowrap text-xs text-slate-500">{formatTs(q.ts)}</td>
                <td className="td max-w-md">
                  <a
                    href={`/queries/${q.query_id}`}
                    className="line-clamp-2 hover:text-indigo-600 dark:hover:text-indigo-300"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      navigate(`/queries/${q.query_id}`)
                    }}
                  >
                    {q.question_masked}
                  </a>
                </td>
                <td className="td">
                  <OutcomeBadge outcome={q.outcome} reason={q.reason_code} />
                </td>
                <td className="td whitespace-nowrap tabular-nums">{formatMs(q.latency_ms)}</td>
                <td className="td whitespace-nowrap tabular-nums" title={`Cost ${formatCost(q.cost_usd)}`}>
                  {q.tokens_in !== undefined && q.tokens_out !== undefined ? (
                    formatNumber(q.tokens_in + q.tokens_out)
                  ) : (
                    // The server does not send tokens in this list yet; show the cost meanwhile.
                    <span className={q.cost_usd === null ? 'italic text-slate-400' : ''}>{formatCost(q.cost_usd)}</span>
                  )}
                </td>
                <td className="td">
                  {q.feedback ? <Badge tone={q.feedback === 'HELPFUL' ? 'green' : 'red'}>{q.feedback === 'HELPFUL' ? 'Helpful' : 'Not helpful'}</Badge> : <span className="text-slate-400">none</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.isLoading ? (
          <div className="p-4">
            <Spinner />
          </div>
        ) : rows.length === 0 ? (
          <p className="m-0 p-8 text-center text-sm text-slate-500">No queries match.</p>
        ) : null}
      </div>
      <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm text-slate-500 dark:border-slate-800">
        <span>
          Showing {rows.length} of {total}
        </span>
        {list.hasNextPage ? (
          <button type="button" className={chip(false)} disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>
            {list.isFetchingNextPage ? 'Loading' : 'Load more'}
          </button>
        ) : null}
      </div>
    </section>
  )
}
