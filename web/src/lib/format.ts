import type { Money } from '../api/types'

/** Cost is a decimal string from the server. It is shown as given, never through a float sum. */
export function formatCost(cost: Money | number | undefined): string {
  if (cost === null || cost === undefined || cost === '') return 'price not set'
  const text = typeof cost === 'number' ? cost.toFixed(6) : String(cost)
  const [whole, frac = ''] = text.split('.')
  return `$${whole}.${frac.padEnd(6, '0').slice(0, 6)}`
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return 'n/a'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

export function formatPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'n/a'
  return `${(value * 100).toFixed(digits)} %`
}

export function ratio(part: number, whole: number): number | null {
  return whole === 0 ? null : part / whole
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-IN').format(n)
}

/** Short form for large counts: 950, 12.4K, 1.2M. Use with the full number in a tooltip. */
export function formatCompact(n: number): string {
  if (Math.abs(n) < 10_000) return formatNumber(n)
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

/** "2,506 tokens"; with in and out, "2,506 tokens (2,410 in · 96 out)" when `detail` is set. */
export function formatTokens(tokensIn: number, tokensOut: number, detail = false): string {
  const total = `${formatNumber(tokensIn + tokensOut)} tokens`
  return detail ? `${total} (${formatNumber(tokensIn)} in · ${formatNumber(tokensOut)} out)` : total
}

export function formatTs(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

export function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10)
}
