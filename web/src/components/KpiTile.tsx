import type { ReactNode } from 'react'

export function KpiTile({ label, value, detail, tone }: { label: string; value: ReactNode; detail?: ReactNode; tone?: 'good' | 'warn' | 'bad' }) {
  const bar = tone === 'good' ? 'bg-emerald-500' : tone === 'warn' ? 'bg-amber-500' : tone === 'bad' ? 'bg-rose-500' : 'bg-slate-300 dark:bg-slate-700'
  return (
    <div className="card relative overflow-hidden p-4" data-testid="kpi-tile">
      <span className={`absolute inset-x-0 top-0 h-1 ${bar}`} aria-hidden />
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {detail ? <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{detail}</div> : null}
    </div>
  )
}

export function toneFor(rate: number | null, good = 0.85, warn = 0.6): 'good' | 'warn' | 'bad' | undefined {
  if (rate === null) return undefined
  return rate >= good ? 'good' : rate >= warn ? 'warn' : 'bad'
}
