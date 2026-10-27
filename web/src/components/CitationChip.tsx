import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Citation } from '../api/types'

/** The API gives `/documents/{id}/pages/{n}`. The app shows that page under /admin. */
export function toAppPath(url: string): string {
  return url.startsWith('/documents/') ? `/admin${url}` : url
}

/** One chip per citation. Document chips show title, version, page, section and extraction method (WP-UI1). */
export function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)

  if (citation.kind === 'tool') {
    return (
      <span className="relative inline-flex">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="inline-flex items-center gap-1.5 rounded-full border border-violet-300 bg-violet-50 px-2.5 py-1 text-xs text-violet-900 hover:bg-violet-100 dark:border-violet-500/40 dark:bg-violet-500/10 dark:text-violet-200"
        >
          <span className="font-semibold">{citation.id}</span>
          <span className="font-mono">{citation.tool}</span>
          <span className="opacity-70">· {citation.row_count} {citation.row_count === 1 ? 'row' : 'rows'}</span>
        </button>
        {open ? (
          <span className="absolute left-0 top-full z-10 mt-1 w-72 rounded-lg border border-slate-200 bg-white p-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-800">
            <span className="mb-1 block font-semibold">Tool arguments</span>
            <code className="block whitespace-pre-wrap break-all">{JSON.stringify(citation.args, null, 2)}</code>
          </span>
        ) : null}
      </span>
    )
  }

  return (
    <Link
      to={toAppPath(citation.url)}
      title={`${citation.title} v${citation.version}, page ${citation.page}${citation.section ? `, ${citation.section}` : ''}`}
      className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-sky-300 bg-sky-50 px-2.5 py-1 text-xs text-sky-900 hover:bg-sky-100 dark:border-sky-500/40 dark:bg-sky-500/10 dark:text-sky-200"
    >
      <span className="font-semibold">{citation.id}</span>
      <span className="truncate">{citation.title}</span>
      <span className="opacity-70">v{citation.version}</span>
      <span className="opacity-70">p.{citation.page}</span>
      {citation.section ? <span className="hidden truncate opacity-70 sm:inline">§ {citation.section}</span> : null}
      <span className="rounded bg-white/70 px-1 font-mono text-[10px] dark:bg-black/20">{citation.method}</span>
    </Link>
  )
}
