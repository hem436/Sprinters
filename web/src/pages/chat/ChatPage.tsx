import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import type { Citation, ConfigId, QueryFilters, QueryResponse } from '../../api/types'
import { useSession } from '../../hooks/useSession'
import { ChatMessage, type Turn } from './ChatMessage'
import { SourceViewer } from './SourceViewer'

const CATEGORIES = ['Policy', 'SOP', 'HR', 'Procurement', 'Finance']

const SUGGESTIONS = [
  'What is the per diem in Mumbai?',
  'What does POL-HR-014 say about laptops?',
  'Total travel spend of P-104 in FY2026-27?',
  'Is P-104 over its travel budget, and what does the policy say about overruns?',
  "What is the CEO's salary?",
]

type Tab = 'chat' | 'filters'

function firstSource(r: QueryResponse): Citation | undefined {
  return r.citations.find((c) => c.kind === 'document') ?? r.citations[0]
}

export function ChatPage() {
  const { sessionId, reset } = useSession()
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [filters, setFilters] = useState<QueryFilters>({})
  const [configId, setConfigId] = useState<ConfigId>('B')
  const [stream, setStream] = useState(true)
  const [tab, setTab] = useState<Tab>('chat')
  const [selected, setSelected] = useState<{ turnId: string; citationId: string } | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const busy = turns.some((t) => t.status === 'streaming')

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [turns])

  useEffect(() => () => abortRef.current?.abort(), [])

  const update = (id: string, patch: Partial<Turn> | ((t: Turn) => Partial<Turn>)) =>
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...(typeof patch === 'function' ? patch(t) : patch) } : t)))

  async function ask(text: string) {
    const q = text.trim()
    if (!q || busy) return
    const id = `t${Date.now()}`
    setTurns((all) => [...all, { id, question: q, status: 'streaming', partial: '', citations: [] }])
    setQuestion('')
    setTab('chat')
    const controller = new AbortController()
    abortRef.current = controller
    const cleanFilters: QueryFilters = {
      ...(filters.category ? { category: filters.category } : {}),
      ...(filters.doc_key?.trim() ? { doc_key: filters.doc_key.trim() } : {}),
      ...(filters.current_only ? { current_only: true } : {}),
    }
    const req = { question: q, session_id: sessionId, config_id: configId, ...(Object.keys(cleanFilters).length ? { filters: cleanFilters } : {}) }
    try {
      const response = stream
        ? await api.queryStream(
            req,
            (ev) => {
              if (ev.event === 'status') update(id, { stage: ev.data.stage })
              else if (ev.event === 'citations') update(id, { citations: ev.data.citations })
              else if (ev.event === 'token') update(id, (t) => ({ partial: t.partial + ev.data.text }))
            },
            controller.signal,
          )
        : await api.query(req, controller.signal)
      update(id, { status: 'done', response })
      const first = firstSource(response)
      if (first) setSelected({ turnId: id, citationId: first.id })
    } catch (err) {
      if ((err as Error).name === 'AbortError') update(id, { status: 'stopped' })
      else update(id, { status: 'error', error: err })
    }
  }

  function newConversation() {
    abortRef.current?.abort()
    setTurns([])
    setSelected(null)
    reset()
  }

  const { citation, toolResult } = useMemo(() => {
    const turn = turns.find((t) => t.id === selected?.turnId)
    const all = turn?.response?.citations ?? turn?.citations ?? []
    const c = all.find((x) => x.id === selected?.citationId) ?? null
    return { citation: c, toolResult: c?.kind === 'tool' ? turn?.response?.tool_results.find((t) => t.id === c.id) : undefined }
  }, [turns, selected])

  const activeFilters = [filters.category, filters.doc_key?.trim(), filters.current_only ? 'current only' : ''].filter(Boolean)
  const tabCls = (on: boolean) =>
    `inline-flex min-h-[34px] items-center rounded-full px-3.5 text-sm font-medium ${on ? 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-white' : 'text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/60'}`

  return (
    <div className="flex flex-wrap items-stretch gap-4">
      <section aria-label="Chat" className="card flex min-h-[70vh] min-w-0 flex-[3_1_560px] flex-col !rounded-2xl">
        <div className="flex items-center gap-1.5 border-b border-slate-200 px-3 py-2.5 dark:border-slate-800" role="tablist">
          <button type="button" role="tab" aria-selected={tab === 'chat'} className={tabCls(tab === 'chat')} onClick={() => setTab('chat')}>
            Chat
          </button>
          <button type="button" role="tab" aria-selected={tab === 'filters'} className={tabCls(tab === 'filters')} onClick={() => setTab('filters')}>
            Filters{activeFilters.length ? ` (${activeFilters.length})` : ''}
          </button>
          <button type="button" className={`${tabCls(false)} ml-auto`} onClick={newConversation}>
            New chat
          </button>
        </div>

        {tab === 'filters' ? (
          <div className="grid flex-1 content-start gap-4 p-5 sm:grid-cols-2" role="tabpanel" aria-label="Filters">
            <label className="block">
              <span className="label">Category</span>
              <select className="input" value={filters.category ?? ''} onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value || undefined }))}>
                <option value="">All</option>
                {CATEGORIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">Document key</span>
              <input className="input" placeholder="e.g. travel-policy" value={filters.doc_key ?? ''} onChange={(e) => setFilters((f) => ({ ...f, doc_key: e.target.value }))} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={!!filters.current_only} onChange={(e) => setFilters((f) => ({ ...f, current_only: e.target.checked }))} />
              Current version only
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={stream} onChange={(e) => setStream(e.target.checked)} />
              Stream answer
            </label>
            <label className="block">
              <span className="label">Configuration</span>
              <select className="input" value={configId} onChange={(e) => setConfigId(e.target.value as ConfigId)}>
                <option value="B">B: hybrid + rerank</option>
                <option value="A">A: vector only</option>
              </select>
            </label>
            <p className="m-0 self-end text-xs text-slate-500">Session {sessionId}</p>
          </div>
        ) : (
          <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-5" aria-live="polite" role="tabpanel" aria-label="Conversation">
            {turns.length === 0 ? (
              <div className="m-auto flex max-w-lg flex-col items-center gap-3 py-10 text-center">
                <h1 className="m-0 text-xl font-semibold">Ask the knowledge base</h1>
                <p className="m-0 text-sm text-slate-500 dark:text-slate-400">Answers come only from approved documents and business data, with sources.</p>
                <div className="mt-2 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" className="btn-secondary !rounded-full text-xs" onClick={() => ask(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              turns.map((t) => (
                <ChatMessage
                  key={t.id}
                  turn={t}
                  selectedId={selected?.turnId === t.id ? selected.citationId : null}
                  onSelect={(citationId) => setSelected({ turnId: t.id, citationId })}
                  onRetry={() => ask(t.question)}
                />
              ))
            )}
            <div ref={bottomRef} />
          </div>
        )}

        <form
          className="m-3 mt-0 flex items-end gap-2 rounded-3xl border border-slate-300 bg-white p-1.5 pl-4 dark:border-slate-700 dark:bg-slate-900"
          onSubmit={(e) => {
            e.preventDefault()
            ask(question)
          }}
        >
          <textarea
            className="min-h-[40px] flex-1 resize-none border-0 bg-transparent py-2 text-sm focus:outline-none"
            rows={1}
            maxLength={2000}
            aria-label="Question"
            placeholder="Ask about a policy, a procedure or project data…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                ask(question)
              }
            }}
          />
          {busy ? (
            <button type="button" className="btn-secondary !min-h-[40px] !rounded-full" onClick={() => abortRef.current?.abort()}>
              Stop
            </button>
          ) : (
            <button type="submit" aria-label="Ask" className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40" disabled={!question.trim()}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
          )}
        </form>
      </section>

      <aside aria-label="Source viewer" className="card min-w-0 flex-[2_1_360px] self-start overflow-hidden !rounded-2xl lg:sticky lg:top-4">
        <SourceViewer citation={citation} toolResult={toolResult} />
      </aside>
    </div>
  )
}
