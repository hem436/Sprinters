import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api'
import { Badge, Card, ErrorBanner, KeyValue, PageHeader, Spinner, StatusBadge, Table } from '../../components/ui'
import { formatCost, formatMs } from '../../lib/format'

export function DocumentDetailPage() {
  const { documentId = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => api.getDocument(documentId),
    refetchInterval: (d) => (d && (d.status === 'QUEUED' || d.status === 'PROCESSING') ? 1500 : false),
  })
  const reindex = useMutation({ mutationFn: () => api.reindexDocument(documentId), onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }) })
  const remove = useMutation({
    mutationFn: () => api.deleteDocument(documentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents'] })
      navigate('/admin/documents')
    },
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBanner error={error} onRetry={() => refetch()} />
  if (!data) return null
  // The report is null until extraction finishes; show the document with an empty page list meanwhile.
  const r = data.report ?? { document_id: data.document_id, status: data.status, pages: [], chunks: data.chunks, ocr_cost_usd: data.ocr_cost_usd, duration_ms: 0 }
  const needsReview = r.pages.filter((p) => p.status === 'NEEDS_REVIEW').length

  return (
    <div className="space-y-5">
      <PageHeader
        title={`${data.title} v${data.version}`}
        subtitle={<code>{data.document_id}</code>}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to="/admin/documents" className="btn-secondary">Back</Link>
            {data.category === 'Finance' ? <Link to={`/admin/finance?doc=${data.document_id}`} className="btn-secondary">Financial tables</Link> : null}
            <button type="button" className="btn-secondary" onClick={() => reindex.mutate()} disabled={reindex.isLoading}>
              {reindex.isSuccess ? 'Re-index queued' : 'Re-index'}
            </button>
            {confirmDelete ? (
              <>
                <button type="button" className="btn-danger" onClick={() => remove.mutate()} disabled={remove.isLoading}>Confirm delete</button>
                <button type="button" className="btn-secondary" onClick={() => setConfirmDelete(false)}>Cancel</button>
              </>
            ) : (
              <button type="button" className="btn-secondary text-rose-600" onClick={() => setConfirmDelete(true)}>Delete</button>
            )}
          </div>
        }
      />
      {reindex.error ? <ErrorBanner error={reindex.error} /> : null}
      {remove.error ? <ErrorBanner error={remove.error} /> : null}
      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        <Card title="Extraction report">
          <KeyValue
            items={[
              ['Status', <StatusBadge key="s" status={r.status} />],
              ['Document key', <code key="k">{data.doc_key}</code>],
              ['Category', data.category],
              ['Effective date', data.effective_date],
              ['Pages', data.pages],
              ['Chunks', r.chunks],
              ['Needs review', needsReview ? <Badge key="n" tone="amber">{needsReview} pages</Badge> : 'none'],
              ['OCR cost', formatCost(r.ocr_cost_usd)],
              ['Duration', formatMs(r.duration_ms)],
            ]}
          />
        </Card>
        <Card title="Pages">
          {data.report ? null : <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">Extraction is still running. The page list appears when it finishes.</p>}
          <p className="mb-3 text-xs text-slate-500">A NEEDS_REVIEW page is not searchable until an admin approves it (contract 10 rule X7).</p>
          <Table head={['Page', 'Class', 'Method', 'Quality', 'Flags', 'Status', 'OCR', '']} empty={r.pages.length === 0}>
            {r.pages.map((p) => (
              <tr key={p.page} className={p.status === 'NEEDS_REVIEW' ? 'bg-amber-50/60 dark:bg-amber-500/5' : ''}>
                <td className="td tabular-nums">{p.page}</td>
                <td className="td text-xs">{p.class}</td>
                <td className="td font-mono text-xs">{p.method}</td>
                <td className="td tabular-nums">{p.quality.toFixed(2)}</td>
                <td className="td">
                  <div className="flex flex-wrap gap-1">{p.flags.map((f) => <Badge key={f} tone={f === 'INJECTION_SUSPECT' ? 'red' : 'amber'}>{f}</Badge>)}</div>
                </td>
                <td className="td"><StatusBadge status={p.status} /></td>
                <td className="td text-xs">{p.ocr ? `${p.ocr.model} · ${formatCost(p.ocr.cost_usd)}` : ''}</td>
                <td className="td">
                  <Link to={`/admin/documents/${data.document_id}/pages/${p.page}`} className="text-xs text-indigo-600 hover:underline">
                    {p.status === 'NEEDS_REVIEW' ? 'Review' : 'Preview'}
                  </Link>
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </div>
  )
}
