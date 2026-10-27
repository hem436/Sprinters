import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api'
import type { ConfigId, EvalRun } from '../../api/types'
import { Badge, Card, Empty, ErrorBanner, OutcomeBadge, PageHeader, RouteBadge, Spinner, StatusBadge, Table } from '../../components/ui'
import { formatCost, formatMs, formatTs } from '../../lib/format'

/** Measures where a lower value is better. All other measures: higher is better. */
const LOWER_IS_BETTER = /latency|cost/i

export function EvalPage() {
  const qc = useQueryClient()
  const runs = useQuery({
    queryKey: ['eval-runs'],
    queryFn: api.listEvalRuns,
    refetchInterval: (data) => (data?.some((r) => r.status === 'RUNNING' || r.status === 'QUEUED') ? 1000 : false),
  })
  const start = useMutation({
    mutationFn: (c: ConfigId) => api.startEvalRun(c),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['eval-runs'] }),
  })

  const latestDone = (c: ConfigId) => runs.data?.find((r) => r.config_id === c && r.status === 'DONE')
  const [aId, bId] = [latestDone('A')?.run_id, latestDone('B')?.run_id]
  const runA = useQuery({ queryKey: ['eval-run', aId], queryFn: () => api.getEvalRun(aId as string), enabled: !!aId })
  const runB = useQuery({ queryKey: ['eval-run', bId], queryFn: () => api.getEvalRun(bId as string), enabled: !!bId })
  const running = runs.data?.some((r) => r.status === 'RUNNING' || r.status === 'QUEUED')

  return (
    <div className="space-y-5">
      <PageHeader
        title="Evaluation and configuration experiment"
        subtitle="Config A: vector retrieval, then LLM. Config B: hybrid retrieval, rerank, then LLM. Same evaluation set for both."
        actions={
          <div className="flex gap-2">
            {(['A', 'B'] as ConfigId[]).map((c) => (
              <button key={c} type="button" className="btn-primary" disabled={running || start.isLoading} onClick={() => start.mutate(c)}>
                Run config {c}
              </button>
            ))}
          </div>
        }
      />
      {start.error ? <ErrorBanner error={start.error} /> : null}
      {runs.error ? <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} /> : null}

      <Card title="Runs">
        {runs.isLoading ? (
          <Spinner />
        ) : (
          <Table head={['Run', 'Config', 'Status', 'Progress', 'Started']} empty={!runs.data?.length}>
            {runs.data?.map((r) => (
              <tr key={r.run_id}>
                <td className="td font-mono text-xs">{r.run_id}</td>
                <td className="td"><Badge>{r.config_id}</Badge></td>
                <td className="td"><StatusBadge status={r.status} /></td>
                <td className="td w-48">
                  <div className="flex items-center gap-2">
                    <span className="h-2 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                      <span className="block h-2 rounded bg-indigo-500" style={{ width: `${(r.cases_done / Math.max(1, r.cases_total)) * 100}%` }} />
                    </span>
                    <span className="text-xs tabular-nums">{r.cases_done}/{r.cases_total}</span>
                  </div>
                </td>
                <td className="td text-xs text-slate-500">{formatTs(r.started_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {runA.data && runB.data ? <Comparison a={runA.data} b={runB.data} /> : <Card title="A vs B"><Empty>Run both configurations to see the comparison.</Empty></Card>}
    </div>
  )
}

export function Comparison({ a, b }: { a: EvalRun; b: EvalRun }) {
  const measures = useMemo(() => Array.from(new Set([...Object.keys(a.summary ?? {}), ...Object.keys(b.summary ?? {})])), [a, b])
  const [onlyFailures, setOnlyFailures] = useState(true)
  const byCase = new Map((a.results ?? []).map((r) => [r.case_id, r]))
  const rows = (b.results ?? []).map((rb) => ({ b: rb, a: byCase.get(rb.case_id) }))
  const shown = onlyFailures ? rows.filter((r) => r.b.behavior_match === 0 || r.a?.behavior_match === 0) : rows

  return (
    <>
      <Card title="A vs B comparison">
        <Table head={['Measure', 'Config A', 'Config B', 'Difference', 'Better']}>
          {measures.map((m) => {
            const va = a.summary?.[m] ?? null
            const vb = b.summary?.[m] ?? null
            const diff = va !== null && vb !== null ? vb - va : null
            const better = diff === null || diff === 0 ? 'same' : (diff > 0) !== LOWER_IS_BETTER.test(m) ? 'B' : 'A'
            const fmt = (v: number | null) => (v === null ? 'n/a' : /cost/i.test(m) ? v.toFixed(6) : Number.isInteger(v) ? String(v) : v.toFixed(3))
            return (
              <tr key={m}>
                <td className="td">{m}</td>
                <td className="td tabular-nums">{fmt(va)}</td>
                <td className="td tabular-nums">{fmt(vb)}</td>
                <td className="td tabular-nums">{diff === null ? 'n/a' : `${diff > 0 ? '+' : ''}${fmt(diff)}`}</td>
                <td className="td">{better === 'same' ? <span className="text-slate-400">same</span> : <Badge tone={better === 'B' ? 'green' : 'amber'}>{better}</Badge>}</td>
              </tr>
            )
          })}
        </Table>
      </Card>

      <Card
        title="Per-case results"
        actions={
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={onlyFailures} onChange={(e) => setOnlyFailures(e.target.checked)} />
            Only cases where a config failed
          </label>
        }
      >
        <Table head={['Case', 'Scenario', 'Expected route', 'Config A', 'Config B', 'hit@5 A / B', 'Latency B', 'Cost B']} empty={shown.length === 0}>
          {shown.map(({ a: ra, b: rb }) => (
            <tr key={rb.case_id}>
              <td className="td font-mono text-xs">{rb.case_id}</td>
              <td className="td">{rb.scenario}</td>
              <td className="td"><RouteBadge route={rb.expected_route} /></td>
              <td className="td">{ra ? <CaseCell r={ra} /> : 'n/a'}</td>
              <td className="td"><CaseCell r={rb} /></td>
              <td className="td tabular-nums">{ra?.hit_at_5 ?? 'n/a'} / {rb.hit_at_5 ?? 'n/a'}</td>
              <td className="td tabular-nums">{formatMs(rb.latency_ms)}</td>
              <td className="td tabular-nums">{formatCost(rb.cost_usd)}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  )
}

function CaseCell({ r }: { r: NonNullable<EvalRun['results']>[number] }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <OutcomeBadge outcome={r.outcome} reason={r.reason_code} />
      <span className="flex items-center gap-2 text-xs">
        {r.behavior_match ? <Badge tone="green">match</Badge> : <Badge tone="red">mismatch</Badge>}
        <Link to={`/queries/${r.query_id}`} className="text-indigo-600 hover:underline">
          drill-down
        </Link>
      </span>
    </div>
  )
}
