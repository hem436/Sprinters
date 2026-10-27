import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import type { ToolInfo } from '../../api/types'
import { Badge, Card, ErrorBanner, KeyValue, PageHeader, Spinner } from '../../components/ui'
import { formatMs, formatPct } from '../../lib/format'

/** Approved tools with a read-only "try" (WP-UI3, contract 13). The model never writes SQL. */
export function ToolsPage() {
  const tools = useQuery({ queryKey: ['tools'], queryFn: api.listTools })
  const [selected, setSelected] = useState<string | null>(null)
  const tool = tools.data?.find((t) => t.name === selected) ?? tools.data?.[0]

  return (
    <div>
      <PageHeader title="Approved tools" subtitle="Parameterised SQL templates on a read-only connection. The router picks one and fills its arguments." />
      {tools.error ? <ErrorBanner error={tools.error} onRetry={() => tools.refetch()} /> : null}
      {tools.isLoading ? <Spinner /> : null}
      {tools.data && tool ? (
        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          <Card title={`${tools.data.length} tools`}>
            <ul className="-mx-2 space-y-0.5">
              {tools.data.map((t) => (
                <li key={t.name}>
                  <button
                    type="button"
                    onClick={() => setSelected(t.name)}
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${t.name === tool.name ? 'bg-indigo-50 text-indigo-800 dark:bg-indigo-500/15 dark:text-indigo-200' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}
                  >
                    <span className="font-mono">{t.name}</span>
                    <span className="ml-2 text-xs text-slate-500">v{t.version} · {t.source}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <ToolDetail key={tool.name} tool={tool} />
        </div>
      ) : null}
    </div>
  )
}

function initialArgs(tool: ToolInfo): Record<string, string> {
  return Object.fromEntries(Object.entries(tool.argument_schema).map(([k, s]) => [k, s.example === undefined ? '' : String(s.example)]))
}

function ToolDetail({ tool }: { tool: ToolInfo }) {
  const [args, setArgs] = useState<Record<string, string>>(() => initialArgs(tool))
  const run = useMutation({
    mutationFn: () => {
      const typed: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(args)) {
        if (v === '') continue
        typed[k] = tool.argument_schema[k]?.type === 'integer' ? Number(v) : v
      }
      return api.tryTool(tool.name, typed)
    },
  })
  const result = run.data

  return (
    <div className="space-y-5">
      <Card title={<span className="font-mono">{tool.name}</span>} actions={tool.approved ? <Badge tone="green">approved</Badge> : <Badge tone="amber">not approved</Badge>}>
        <p className="mb-3 text-sm">{tool.description}</p>
        <KeyValue items={[['Version', tool.version], ['Source', tool.source], ['Success rate', formatPct(tool.success_rate)]]} />
      </Card>
      <Card title="Try it (read-only)">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            run.mutate()
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(tool.argument_schema).map(([name, s]) => (
              <label key={name} className="block">
                <span className="label">
                  {name}
                  {s.required ? ' *' : ''} <span className="normal-case text-slate-400">({s.type})</span>
                </span>
                {s.enum ? (
                  <select className="input" aria-label={name} value={args[name] ?? ''} onChange={(e) => setArgs((a) => ({ ...a, [name]: e.target.value }))}>
                    <option value="">(none)</option>
                    {s.enum.map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                ) : (
                  <input className="input font-mono" aria-label={name} type={s.type === 'integer' ? 'number' : 'text'} value={args[name] ?? ''} onChange={(e) => setArgs((a) => ({ ...a, [name]: e.target.value }))} />
                )}
              </label>
            ))}
          </div>
          <button type="submit" className="btn-primary" disabled={run.isLoading}>
            {run.isLoading ? 'Running' : 'Run tool'}
          </button>
        </form>
        {run.error ? <div className="mt-3"><ErrorBanner error={run.error} /></div> : null}
        {result ? (
          <div className="mt-4 space-y-2 text-sm">
            <p><strong>Summary:</strong> {result.summary}</p>
            <p className="text-xs text-slate-500">
              Provenance: {result.provenance.tool} v{result.provenance.version} · {result.provenance.source} · {result.provenance.row_count} rows · {formatMs(result.provenance.latency_ms)}
            </p>
            <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-2 text-xs dark:bg-slate-800/60">{JSON.stringify(result.rows, null, 2)}</pre>
          </div>
        ) : null}
      </Card>
    </div>
  )
}
