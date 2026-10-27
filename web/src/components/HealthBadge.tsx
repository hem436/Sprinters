import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Health } from '../api/types'

const PARTS: [keyof Health, string][] = [
  ['qdrant', 'Vector DB'],
  ['llm', 'LLM'],
  ['ocr_available', 'OCR'],
  ['reranker', 'Reranker'],
  ['db', 'Database'],
]

export function HealthBadge() {
  const { data, isError } = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000, retry: false })
  const down = isError || data?.status === 'down'
  const degraded = data?.status === 'degraded' || (data && PARTS.some(([k]) => data[k] === false))
  const color = down ? 'bg-rose-500' : degraded ? 'bg-amber-500' : data ? 'bg-emerald-500' : 'bg-slate-400'
  const label = down ? 'Service down' : degraded ? 'Degraded' : data ? 'All systems OK' : 'Checking'
  const detail = data ? PARTS.map(([k, name]) => `${name}: ${data[k] ? 'up' : 'down'}`).join('\n') : isError ? 'GET /health failed' : ''

  return (
    <span title={detail} className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
      <span className={`h-2 w-2 rounded-full ${color}`} aria-hidden />
      {label}
    </span>
  )
}
