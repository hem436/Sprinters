import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api'
import type { MetricsFilters } from '../../api/types'
import { FilterBar } from '../../components/FilterBar'
import { Badge, Card, ErrorBanner, OutcomeBadge, PageHeader, RouteBadge, Spinner, Table } from '../../components/ui'
import { formatCost, formatMs, formatTs } from '../../lib/format'

export function QueryListPage() {
  const [filters, setFilters] = useState<MetricsFilters>({})
  const [page, setPage] = useState(1)
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['queries', filters, page],
    queryFn: () => api.listQueries({ ...filters, page }),
    keepPreviousData: true,
  })
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <div>
      <PageHeader title="Query executions" subtitle="Every query, with its outcome. Questions are PII-masked. Open a row for the full drill-down." />
      <FilterBar
        value={filters}
        onChange={(f) => {
          setFilters(f)
          setPage(1)
        }}
      />
      {error ? <ErrorBanner error={error} onRetry={() => refetch()} /> : null}
      {isLoading ? <Spinner /> : null}
      {data ? (
        <Card
          title={`${data.total} queries`}
          actions={
            <div className="flex items-center gap-2 text-xs">
              <button type="button" className="btn-secondary !py-0.5" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <span>
                Page {page} of {pages}
              </span>
              <button type="button" className="btn-secondary !py-0.5" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
                Next
              </button>
            </div>
          }
        >
          <Table head={['Time', 'Question', 'Route', 'Outcome', 'Latency', 'Cost', 'Feedback']} empty={data.items.length === 0}>
            {data.items.map((q) => (
              <tr key={q.query_id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" onClick={() => navigate(`/queries/${q.query_id}`)}>
                <td className="td whitespace-nowrap text-xs text-slate-500">{formatTs(q.ts)}</td>
                <td className="td max-w-md">
                  <Link to={`/queries/${q.query_id}`} className="line-clamp-2 hover:text-indigo-600" onClick={(e) => e.stopPropagation()}>
                    {q.question_masked}
                  </Link>
                </td>
                <td className="td">
                  <RouteBadge route={q.route} />
                </td>
                <td className="td">
                  <OutcomeBadge outcome={q.outcome} reason={q.reason_code} />
                </td>
                <td className="td whitespace-nowrap tabular-nums">{formatMs(q.latency_ms)}</td>
                <td className="td whitespace-nowrap tabular-nums">{formatCost(q.cost_usd)}</td>
                <td className="td">{q.feedback ? <Badge tone={q.feedback === 'HELPFUL' ? 'green' : 'red'}>{q.feedback === 'HELPFUL' ? '👍' : '👎'}</Badge> : <span className="text-slate-400">none</span>}</td>
              </tr>
            ))}
          </Table>
        </Card>
      ) : null}
    </div>
  )
}
