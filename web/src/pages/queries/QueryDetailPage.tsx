import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api'
import type { DrillDown, RankedHit } from '../../api/types'
import { Badge, Card, Empty, ErrorBanner, KeyValue, OutcomeBadge, PageHeader, RouteBadge, Spinner, StatusBadge, Table } from '../../components/ui'
import { formatCost, formatMs, formatNumber, formatTokens, formatTs } from '../../lib/format'

export function QueryDetailPage() {
  const { queryId = '' } = useParams()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['query', queryId], queryFn: () => api.getQuery(queryId) })

  return (
    <div>
      <PageHeader
        title="Query drill-down"
        subtitle={<code>{queryId}</code>}
        actions={
          <Link to="/queries" className="btn-secondary">
            Back to list
          </Link>
        }
      />
      {error ? <ErrorBanner error={error} onRetry={() => refetch()} /> : null}
      {isLoading ? <Spinner /> : null}
      {data ? <DrillDownView d={data} /> : null}
    </div>
  )
}

function Panel({ n, title, children, wide }: { n: number; title: string; children: ReactNode; wide?: boolean }) {
  return (
    <Card title={<span><span className="mr-1.5 text-slate-400">{n}.</span>{title}</span>} className={wide ? 'lg:col-span-2' : ''}>
      <div data-testid={`panel-${title}`}>{children}</div>
    </Card>
  )
}

