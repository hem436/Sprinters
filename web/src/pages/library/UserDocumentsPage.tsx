import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api'
import type { LibraryDocument } from '../../api/types'
import { ErrorBanner, Spinner } from '../../components/ui'

// User view of the approved documents, like Verba's document explorer: search on the left, a reader on the right.

const CATEGORIES = ['Policy', 'SOP', 'HR', 'Procurement', 'Finance']

const chip = (on: boolean) =>
  `inline-flex min-h-[32px] items-center rounded-full border px-3 text-xs font-medium ${
    on
      ? 'border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-900'
      : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800'
  }`

const meta = 'inline-flex items-center rounded-full border border-slate-300 px-2.5 py-0.5 text-xs dark:border-slate-600'

/** The newest effective date per doc_key is the current version; documents without a key stand alone. */
export function versionLabels(docs: LibraryDocument[]): Map<string, 'current' | 'older' | null> {
  const newest = new Map<string, string>()
  const count = new Map<string, number>()
  for (const d of docs) {
    if (!d.doc_key) continue
    count.set(d.doc_key, (count.get(d.doc_key) ?? 0) + 1)
    if ((newest.get(d.doc_key) ?? '') < d.effective_date) newest.set(d.doc_key, d.effective_date)
  }
  return new Map(
    docs.map((d) => [
      d.document_id,
      !d.doc_key || (count.get(d.doc_key) ?? 0) < 2 ? null : newest.get(d.doc_key) === d.effective_date ? 'current' : 'older',
    ]),
  )
}

function versionText(d: LibraryDocument, label: 'current' | 'older' | null | undefined): string {
  return `v${d.version}${label === 'current' ? ' · current' : label === 'older' ? ' · older version' : ''}`
}

export function UserDocumentsPage() {
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const docs = useQuery({ queryKey: ['library', category], queryFn: () => api.listLibrary(category || undefined) })

  const labels = useMemo(() => versionLabels(docs.data ?? []), [docs.data])
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    const all = docs.data ?? []
    return q ? all.filter((d) => `${d.title} ${d.doc_key} ${d.category}`.toLowerCase().includes(q)) : all
  }, [docs.data, search])

  const selectedId = params.get('doc') ?? shown[0]?.document_id ?? ''
  const selected = docs.data?.find((d) => d.document_id === selectedId)
  const page = Math.max(1, Number(params.get('page')) || 1)

  const open = (documentId: string, n = 1) => setParams({ doc: documentId, page: String(n) })

  return (
    <div className="flex flex-wrap items-start gap-4">
      <section aria-label="Document list" className="card flex min-w-0 flex-[1_1_300px] flex-col gap-3 !rounded-2xl p-4 lg:max-w-[380px]">
        <label className="block">
          <span className="sr-only">Search documents</span>
          <input
            className="input !min-h-[40px] !rounded-full !px-4"
            placeholder="Search documents"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Category">
          {['', ...CATEGORIES].map((c) => (
            <button key={c || 'all'} type="button" aria-pressed={category === c} className={chip(category === c)} onClick={() => setCategory(c)}>
              {c || 'All'}
            </button>
          ))}
        </div>
        {docs.error ? <ErrorBanner error={docs.error} onRetry={() => docs.refetch()} /> : null}
        {docs.isLoading ? <Spinner /> : null}
        {docs.data && shown.length === 0 ? <p className="m-0 py-6 text-center text-sm text-slate-500">No documents match.</p> : null}
        <nav aria-label="Documents" className="-mx-1 flex flex-col gap-0.5">
          {shown.map((d) => {
            const on = d.document_id === selectedId
            return (
              <button
                key={d.document_id}
                type="button"
                aria-current={on ? 'true' : undefined}
                onClick={() => open(d.document_id)}
                className={`flex flex-col items-start gap-0.5 rounded-xl px-3 py-2.5 text-left ${on ? 'bg-indigo-50 dark:bg-indigo-500/15' : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'}`}
              >
                <strong className="text-sm">{d.title}</strong>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {d.category} · {versionText(d, labels.get(d.document_id))} · {d.pages} {d.pages === 1 ? 'page' : 'pages'}
                </span>
              </button>
            )
          })}
        </nav>
      </section>

      <section aria-label="Document viewer" className="card min-w-0 flex-[999_1_520px] !rounded-2xl">
        {selected ? <Reader doc={selected} label={labels.get(selected.document_id)} page={Math.min(page, Math.max(1, selected.pages))} onPage={(n) => open(selected.document_id, n)} /> : (
          <p className="m-0 p-10 text-center text-sm text-slate-500">{docs.isLoading ? 'Loading documents…' : 'Pick a document to read it.'}</p>
        )}
      </section>
    </div>
  )
}

function Reader({ doc, label, page, onPage }: { doc: LibraryDocument; label: 'current' | 'older' | null | undefined; page: number; onPage: (n: number) => void }) {
  const content = useQuery({
    queryKey: ['library-page', doc.document_id, page],
    queryFn: () => api.getLibraryPage(doc.document_id, page),
    retry: false,
  })
  const missing = content.error instanceof ApiError && content.error.status === 404
  const iconBtn =
    'inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'

  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <h1 className="m-0 mr-1 text-lg font-semibold">{doc.title}</h1>
        <span className={meta}>{versionText(doc, label)}</span>
        {doc.effective_date ? <span className={meta}>Effective {doc.effective_date}</span> : null}
        <Link
          to={`/chat?doc_key=${encodeURIComponent(doc.doc_key)}`}
          className="ml-auto inline-flex min-h-[34px] items-center rounded-full border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Ask about this document
        </Link>
      </div>
      {label === 'older' ? (
        <p className="m-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          This is an older version. A newer version of this document exists.
        </p>
      ) : null}
      <div className="min-h-[320px] px-6 py-5 text-sm leading-relaxed">
        <p className="label m-0 mb-3">Page {page}</p>
        {content.isLoading ? <Spinner /> : null}
        {missing ? <p className="m-0 text-slate-500">This page is not available to read yet. It may be waiting for an admin review.</p> : null}
        {content.error && !missing ? <ErrorBanner error={content.error} onRetry={() => content.refetch()} /> : null}
        {content.data ? <div className="max-w-3xl whitespace-pre-line">{content.data.text}</div> : null}
      </div>
      <div className="flex items-center gap-2 border-t border-slate-200 px-5 py-3 text-sm dark:border-slate-800">
        <button type="button" className={iconBtn} aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <span className="text-slate-500 dark:text-slate-400">
          Page {page} of {doc.pages}
        </span>
        <button type="button" className={iconBtn} aria-label="Next page" disabled={page >= doc.pages} onClick={() => onPage(page + 1)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </div>
    </div>
  )
}
