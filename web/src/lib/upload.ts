import type { UploadMetadata } from '../api/types'

export const ALLOWED_EXTENSIONS = ['pdf', 'docx', 'txt', 'png', 'jpg', 'jpeg']
export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? 25)

export interface UploadProblem {
  field: string
  problem: string
}

/** Early checks in the page (FR-01). The server repeats them and also finds corrupt or encrypted files. */
export function checkUpload(file: File | null, meta: UploadMetadata): UploadProblem[] {
  const problems: UploadProblem[] = []
  if (!file) {
    problems.push({ field: 'file', problem: 'Choose a file.' })
  } else {
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (!ALLOWED_EXTENSIONS.includes(ext)) problems.push({ field: 'file', problem: `.${ext} is not supported. Use ${ALLOWED_EXTENSIONS.join(', ')}.` })
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) problems.push({ field: 'file', problem: `The file is larger than ${MAX_UPLOAD_MB} MB.` })
    if (file.size === 0) problems.push({ field: 'file', problem: 'The file is empty.' })
  }
  if (!meta.title.trim()) problems.push({ field: 'title', problem: 'Enter a title.' })
  if (!meta.category.trim()) problems.push({ field: 'category', problem: 'Choose a category.' })
  if (!/^\d+(\.\d+)*$/.test(meta.version.trim())) problems.push({ field: 'version', problem: 'Use a version like 1.0 or 2.1.' })
  if (!/^\d{4}-\d{2}-\d{2}$/.test(meta.effective_date)) problems.push({ field: 'effective_date', problem: 'Choose the effective date.' })
  if (meta.doc_key && !/^[a-z0-9-]+$/.test(meta.doc_key)) problems.push({ field: 'doc_key', problem: 'Use lower-case letters, digits and hyphens.' })
  return problems
}