export function DrillDownView({ d }: { d: DrillDown }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel n={1} title="Identity">
        <KeyValue
          items={[
            ['Query id', <code key="q">{d.identity.query_id}</code>],
            ['Time', formatTs(d.identity.ts)],
            ['Session id', <code key="s">{d.identity.session_id}</code>],
            ['App version', d.identity.app_version],
            ['Config', <Badge key="c">{d.identity.config_id}</Badge>],
          ]}
        />
      </Panel>

      <Panel n={2} title="Question">
        <KeyValue
          items={[
            ['Original (masked)', d.question.original_masked],
            ['Normalized', d.question.normalized],
            ['Route', <span key="r" className="inline-flex items-center gap-2"><RouteBadge route={d.question.route} />{d.question.route_reason ? <code className="text-xs text-slate-500">{d.question.route_reason}</code> : null}</span>],
          ]}
        />
      </Panel>

      <Panel n={3} title="Execution status">
        <Table head={['Stage', 'Status', 'Time']}>
          {d.execution.map((s) => (
            <tr key={s.stage}>
              <td className="td font-mono text-xs">{s.stage}</td>
              <td className="td"><StatusBadge status={s.status} /></td>
              <td className="td tabular-nums">{s.status === 'SKIPPED' ? '' : formatMs(s.latency_ms)}</td>
            </tr>
          ))}
        </Table>
      </Panel>

      <Panel n={4} title="Overall outcome">
        <div className="flex flex-col gap-2">
          <div className="text-lg"><OutcomeBadge outcome={d.outcome.outcome} reason={d.outcome.reason_code} /></div>
          <p className="text-xs text-slate-500">Outcome rules of contract 11 section 5. The first matching rule wins.</p>
        </div>
      </Panel>

      <Panel n={5} title="Retrieval" wide>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <HitList title="Vector" hits={d.retrieval.vector} />
          <HitList title="BM25" hits={d.retrieval.bm25} />
          <HitList title="Fused (RRF)" hits={d.retrieval.fused} />
          <HitList title="Reranked" hits={d.retrieval.reranked} />
        </div>
      </Panel>

      <Panel n={6} title="Evidence quality">
        {d.evidence_quality ? (
          <KeyValue
            items={[
              ['Relevant evidence', d.evidence_quality.relevant ? <Badge key="y" tone="green">yes</Badge> : <Badge key="n" tone="red">no</Badge>],
              ['Top score', d.evidence_quality.top_score?.toFixed(2)],
              ['Expected evidence match', d.evidence_quality.expected_match === null || d.evidence_quality.expected_match === undefined ? 'not an evaluation query' : d.evidence_quality.expected_match ? <Badge key="m" tone="green">match</Badge> : <Badge key="x" tone="red">no match</Badge>],
            ]}
          />
        ) : (
          <Empty>No document retrieval on this route.</Empty>
        )}
      </Panel>

      <Panel n={7} title="Conversation context">
        {d.context_turns.length ? (
          <ol className="space-y-1.5 text-sm">
            {d.context_turns.map((t) => (
              <li key={t.turn_index} className="rounded bg-slate-50 px-2 py-1 dark:bg-slate-800/60">
                <span className="mr-2 text-xs text-slate-500">#{t.turn_index} {t.role} · {t.chars} chars</span>
                {t.text_masked ? <span className="line-clamp-2">{t.text_masked}</span> : null}
              </li>
            ))}
          </ol>
        ) : (
          <Empty>No prior turns were sent.</Empty>
        )}
      </Panel>

      <Panel n={8} title="Tool calls">
        {d.tool_calls.length ? (
          <Table head={['Tool', 'Inputs (sanitized)', 'Status', 'Result', 'Time']}>
            {d.tool_calls.map((t, i) => (
              <tr key={i}>
                <td className="td font-mono text-xs">{t.tool}</td>
                <td className="td"><code className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(t.args_sanitized)}</code></td>
                <td className="td"><StatusBadge status={t.status} /></td>
                <td className="td text-xs">{t.summary ?? ''}{t.row_count !== undefined ? ` (${t.row_count} rows)` : ''}</td>
                <td className="td tabular-nums">{formatMs(t.latency_ms)}</td>
              </tr>
            ))}
          </Table>
        ) : (
          <Empty>No tool was called.</Empty>
        )}
      </Panel>

      <Panel n={9} title="Generation" wide>
        <KeyValue
          items={[
            ['Model', <code key="m">{d.generation.model}</code>],
            ['Prompt version', <code key="p">{d.generation.prompt_version}</code>],
            ['Validation', <StatusBadge key="v" status={d.generation.validation} />],
          ]}
        />
        {d.generation.raw_output ? (
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-indigo-600">Raw model output</summary>
            <pre className="mt-2 max-h-72 overflow-auto rounded bg-slate-50 p-2 text-xs dark:bg-slate-800/60">{d.generation.raw_output}</pre>
          </details>
        ) : null}
      </Panel>

      <Panel n={10} title="Citations">
        {d.citations.length ? (
          <ul className="space-y-1 text-sm">
            {d.citations.map((c) => (
              <li key={c.id} className="flex items-center gap-2">
                <code className="font-semibold">{c.id}</code>
                {c.valid ? <Badge tone="green">maps to evidence</Badge> : <Badge tone="red">invalid</Badge>}
                {c.reason ? <span className="text-xs text-slate-500">{c.reason}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No citations.</Empty>
        )}
      </Panel>

      <Panel n={11} title="Grounding">
        <p className="mb-2 text-sm">
          Score: <strong>{d.grounding.score === null ? 'n/a' : d.grounding.score.toFixed(2)}</strong>
          <span className="text-xs text-slate-500"> (minimum 0.80)</span>
        </p>
        {d.grounding.claims.length ? (
          <ul className="space-y-1 text-sm">
            {d.grounding.claims.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span aria-label={c.supported ? 'supported' : 'unsupported'}>{c.supported ? '✅' : '⚠️'}</span>
                <span className={c.supported ? '' : 'text-amber-700 dark:text-amber-300'}>{c.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No claims to check.</Empty>
        )}
      </Panel>

      <Panel n={12} title="Safety">
        <div className="flex flex-wrap gap-1.5">
          {d.safety.flags.length ? d.safety.flags.map((f) => <Badge key={f} tone="red">{f}</Badge>) : <Badge tone="green">No safety flags</Badge>}
          {d.safety.pii_masked ? <Badge tone="amber">PII masked</Badge> : null}
          {d.safety.fallback ? <Badge tone="amber">Fallback used</Badge> : null}
        </div>
      </Panel>

      <Panel n={13} title="Performance">
        <LatencyBars p={d.performance} />
      </Panel>

      <Panel n={14} title="Usage">
        <Table head={['Call', 'Tokens in', 'Tokens out', 'Cached']}>
          {d.usage.calls.map((c, i) => (
            <tr key={i}>
              <td className="td">{c.purpose}</td>
              <td className="td tabular-nums">{formatNumber(c.tokens_in)}</td>
              <td className="td tabular-nums">{formatNumber(c.tokens_out)}</td>
              <td className="td tabular-nums">{c.cached_tokens === undefined ? 'n/a' : formatNumber(c.cached_tokens)}</td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-sm">
          Tokens: <strong>{formatTokens(d.usage.calls.reduce((a, c) => a + c.tokens_in, 0), d.usage.calls.reduce((a, c) => a + c.tokens_out, 0), true)}</strong>
        </p>
        <p className="mt-1 text-sm">
          Cost: <strong className={d.usage.cost_usd === null ? 'italic text-slate-400' : ''}>{formatCost(d.usage.cost_usd)}</strong>
          <span className="ml-2 text-xs text-slate-500">source: {d.usage.usage_source}</span>
        </p>
      </Panel>

      <Panel n={15} title="Feedback">
        {d.feedback ? (
          <p className="text-sm">
            <Badge tone={d.feedback.helpful ? 'green' : 'red'}>{d.feedback.helpful ? 'Helpful' : 'Not helpful'}</Badge>
            {d.feedback.comment ? <span className="ml-2">“{d.feedback.comment}”</span> : null}
          </p>
        ) : (
          <p className="text-sm text-slate-500">No user feedback.</p>
        )}
        <ReviewerComments queryId={d.identity.query_id} comments={d.reviewer_comments ?? []} />
      </Panel>

      <Panel n={16} title="Errors">
        {d.errors.length ? (
          <Table head={['Category', 'Stage', 'Retries', 'Correlation id']}>
            {d.errors.map((e, i) => (
              <tr key={i}>
                <td className="td font-mono text-xs">{e.category}</td>
                <td className="td">{e.stage}</td>
                <td className="td">{e.retries}</td>
                <td className="td font-mono text-xs">{e.correlation_id}</td>
              </tr>
            ))}
          </Table>
        ) : (
          <Empty>No errors.</Empty>
        )}
      </Panel>
    </div>
  )
}

function HitList({ title, hits }: { title: string; hits: RankedHit[] }) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800">
      <p className="border-b border-slate-200 px-2 py-1 text-xs font-semibold dark:border-slate-800">{title}</p>
      {hits.length === 0 ? (
        <p className="px-2 py-3 text-xs text-slate-400">Skipped or empty</p>
      ) : (
        <ol className="divide-y divide-slate-100 text-xs dark:divide-slate-800">
          {hits.map((h) => (
            <li key={`${h.chunk_id}-${h.rank}`} className="flex items-center justify-between gap-2 px-2 py-1">
              <span className="min-w-0 truncate">
                <span className="mr-1 text-slate-400">{h.rank}.</span>
                <span title={h.chunk_id}>{h.doc}</span>
                {h.version ? <span className="text-slate-400"> v{h.version}</span> : null}
                <span className="text-slate-400"> p.{h.page}</span>
              </span>
              <span className="font-mono tabular-nums">{h.score}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function LatencyBars({ p }: { p: DrillDown['performance'] }) {
  const parts = [
    ['Retrieval', p.retrieval_ms, 'bg-indigo-300'],
    ['Tool', p.tool_ms, 'bg-slate-500'],
    ['LLM', p.llm_ms, 'bg-indigo-500'],
  ] as const
  const max = Math.max(p.total_ms, 1)
  return (
    <div className="space-y-2 text-sm">
      {parts.map(([label, ms, color]) => (
        <div key={label} className="grid grid-cols-[72px_1fr_72px] items-center gap-2">
          <span className="text-slate-500">{label}</span>
          <span className="h-2 rounded bg-slate-100 dark:bg-slate-800">
            <span className={`block h-2 rounded ${color}`} style={{ width: `${(ms / max) * 100}%` }} />
          </span>
          <span className="text-right tabular-nums">{formatMs(ms)}</span>
        </div>
      ))}
      <p className="border-t border-slate-100 pt-1 text-right font-semibold dark:border-slate-800">End to end {formatMs(p.total_ms)}</p>
    </div>
  )
}

function ReviewerComments({ queryId, comments }: { queryId: string; comments: string[] }) {
  const [text, setText] = useState('')
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => api.reviewQuery(queryId, text.trim()),
    onSuccess: () => {
      setText('')
      qc.invalidateQueries({ queryKey: ['query', queryId] })
    },
  })
  return (
    <div className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800">
      <p className="label">Reviewer comments</p>
      {comments.length ? (
        <ul className="mb-2 list-disc pl-5 text-sm">
          {comments.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      ) : null}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) mutation.mutate()
        }}
      >
        <input className="input" aria-label="Reviewer comment" placeholder="Add a reviewer comment" value={text} onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="btn-primary" disabled={!text.trim() || mutation.isLoading}>
          Add
        </button>
      </form>
      {mutation.error ? <div className="mt-2"><ErrorBanner error={mutation.error} /></div> : null}
    </div>
  )
}
