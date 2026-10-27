import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api'
import type { UploadMetadata } from '../../api/types'
import { OcrUsage } from '../../components/OcrUsage'
import { Card, ErrorBanner, PageHeader, Spinner, StatusBadge, Table } from '../../components/ui'
import { ALLOWED_EXTENSIONS, checkUpload, MAX_UPLOAD_MB, type UploadProblem } from '../../lib/upload'

const CATEGORIES = ['Policy', 'SOP', 'HR', 'Procurement', 'Finance']
const EMPTY_META: UploadMetadata = { title: '', category: '', version: '1.0', effective_date: '', doc_key: '' }

export function DocumentsPage() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: api.listJobs,
    refetchInterval: (data) => (data?.some((j) => j.status === 'QUEUED' || j.status === 'RUNNING') ? 1000 : false),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  })
  const docs = useQuery({ queryKey: ['documents', statusFilter, categoryFilter], queryFn: () => api.listDocuments({ status: statusFilter || undefined, category: categoryFilter || undefined }) })
  const activeJobs = jobs.data?.filter((j) => j.status !== 'DONE') ?? []

  return (
    <div className="space-y-5">
      <PageHeader title="Documents" subtitle="Upload approved documents, follow ingestion and review pages that need a person." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_1fr]">
        <UploadForm onUploaded={() => qc.invalidateQueries({ queryKey: ['jobs'] })} />
        <Card title={`Ingestion jobs${activeJobs.length ? ` (${activeJobs.length} active)` : ''}`}>
          {jobs.error ? <ErrorBanner error={jobs.error} /> : null}
          {jobs.data?.length ? (
            <ul className="space-y-3">
              {jobs.data.slice(0, 6).map((j) => (
                <li key={j.job_id} className="text-sm">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <Link to={`/admin/documents/${j.document_id}`} className="truncate font-medium hover:text-indigo-600">
                      {j.title}
                    </Link>
                    <span className="flex items-center gap-2 text-xs text-slate-500">
                      <code>{j.stage}</code>
                      <StatusBadge status={j.status} />
                    </span>
                  </div>
                  <div className="h-2 rounded bg-slate-100 dark:bg-slate-800" role="progressbar" aria-valuenow={j.done} aria-valuemax={j.total} aria-label={`${j.title} progress`}>
                    <div className="h-2 rounded bg-indigo-500 transition-all" style={{ width: `${(j.done / Math.max(1, j.total)) * 100}%` }} />
                  </div>
                  <p className="mt-0.5 text-right text-[11px] text-slate-500">
                    {j.done} of {j.total} pages
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">No jobs yet. Upload a document to start one.</p>
          )}
        </Card>
      </div>

      <Card
        title="Document list"
        actions={
          <div className="flex gap-2">
            <select className="input !w-auto !py-1 text-xs" aria-label="Filter by category" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
              <option value="">All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <select className="input !w-auto !py-1 text-xs" aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              {['QUEUED', 'PROCESSING', 'INDEXED', 'PARTIAL_REVIEW', 'FAILED'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
        }
      >
        {docs.error ? <ErrorBanner error={docs.error} onRetry={() => docs.refetch()} /> : null}
        {docs.isLoading ? (
          <Spinner />
        ) : (
          <Table head={['Title', 'Key', 'Category', 'Version', 'Effective', 'Status', 'Pages', 'Chunks', 'OCR tokens and cost']} empty={!docs.data?.length}>
            {docs.data?.map((d) => (
              <tr key={d.document_id}>
                <td className="td">
                  <Link to={`/admin/documents/${d.document_id}`} className="font-medium text-indigo-600 hover:underline">
                    {d.title}
                  </Link>
                </td>
                <td className="td font-mono text-xs">{d.doc_key}</td>
                <td className="td">{d.category}</td>
                <td className="td">v{d.version}</td>
                <td className="td whitespace-nowrap">{d.effective_date}</td>
                <td className="td"><StatusBadge status={d.status} /></td>
                <td className="td tabular-nums">{d.pages}</td>
                <td className="td tabular-nums">{d.chunks}</td>
                <td className="td tabular-nums">
                  <OcrUsage doc={d} />
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  )
}

function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [meta, setMeta] = useState<UploadMetadata>(EMPTY_META)
  const [problems, setProblems] = useState<UploadProblem[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const mutation = useMutation({
    mutationFn: () => api.uploadDocument(file as File, { ...meta, doc_key: meta.doc_key || undefined }),
    onSuccess: () => {
      setFile(null)
      setMeta(EMPTY_META)
      if (fileRef.current) fileRef.current.value = ''
      onUploaded()
    },
  })
  const problemFor = (field: string) => problems.find((p) => p.field === field)?.problem
  const set = (patch: Partial<UploadMetadata>) => setMeta((m) => ({ ...m, ...patch }))

  return (
    <Card title="Upload a document">
      <form
        className="space-y-3"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          const found = checkUpload(file, meta)
          setProblems(found)
          if (found.length === 0) mutation.mutate()
        }}
      >
        <Field label={`File (${ALLOWED_EXTENSIONS.join(', ')}; max ${MAX_UPLOAD_MB} MB)`} problem={problemFor('file')}>
          <input
            ref={fileRef}
            type="file"
            aria-label="File"
            accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(',')}
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700 dark:file:bg-indigo-500/20 dark:file:text-indigo-200"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null
              setFile(f)
              if (f && !meta.title) set({ title: f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ') })
            }}
          />
        </Field>
        <Field label="Title" problem={problemFor('title')}>
          <input className="input" aria-label="Title" value={meta.title} onChange={(e) => set({ title: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Category" problem={problemFor('category')}>
            <select className="input" aria-label="Category" value={meta.category} onChange={(e) => set({ category: e.target.value })}>
              <option value="">Choose</option>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
          <Field label="Version" problem={problemFor('version')}>
            <input className="input" aria-label="Version" value={meta.version} onChange={(e) => set({ version: e.target.value })} />
          </Field>
          <Field label="Effective date" problem={problemFor('effective_date')}>
            <input className="input" type="date" aria-label="Effective date" value={meta.effective_date} onChange={(e) => set({ effective_date: e.target.value })} />
          </Field>
          <Field label="Document key (optional)" problem={problemFor('doc_key')}>
            <input className="input" aria-label="Document key" placeholder="travel-policy" value={meta.doc_key} onChange={(e) => set({ doc_key: e.target.value })} />
          </Field>
        </div>
        <p className="text-xs text-slate-500">Use the same document key for a new version of an existing document. The assistant then shows conflicts between versions.</p>
        {mutation.error ? <ErrorBanner error={mutation.error} /> : null}
        {mutation.isSuccess ? <p className="text-sm text-emerald-600">Upload accepted. The job is in the list.</p> : null}
        <button type="submit" className="btn-primary w-full" disabled={mutation.isLoading}>
          {mutation.isLoading ? 'Uploading' : 'Upload'}
        </button>
      </form>
    </Card>
  )
}

function Field({ label, problem, children }: { label: string; problem?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {problem ? <span className="mt-1 block text-xs text-rose-600">{problem}</span> : null}
    </label>
  )
}
