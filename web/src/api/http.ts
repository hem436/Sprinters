import type { Api } from './api'
import { ApiError, buildUrl, request, toApiError } from './client'
import { toDocumentDetail, toDocumentRow, toJob, toLibraryDocument, toLibraryPage, toPageDetail } from './normalize'
import { createSseParser } from './sse'
import type { QueryResponse } from './types'

type Raw = Record<string, unknown>

const enc = encodeURIComponent

export const httpApi: Api = {
  health: () => request('GET', '/health'),

  query: (req, signal) => request('POST', '/query', { body: req, signal }),

  async queryStream(req, onEvent, signal) {
    const res = await fetch(buildUrl('/query/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(req),
      signal,
    })
    if (!res.ok) throw await toApiError(res)
    if (!res.body) return httpApi.query(req, signal)

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    const parser = createSseParser()
    let final: QueryResponse | null = null
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      for (const ev of parser.push(decoder.decode(value, { stream: true }))) {
        onEvent(ev)
        if (ev.event === 'done') final = ev.data
        if (ev.event === 'error') throw new ApiError(500, ev.data, res.headers.get('X-Request-Id'))
      }
    }
    if (!final) throw new ApiError(500, { code: 'STREAM_INCOMPLETE', message: 'The answer stream ended early.' })
    return final
  },

  feedback: (req) => request('POST', '/feedback', { body: req }),
  reviewQuery: (id, comment) => request('POST', `/queries/${enc(id)}/review`, { body: { comment } }),

  metricsSummary: (f) => request('GET', '/metrics/summary', { query: { ...f } }),
  listQueries: (f) => request('GET', '/queries', { query: { ...f } }),
  getQuery: (id) => request('GET', `/queries/${enc(id)}`),

  startEvalRun: (config_id, case_ids) => request('POST', '/eval/runs', { body: { config_id, case_ids } }),
  listEvalRuns: () => request('GET', '/eval/runs'),
  getEvalRun: (id) => request('GET', `/eval/runs/${enc(id)}`),

  uploadDocument(file, meta) {
    const form = new FormData()
    form.append('file', file)
    for (const [key, value] of Object.entries(meta)) if (value) form.append(key, value)
    return request('POST', '/documents', { form })
  },
  listDocuments: async (f) => (await request<Raw[]>('GET', '/documents', { query: { ...f } })).map(toDocumentRow),
  getDocument: async (id) => toDocumentDetail(await request<Raw>('GET', `/documents/${enc(id)}`)),
  getPage: async (id, n) => toPageDetail(await request<Raw>('GET', `/documents/${enc(id)}/pages/${n}`)),
  pageImageUrl: (id, n) => buildUrl(`/documents/${enc(id)}/pages/${n}/image`),
  reviewPage: async (id, n, decision, comment) =>
    toPageDetail(await request<Raw>('POST', `/documents/${enc(id)}/pages/${n}/review`, { body: { decision, comment } })),
  reindexDocument: (id) => request('POST', `/documents/${enc(id)}/reindex`),
  deleteDocument: (id) => request('DELETE', `/documents/${enc(id)}`),
  listJobs: async () => (await request<Raw[]>('GET', '/jobs')).map(toJob),

  listTables: (id) => request('GET', `/documents/${enc(id)}/tables`),
  reviewTable: (id, decision, comment) => request('POST', `/tables/${enc(id)}/review`, { body: { decision, comment } }),
  listMetricMap: (pending) => request('GET', '/metric-map', { query: { pending } }),
  approveMapping: (line_label, metric) => request('POST', '/metric-map/approve', { body: { line_label, metric } }),

  listLibrary: async (category) => (await request<Raw[]>('GET', '/library', { query: { category } })).map(toLibraryDocument),
  getLibraryPage: async (id, n) => toLibraryPage(await request<Raw>('GET', `/library/${enc(id)}/pages/${n}`)),

  listTools: () => request('GET', '/tools'),
  tryTool: (name, args) => request('POST', `/tools/${enc(name)}/try`, { body: { args } }),
}
