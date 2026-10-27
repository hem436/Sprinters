import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../../api'
import type { FinTable, MetricMapRow, ReviewDecision } from '../../api/types'
import { Badge, Card, Empty, ErrorBanner, PageHeader, Spinner, StatusBadge, Table } from '../../components/ui'

const SCALE_LABEL: Record<number, string> = { 1: 'units', 1000: 'thousand', 100000: 'lakh', 1000000: 'million', 10000000: 'crore' }

/** Financial table review and metric-map approval (WP-UI3, contract 14 F6 and F8). */
export function FinancePage() {
  const [params, setParams] = useSearchParams()
  const docs = useQuery({ queryKey: ['documents', '', 'Finance'], queryFn: () => api.listDocuments({ category: 'Finance' }) })
  const docId = params.get('doc') ?? docs.data?.[0]?.document_id ?? ''

  return (
    <div className="space-y-5">
      <PageHeader title="Financial tables and metric map" subtitle="Numbers from a table are used only after its checks pass or a person approves it." />
      <Card
        title="Tables"
        actions={
          <select className="input !w-auto !py-1 text-xs" aria-label="Report" value={docId} onChange={(e) => setParams({ doc: e.target.value })}>
            {docs.data?.map((d) => (
              <option key={d.document_id} value={d.document_id}>
                {d.title}
              </option>
            ))}
          </select>
        }
      >
        {docs.error ? <ErrorBanner error={docs.error} /> : null}
        {docId ? <TableList documentId={docId} /> : docs.isLoading ? <Spinner /> : <Empty>No Finance documents yet.</Empty>}
      </Card>
      <MetricMap />
    </div>
  )
}

function TableList({ documentId }: { documentId: string }) {
  const qc = useQueryClient()
  const tables = useQuery({ queryKey: ['tables', documentId], queryFn: () => api.listTables(documentId) })
  const review = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: ReviewDecision }) => api.reviewTable(id, decision),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tables', documentId] }),
  })
  if (tables.isLoading) return <Spinner />
  if (tables.error) return <ErrorBanner error={tables.error} onRetry={() => tables.refetch()} />
  if (!tables.data?.length) return <Empty>No financial tables found in this document.</Empty>
  return (
    <>
      {review.error ? <div className="mb-3"><ErrorBanner error={review.error} /></div> : null}
      <Table head={['Table', 'Statement', 'Basis', 'Unit and scale', 'Pages', 'Checks', 'Status', '']}>
        {tables.data.map((t: FinTable) => (
          <tr key={t.table_id} className={t.status === 'NEEDS_REVIEW' ? 'bg-amber-50/60 dark:bg-amber-500/5' : ''}>
            <td className="td font-mono text-xs">{t.table_id}</td>
            <td className="td">{t.statement}</td>
            <td className="td text-xs">{t.basis}</td>
            <td className="td text-xs">{t.unit} · {SCALE_LABEL[t.scale] ?? `× ${t.scale}`}</td>
            <td className="td">
              {t.pages.map((p) => (
                <Link key={p} to={`/admin/documents/${documentId}/pages/${p}`} className="mr-1 text-indigo-600 hover:underline">
                  p.{p}
                </Link>
              ))}
            </td>
            <td className="td">
              <ul className="space-y-0.5 text-xs">
                {t.checks.map((c) => (
                  <li key={c.name}>
                    {c.passed ? '✅' : '❌'} {c.name}
                    {c.detail ? <span className="block pl-5 text-slate-500">{c.detail}</span> : null}
                  </li>
                ))}
              </ul>
            </td>
            <td className="td"><StatusBadge status={t.status} /></td>
            <td className="td">
              {t.status === 'NEEDS_REVIEW' ? (
                <div className="flex gap-1">
                  <button type="button" className="btn-primary !px-2 !py-0.5 text-xs" disabled={review.isLoading} onClick={() => review.mutate({ id: t.table_id, decision: 'APPROVE' })}>Approve</button>
                  <button type="button" className="btn-danger !px-2 !py-0.5 text-xs" disabled={review.isLoading} onClick={() => review.mutate({ id: t.table_id, decision: 'REJECT' })}>Reject</button>
                </div>
              ) : null}
            </td>
          </tr>
        ))}
      </Table>
    </>
  )
}

function MetricMap() {
  const [pendingOnly, setPendingOnly] = useState(false)
  const rows = useQuery({ queryKey: ['metric-map', pendingOnly], queryFn: () => api.listMetricMap(pendingOnly) })
  return (
    <Card
      title="Metric map"
      actions={
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={pendingOnly} onChange={(e) => setPendingOnly(e.target.checked)} />
          Pending only
        </label>
      }
    >
      <p className="mb-3 text-xs text-slate-500">An LLM proposes a metric for an unknown line label. No tool uses it until a person approves it.</p>
      {rows.error ? <ErrorBanner error={rows.error} /> : null}
      {rows.isLoading ? (
        <Spinner />
      ) : (
        <Table head={['Line label', 'Metric', 'Proposed by', 'Approved', '']} empty={!rows.data?.length}>
          {rows.data?.map((r) => <MetricRow key={r.line_label} row={r} />)}
        </Table>
      )}
    </Card>
  )
}

function MetricRow({ row }: { row: MetricMapRow }) {
  const qc = useQueryClient()
  const [metric, setMetric] = useState(row.metric)
  const approve = useMutation({
    mutationFn: () => api.approveMapping(row.line_label, metric.trim()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['metric-map'] }),
  })
  const pending = row.approved_by === null
  return (
    <tr>
      <td className="td">{row.line_label}</td>
      <td className="td">
        {pending ? (
          <input className="input !py-0.5 font-mono text-xs" aria-label={`Metric for ${row.line_label}`} value={metric} onChange={(e) => setMetric(e.target.value)} />
        ) : (
          <code>{row.metric}</code>
        )}
        {approve.error ? <div className="mt-1"><ErrorBanner error={approve.error} /></div> : null}
      </td>
      <td className="td"><Badge tone={row.proposed_by === 'LLM' ? 'violet' : 'slate'}>{row.proposed_by}</Badge></td>
      <td className="td text-xs">{pending ? <Badge tone="amber">pending</Badge> : `${row.approved_by} · ${row.approved_on}`}</td>
      <td className="td">
        {pending ? (
          <button type="button" className="btn-primary !px-2 !py-0.5 text-xs" disabled={!metric.trim() || approve.isLoading} onClick={() => approve.mutate()}>
            Approve
          </button>
        ) : null}
      </td>
    </tr>
  )
}
