import { describe, expect, it } from 'vitest'
import { costFor } from '../api/mock/scenarios'
import { formatCost, formatMs, formatPct, formatTokens } from './format'
import { checkUpload } from './upload'

describe('formatCost', () => {
  it('shows "price not set" for null, never zero (test_missing_price_not_zero)', () => {
    expect(formatCost(null)).toBe('price not set')
  })
  it('keeps 6 decimals from the server string', () => {
    expect(formatCost('0.00036')).toBe('$0.000360')
    expect(formatCost('0.000420')).toBe('$0.000420')
  })
})

describe('cost rule of contract 11 section 4', () => {
  it('1,200 in and 300 out at 0.15 / 0.60 USD per 1M is 0.000360 (test_cost_decimal)', () => {
    expect(costFor(1200, 300)).toBe('0.000360')
  })
})

describe('formatMs and formatPct', () => {
  it('formats', () => {
    expect(formatMs(640)).toBe('640 ms')
    expect(formatMs(3120)).toBe('3.12 s')
    expect(formatPct(0.873)).toBe('87 %')
    expect(formatPct(null)).toBe('n/a')
  })
})

describe('checkUpload', () => {
  const meta = { title: 'Policy', category: 'Policy', version: '1.0', effective_date: '2026-04-01' }
  it('accepts a valid PDF', () => {
    expect(checkUpload(new File(['x'], 'a.pdf'), meta)).toEqual([])
  })
  it('rejects an unsupported type, an empty file and bad metadata', () => {
    const fields = checkUpload(new File([''], 'a.exe'), { ...meta, version: 'v one', effective_date: '' }).map((p) => p.field)
    expect(fields).toEqual(['file', 'file', 'version', 'effective_date'])
  })
})

describe('formatTokens', () => {
  it('shows the total, and in and out on request', () => {
    expect(formatTokens(2410, 96)).toBe('2,506 tokens')
    expect(formatTokens(2410, 96, true)).toBe('2,506 tokens (2,410 in · 96 out)')
  })
})
