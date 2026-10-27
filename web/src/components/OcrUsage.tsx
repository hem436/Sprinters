import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { DocumentRow } from '../api/types'
import { formatCost, formatTokens } from '../lib/format'
import { ocrTokens } from '../lib/ocr'

/**
 * OCR tokens and cost for one row of the document list. GET /documents sends only the cost, so the tokens come
 * from the document's report. A zero cost means no OCR ran, and then nothing is fetched. The query key matches
 * the document page, so opening the document reuses this answer.
 */
export function OcrUsage({ doc }: { doc: DocumentRow }) {
  const noOcr = doc.ocr_cost_usd !== null && Number(doc.ocr_cost_usd) === 0
  const detail = useQuery({
    queryKey: ['document', doc.document_id],
    queryFn: () => api.getDocument(doc.document_id),
    enabled: !noOcr,
    staleTime: 60_000,
  })

  if (noOcr) return <span className="text-slate-400">no OCR</span>
  const { tokensIn, tokensOut } = ocrTokens(detail.data?.report)
  const cost = <span className={doc.ocr_cost_usd === null ? 'italic text-slate-400' : 'text-slate-500 dark:text-slate-400'}>{formatCost(doc.ocr_cost_usd)}</span>
  return (
    <span className="whitespace-nowrap" title={detail.data ? `${tokensIn} in · ${tokensOut} out` : undefined}>
      {detail.data ? `${formatTokens(tokensIn, tokensOut)} · ` : detail.isLoading ? '… · ' : ''}
      {cost}
    </span>
  )
}
