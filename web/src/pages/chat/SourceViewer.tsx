import { Link } from 'react-router-dom'
import type { Citation, ToolResult } from '../../api/types'
import { toAppPath } from '../../components/CitationChip'
import { useAuth } from '../../hooks/useAuth'

const meta = 'inline-flex items-center rounded-full border border-slate-300 px-2.5 py-0.5 text-xs dark:border-slate-600'

/** Right-hand panel of the chat, like Verba's document view: the passage behind the selected source. */
export function SourceViewer({ citation, toolResult }: { citation: Citation | null; toolResult?: ToolResult }) {
  const { user } = useAuth()

  if (!citation) {
    return (
      <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 p-8 text-center text-sm text-slate-500">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
          <path d="M14 3v5h5M9 13h6M9 17h4" />
        </svg>
        <p className="m-0">Sources appear here. Ask a question, then pick a source under the answer.</p>
      </div>
    )
  }

  if (citation.kind === 'tool') {
    const rows = toolResult?.rows ?? []
    return (
      <div className="flex flex-col">
        <div className="flex flex-col gap-2 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <p className="label m-0">Source {citation.id} · business data</p>
          <h2 className="m-0 font-mono text-lg font-semibold">{citation.tool}</h2>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(citation.args).map(([k, v]) => (
              <span key={k} className={`${meta} font-mono`}>
                {k}: {String(v)}
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-3 px-5 py-4 text-sm">
          {toolResult?.summary ? <p className="m-0">{toolResult.summary}</p> : null}
          {rows.length > 0 ? (
            <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-slate-50 dark:bg-slate-800/60">
                  <tr>
                    {Object.keys(rows[0]).map((k) => (
                      <th key={k} className="px-3 py-2 font-semibold">
                        {k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                      {Object.values(row).map((v, j) => (
                        <td key={j} className="px-3 py-2">
                          {String(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="m-0 text-xs text-slate-500">
            From an approved, read-only query. {citation.row_count} {citation.row_count === 1 ? 'row' : 'rows'}.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-2 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <p className="label m-0">Source {citation.id}</p>
        <h2 className="m-0 text-lg font-semibold">{citation.title}</h2>
        <div className="flex flex-wrap gap-1.5">
          <span className={meta}>
            v{citation.version}
            {citation.current === true ? ' · current' : citation.current === false ? ' · older version' : ''}
          </span>
          <span className={meta}>Page {citation.page}</span>
          {citation.section ? <span className={meta}>§ {citation.section}</span> : null}
          <span className={`${meta} font-mono`}>{citation.method}</span>
        </div>
      </div>
      <div className="flex flex-col gap-3 px-5 py-4 text-sm leading-relaxed">
        {citation.snippet ? (
          <blockquote className="m-0 rounded-xl bg-indigo-50 px-4 py-3 text-slate-800 dark:bg-indigo-500/10 dark:text-slate-100">{citation.snippet}</blockquote>
        ) : (
          <p className="m-0 text-slate-500">The passage text is not available for this source.</p>
        )}
        {citation.method === 'ocr' ? <p className="m-0 text-xs text-slate-500">This text was read from a scanned page.</p> : null}
      </div>
      {user ? (
        <div className="border-t border-slate-200 px-5 py-3 text-sm dark:border-slate-800">
          <Link to={toAppPath(citation.url)} className="text-indigo-600 hover:underline dark:text-indigo-300">
            Open the page
          </Link>
        </div>
      ) : null}
    </div>
  )
}
