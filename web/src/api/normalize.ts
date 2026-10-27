import { buildUrl } from './client'
import type { DocumentDetail, DocumentRow, ExtractionPage, Job, LibraryDocument, LibraryPage, Money, PageDetail } from './types'

// The extraction service (extraction/ingestion/service.py) names some fields differently from the
// frontend types. These functions map its real responses onto the types, so the screens stay simple.

type Raw = Record<string, unknown>

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : Number(v) || 0)

/** Cost may arrive as a number from the store. Keep the contract form: a 6-decimal string, or null. */
export function money(v: unknown): Money {
  if (v === null || v === undefined || v === '') return null
  if (typeof v === 'string') return v
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(6) : null
}

/** A relative API path like /documents/x/pages/1/image needs the API base to load in an <img>. */
export function apiAsset(url: unknown): string {
  if (typeof url !== 'string' || !url) return ''
  if (/^(https?:|data:|blob:)/.test(url) || url.startsWith(buildUrl(''))) return url
  return url.startsWith('/') ? buildUrl(url) : url
}

export function toDocumentRow(d: Raw): DocumentRow {
  return {
    document_id: String(d.document_id),
    title: String(d.title ?? d.file_name ?? d.document_id),
    doc_key: String(d.doc_key ?? ''),
    category: String(d.category ?? ''),
    version: String(d.version ?? ''),
    effective_date: String(d.effective_date ?? ''),
    status: (d.status as DocumentRow['status']) ?? 'QUEUED',
    pages: num(d.pages ?? d.page_count),
    chunks: num(d.chunks ?? d.chunk_count),
    ocr_cost_usd: money(d.ocr_cost_usd),
  }
}

export function toDocumentDetail(d: Raw): DocumentDetail {
  const row = toDocumentRow(d)
  const r = d.report as Raw | null | undefined
  return {
    ...row,
    report: r
      ? {
          document_id: row.document_id,
          status: (r.status as DocumentRow['status']) ?? row.status,
          pages: Array.isArray(r.pages) ? (r.pages as Raw[]).map(toExtractionPage) : [],
          chunks: num(r.chunks ?? row.chunks),
          ocr_cost_usd: money(r.ocr_cost_usd ?? d.ocr_cost_usd),
          duration_ms: num(r.duration_ms),
        }
      : null,
  }
}

function toExtractionPage(p: Raw): ExtractionPage {
  return {
    ...(p as unknown as ExtractionPage),
    page: num(p.page),
    quality: num(p.quality),
    flags: (p.flags as string[]) ?? [],
    ocr: p.ocr ? { ...(p.ocr as ExtractionPage['ocr'] & object), cost_usd: money((p.ocr as Raw).cost_usd) } : undefined,
  }
}

export function toPageDetail(p: Raw): PageDetail {
  return {
    page: num(p.page),
    text: String(p.text ?? ''),
    class: String(p.class ?? ''),
    method: String(p.method ?? ''),
    quality: num(p.quality),
    flags: (p.flags as string[]) ?? [],
    status: (p.status as PageDetail['status']) ?? 'INDEXED',
    image_url: apiAsset(p.image_url),
  }
}

export function toJob(j: Raw): Job {
  return {
    job_id: String(j.job_id),
    document_id: String(j.document_id ?? ''),
    title: String(j.title ?? j.file_name ?? j.document_id ?? j.job_id),
    stage: String(j.stage ?? ''),
    done: num(j.done),
    total: num(j.total),
    status: (j.status as Job['status']) ?? 'QUEUED',
  }
}

export function toLibraryDocument(d: Raw): LibraryDocument {
  return {
    document_id: String(d.document_id),
    doc_key: String(d.doc_key ?? ''),
    title: String(d.title ?? d.document_id),
    category: String(d.category ?? ''),
    version: String(d.version ?? ''),
    effective_date: String(d.effective_date ?? ''),
    pages: num(d.pages ?? d.page_count),
  }
}

export function toLibraryPage(p: Raw): LibraryPage {
  return {
    document_id: String(p.document_id),
    title: String(p.title ?? ''),
    version: String(p.version ?? ''),
    page: num(p.page),
    text: String(p.text ?? ''),
  }
}
