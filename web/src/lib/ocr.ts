import type { ExtractionReport } from '../api/types'

/** OCR tokens summed over the pages of an extraction report. */
export function ocrTokens(report: ExtractionReport | null | undefined): { tokensIn: number; tokensOut: number } {
  const pages = report?.pages ?? []
  return {
    tokensIn: pages.reduce((a, p) => a + (p.ocr?.input_tokens ?? 0), 0),
    tokensOut: pages.reduce((a, p) => a + (p.ocr?.output_tokens ?? 0), 0),
  }
}
