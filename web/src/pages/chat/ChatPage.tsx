import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { ConfigId, QueryFilters } from '../../api/types'
import { useSession } from '../../hooks/useSession'
import { ChatMessage, type Turn } from './ChatMessage'

const CATEGORIES = ['Policy', 'SOP', 'HR', 'Procurement', 'Finance']

const SUGGESTIONS = [
  'What is the per diem in Mumbai?',
  'and Delhi?',
  'What does POL-HR-014 say about laptops?',
  'Total travel spend of P-104 in FY2026-27?',
  'Is P-104 over its travel budget, and what does the policy say about overruns?',
  "What is the CEO's salary?",
]

export function ChatPage() {
  const { sessionId, reset } = useSession()
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [filters, setFilters] = useState<QueryFilters>({})
  const [configId, setConfigId] = useState<ConfigId>('B')
  const [stream, setStream] = useState(true)
  const [showFilters, setShowFilters] = useState(false)
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
    } catch (err) {
      if ((err as Error).name === 'AbortError') update(id, { status: 'stopped' })
      else update(id, { status: 'error', error: err })
    }
  }

  function newConversation() {
    abortRef.current?.abort()
    setTurns([])
    reset()
  }

  const activeFilters = [filters.category, filters.doc_key?.trim(), filters.current_only ? 'current only' : ''].filter(Boolean)

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Ask the knowledge base</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Answers come only from approved documents and business data, with sources.</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn-secondary" onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters}>
            Filters{activeFilters.length ? ` (${activeFilters.length})` : ''}
          </button>
          <button type="button" className="btn-secondary" onClick={newConversation}>
            New conversation
          </button>
        </div>
      </div>

      {showFilters ? (
        <div className="card grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
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
          <label className="flex items-end gap-2 pb-1.5 text-sm">
            <input type="checkbox" checked={!!filters.current_only} onChange={(e) => setFilters((f) => ({ ...f, current_only: e.target.checked }))} />
            Current version only
          </label>
          <label className="block">
            <span className="label">Configuration</span>
            <select className="input" value={configId} onChange={(e) => setConfigId(e.target.value as ConfigId)}>
              <option value="B">B: hybrid + rerank</option>
              <option value="A">A: vector only</option>
            </select>
          </label>
          <label className="flex items-end gap-2 pb-1.5 text-sm">
            <input type="checkbox" checked={stream} onChange={(e) => setStream(e.target.checked)} />
            Stream answer
          </label>
        </div>
      ) : null}

      <div className="flex min-h-[40vh] flex-col gap-6" aria-live="polite">
        {turns.length === 0 ? (
          <div className="card p-6 text-center">
            <p className="mb-3 text-sm text-slate-500">Try one of these questions:</p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="btn-secondary text-xs" onClick={() => ask(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((t) => <ChatMessage key={t.id} turn={t} onRetry={() => ask(t.question)} />)
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="card sticky bottom-4 flex items-end gap-2 p-2"
        onSubmit={(e) => {
          e.preventDefault()
          ask(question)
        }}
      >
        <textarea
          className="input min-h-[44px] flex-1 resize-none border-0 focus:ring-0"
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
          <button type="button" className="btn-secondary" onClick={() => abortRef.current?.abort()}>
            Stop
          </button>
        ) : (
          <button type="submit" className="btn-primary" disabled={!question.trim()}>
            Ask
          </button>
        )}
      </form>
      <p className="-mt-2 text-center text-[11px] text-slate-400">
        Session {sessionId}
        {activeFilters.length ? ` · Filters: ${activeFilters.join(', ')}` : ''} · Config {configId}
      </p>
    </div>
  )
}
