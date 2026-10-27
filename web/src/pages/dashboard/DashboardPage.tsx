import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../../api'
import type { MetricsFilters } from '../../api/types'
import { FilterBar } from '../../components/FilterBar'
import { KpiTile, toneFor } from '../../components/KpiTile'
import { Card, Empty, ErrorBanner, PageHeader, Spinner, Table } from '../../components/ui'
import { CHART } from '../../lib/chart'
import { formatCost, formatMs, formatNumber, formatPct, ratio } from '../../lib/format'

const tick = { fill: CHART.tick, fontSize: 11 }

export function DashboardPage() {
  const [filters, setFilters] = useState<MetricsFilters>({})
  const { data: m, isLoading, error, refetch } = useQuery({
    queryKey: ['metrics', filters],
    queryFn: () => api.metricsSummary(filters),
    keepPreviousData: true,
  })

  return (
    <div>
      <PageHeader
        title="Observability dashboard"
        subtitle="Execution success and AI quality for every query. An HTTP 200 is not a success when evidence or citations fail."
        actions={
          <Link to="/queries" className="btn-secondary">
            Open query list
          </Link>
        }
      />
      <FilterBar value={filters} onChange={setFilters} />
      {error ? <ErrorBanner error={error} onRetry={() => refetch()} /> : null}
      {isLoading || !m ? (
        isLoading ? <Spinner /> : null
      ) : m.total_queries === 0 ? (
        <Empty>No queries match these filters.</Empty>
      ) : (
        <Dashboard m={m} />
      )}
    </div>
  )
}

function Dashboard({ m }: { m: NonNullable<Awaited<ReturnType<typeof api.metricsSummary>>> }) {
  const total = m.total_queries
  const success = ratio(m.outcomes.SUCCESS, total)
  const citation = ratio(m.citation_support.valid, m.citation_support.total)
  const tool = ratio(m.tool_success.ok, m.tool_success.total)
  const fbTotal = m.feedback.helpful + m.feedback.not_helpful
  const helpfulRate = ratio(m.feedback.helpful, fbTotal)
  const safetyTotal = Object.values(m.safety_events).reduce((a, b) => a + b, 0)

  const latency = (['retrieval', 'tool', 'llm', 'total'] as const).map((k) => ({ stage: k, p50: m.latency_ms[k].p50, p95: m.latency_ms[k].p95 }))
  const routeCost = m.usage.cost_per_route.map((r) => ({ route: r.route, cost: r.cost_usd === null ? 0 : Number(r.cost_usd), label: formatCost(r.cost_usd), queries: r.queries }))

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <KpiTile label="Total queries" value={formatNumber(total)} detail={m.dropped_events ? `${m.dropped_events} events dropped` : 'No dropped events'} />
        <KpiTile
          label="Overall outcome"
          value={formatPct(success)}
          tone={toneFor(success, 0.75, 0.5)}
          detail={
            <span>
              <span className="text-emerald-600">{m.outcomes.SUCCESS} success</span> · <span className="text-amber-600">{m.outcomes.PARTIAL} partial</span> ·{' '}
              <span className="text-rose-600">{m.outcomes.FAILED} failed</span>
            </span>
          }
        />
        <KpiTile label="Retrieval success" value={formatPct(m.retrieval_success_rate)} tone={toneFor(m.retrieval_success_rate)} detail={m.hit_at_5 !== null ? `Eval hit@5: ${formatPct(m.hit_at_5)}` : 'Relevant evidence found'} />
        <KpiTile label="Grounding rate" value={formatPct(m.grounding_rate)} tone={toneFor(m.grounding_rate)} detail="Answers with grounding score ≥ 0.8" />
        <KpiTile label="Citation support" value={formatPct(citation)} tone={toneFor(citation, 0.95, 0.8)} detail={`${m.citation_support.valid} of ${m.citation_support.total} citations valid`} />
        <KpiTile label="Tool success" value={formatPct(tool)} tone={toneFor(tool, 0.9, 0.7)} detail={`${m.tool_success.ok} of ${m.tool_success.total} tool calls`} />
        <KpiTile
          label="Safety events"
          value={formatNumber(safetyTotal)}
          tone={safetyTotal ? 'warn' : 'good'}
          detail={
            Object.keys(m.safety_events).length ? (
              <ul className="space-y-0.5">
                {Object.entries(m.safety_events).map(([flag, n]) => (
                  <li key={flag} className="flex min-w-0 items-baseline justify-between gap-2" title={flag}>
                    <code className="min-w-0 truncate">{flag}</code>
                    <span className="tabular-nums">{n}</span>
                  </li>
                ))}
              </ul>
            ) : (
              'None'
            )
          }
        />
        <KpiTile label="Latency p50 / p95" value={formatMs(m.latency_ms.total.p50)} detail={`p95 ${formatMs(m.latency_ms.total.p95)} end to end`} />
        <KpiTile
          label="Usage and cost"
          value={formatCost(m.usage.total_cost_usd)}
          detail={`${formatNumber(m.usage.tokens_in)} in · ${formatNumber(m.usage.tokens_out)} out · ${formatCost(m.usage.cost_per_query_usd)} per query`}
        />
        <KpiTile label="User feedback" value={formatPct(helpfulRate)} tone={toneFor(helpfulRate, 0.7, 0.5)} detail={`${m.feedback.helpful} helpful · ${m.feedback.not_helpful} not helpful`} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Outcome over time">
          <div className="h-64">
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
        </Card>
        <Card title="Latency per stage (ms)">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={latency}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="stage" tick={tick} tickLine={false} />
                <YAxis tick={tick} tickLine={false} axisLine={false} width={44} />
                <Tooltip formatter={(v: number) => formatMs(v)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="p50" fill={CHART.p50} radius={[3, 3, 0, 0]} />
                <Bar dataKey="p95" fill={CHART.p95} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Cost per route">
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={routeCost} layout="vertical" margin={{ left: 16 }}>
                <CartesianGrid stroke={CHART.grid} horizontal={false} />
                <XAxis type="number" tick={tick} tickLine={false} />
                <YAxis type="category" dataKey="route" tick={tick} tickLine={false} axisLine={false} width={96} />
                <Tooltip formatter={(_v, _n, item) => [`${(item.payload as { label: string }).label} over ${(item.payload as { queries: number }).queries} queries`, 'Cost']} />
                <Bar dataKey="cost" fill={CHART.cost} radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Ingestion cost per document">
          <Table head={['Document', 'OCR cost']}>
            {m.usage.ingestion_cost_per_document.map((d) => (
              <tr key={d.document_id}>
                <td className="td">
                  <Link to={`/admin/documents/${d.document_id}`} className="text-indigo-600 hover:underline">
                    {d.title}
                  </Link>
                </td>
                <td className={`td tabular-nums ${d.cost_usd === null ? 'italic text-slate-400' : ''}`}>{formatCost(d.cost_usd)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </div>
  )
}
