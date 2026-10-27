import { describe, expect, it } from 'vitest'
import { formatCost } from '../lib/format'
import { apiAsset, money, toDocumentDetail, toDocumentRow, toJob, toPageDetail } from './normalize'

// Samples in the shape of extraction/ingestion/service.py on sinngam/backend (834c8a8).

describe('normalize extraction responses', () => {
  it('maps page_count and chunk_count, and keeps cost a string', () => {
    const row = toDocumentRow({ document_id: 'doc_1', title: 'Policy', doc_key: 'p', category: 'Policy', version: '2.0', effective_date: '2026-04-01', status: 'INDEXED', page_count: 12, chunk_count: 41, ocr_cost_usd: 0.0011 })
    expect(row).toMatchObject({ pages: 12, chunks: 41, ocr_cost_usd: '0.001100' })
  })

  it('accepts a document whose report is not written yet', () => {
    expect(toDocumentDetail({ document_id: 'doc_2', status: 'PROCESSING', report: null }).report).toBeNull()
  })

  it('prefixes a relative page image path with the API base', () => {
    const p = toPageDetail({ page: 3, text: 'x', status: 'NEEDS_REVIEW', image_url: '/documents/doc_1/pages/3/image', flags: ['HANDWRITTEN'], quality: 0.71 })
    expect(p.image_url).toBe('/api/documents/doc_1/pages/3/image')
    expect(apiAsset(null)).toBe('')
    expect(apiAsset('data:image/png;base64,AA')).toBe('data:image/png;base64,AA')
  })

  it('gives a job a title from its file name', () => {
    expect(toJob({ job_id: 'j1', document_id: 'doc_1', file_name: 'policy.pdf', status: 'RUNNING', stage: 'extracting', done: 2, total: 9 })).toMatchObject({ title: 'policy.pdf', done: 2, total: 9 })
  })

  it('keeps null cost as "price not set", and never crashes on a number', () => {
    expect(money(null)).toBeNull()
    expect(formatCost(null)).toBe('price not set')
    expect(formatCost(0.00042)).toBe('$0.000420')
  })
})
