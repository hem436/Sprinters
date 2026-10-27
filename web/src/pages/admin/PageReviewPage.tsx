import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api'
import type { ReviewDecision } from '../../api/types'
import { Badge, Card, ErrorBanner, KeyValue, PageHeader, Spinner, StatusBadge } from '../../components/ui'

/** Page image beside the extracted text, with approve or reject (WP-UI2). */
export function PageReviewPage() {
  const { documentId = '', page = '1' } = useParams()
  const n = Number(page)
  const qc = useQueryClient()
  const [comment, setComment] = useState('')
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['page', documentId, n], queryFn: () => api.getPage(documentId, n) })
  const review = useMutation({
    mutationFn: (decision: ReviewDecision) => api.reviewPage(documentId, n, decision, comment.trim() || undefined),
    onSuccess: (updated) => {
      qc.setQueryData(['page', documentId, n], updated)
      qc.invalidateQueries({ queryKey: ['document', documentId] })
      qc.invalidateQueries({ queryKey: ['documents'] })
    },
  })

  return (
    <div>
      <PageHeader
        title={`Page ${n}`}
        subtitle={<code>{documentId}</code>}
        actions={<Link to={`/admin/documents/${documentId}`} className="btn-secondary">Back to document</Link>}
      />
      {error ? <ErrorBanner error={error} onRetry={() => refetch()} /> : null}
      {isLoading ? <Spinner /> : null}
      {data ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Page image">
            {data.image_url ? (
              <img src={data.image_url} alt={`Render of page ${n}`} className="mx-auto max-h-[75vh] w-auto rounded border border-slate-200 shadow-sm dark:border-slate-700" />
            ) : (
              <p className="text-sm text-slate-500">No image.</p>
            )}
          </Card>
          <div className="space-y-5">
            <Card title="Extraction">
              <KeyValue
                items={[
                  ['Status', <StatusBadge key="s" status={data.status} />],
                  ['Class', data.class],
                  ['Method', <code key="m">{data.method}</code>],
                  ['Quality', data.quality.toFixed(2)],
                  ['Flags', data.flags.length ? <span key="f" className="flex flex-wrap gap-1">{data.flags.map((f) => <Badge key={f} tone="amber">{f}</Badge>)}</span> : 'none'],
                ]}
              />
              {data.flags.includes('INJECTION_SUSPECT') ? (
                <p className="mt-3 rounded bg-rose-50 px-2 py-1 text-xs text-rose-800 dark:bg-rose-500/10 dark:text-rose-200">
                  This page holds text that looks like an instruction to the model. It is treated as data only. Its use is logged as a safety event.
                </p>
              ) : null}
            </Card>
            <Card title="Extracted text">
              <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 font-mono text-xs dark:bg-slate-800/60">{data.text}</pre>
            </Card>
            {data.status === 'NEEDS_REVIEW' ? (
              <Card title="Review">
                <p className="mb-2 text-sm text-slate-600 dark:text-slate-300">Compare the text with the image. Check every number. Approve to make this page searchable.</p>
                <textarea className="input mb-3" rows={2} aria-label="Review comment" placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
                <div className="flex gap-2">
                  <button type="button" className="btn-primary" disabled={review.isLoading} onClick={() => review.mutate('APPROVE')}>Approve</button>
                  <button type="button" className="btn-danger" disabled={review.isLoading} onClick={() => review.mutate('REJECT')}>Reject</button>
                </div>
                {review.error ? <div className="mt-3"><ErrorBanner error={review.error} /></div> : null}
              </Card>
            ) : review.isSuccess ? (
              <p className="text-sm text-emerald-600">Review saved. The page is now {data.status}.</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
