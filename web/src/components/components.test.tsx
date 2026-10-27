import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api'
import type { ReasonCode } from '../api/types'
import { renderWithProviders } from '../test/render'
import { CitationChip } from './CitationChip'
import { FeedbackBar } from './FeedbackBar'
import { OutcomeBadge } from './ui'

describe('CitationChip', () => {
  it('shows every document chip field (WP-UI1)', () => {
    renderWithProviders(
      <CitationChip citation={{ id: 'E1', kind: 'document', title: 'Travel and Expense Policy', version: '2.0', page: 7, section: '4.2 Per diem', method: 'text+tables', url: '/documents/doc_7f3a/pages/7' }} />,
    )
    const link = screen.getByRole('link')
    expect(link).toHaveTextContent('E1')
    expect(link).toHaveTextContent('Travel and Expense Policy')
    expect(link).toHaveTextContent('v2.0')
    expect(link).toHaveTextContent('p.7')
    expect(link).toHaveTextContent('4.2 Per diem')
    expect(link).toHaveTextContent('text+tables')
    expect(link).toHaveAttribute('href', '/admin/documents/doc_7f3a/pages/7')
  })

  it('shows tool provenance with its arguments', async () => {
    renderWithProviders(<CitationChip citation={{ id: 'T1', kind: 'tool', tool: 'expense_total', args: { project_id: 'P-104' }, row_count: 1 }} />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveTextContent('T1')
    expect(btn).toHaveTextContent('expense_total')
    expect(btn).toHaveTextContent('1 row')
    await userEvent.click(btn)
    expect(screen.getByText(/"project_id": "P-104"/)).toBeInTheDocument()
  })
})

describe('OutcomeBadge', () => {
  const cases: [ReasonCode, 'SUCCESS' | 'PARTIAL' | 'FAILED', string][] = [
    ['SYSTEM_ERROR', 'FAILED', 'rose'],
    ['LLM_ERROR', 'FAILED', 'rose'],
    ['OUTPUT_INVALID', 'FAILED', 'rose'],
    ['BLOCKED_SAFETY', 'PARTIAL', 'amber'],
    ['NO_EVIDENCE', 'PARTIAL', 'amber'],
    ['TOOL_FAILED', 'PARTIAL', 'amber'],
    ['UNGROUNDED_ANSWER', 'FAILED', 'rose'],
    ['UNSUPPORTED_CLAIMS', 'PARTIAL', 'amber'],
    ['OK', 'SUCCESS', 'emerald'],
    ['OK_CONFLICT', 'SUCCESS', 'emerald'],
  ]
  it.each(cases)('%s shows as %s', (reason, outcome, color) => {
    renderWithProviders(<OutcomeBadge outcome={outcome} reason={reason} />)
    const badge = screen.getByText(outcome)
    expect(badge).toHaveTextContent(reason)
    expect(badge.className).toContain(color)
  })
})

describe('FeedbackBar', () => {
  it('saves helpful feedback with one click', async () => {
    const spy = vi.spyOn(api, 'feedback').mockResolvedValue()
    renderWithProviders(<FeedbackBar queryId="Q1" />)
    await userEvent.click(screen.getByRole('button', { name: 'Helpful' }))
    expect(spy).toHaveBeenCalledWith({ query_id: 'Q1', helpful: true, comment: undefined })
    expect(await screen.findByText(/feedback is saved/)).toBeInTheDocument()
    spy.mockRestore()
  })

  it('asks for an optional comment on "Not helpful"', async () => {
    const spy = vi.spyOn(api, 'feedback').mockResolvedValue()
    renderWithProviders(<FeedbackBar queryId="Q1" />)
    await userEvent.click(screen.getByRole('button', { name: 'Not helpful' }))
    await userEvent.type(screen.getByLabelText('Feedback comment'), 'Missed Delhi')
    await userEvent.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(spy).toHaveBeenCalledWith({ query_id: 'Q1', helpful: false, comment: 'Missed Delhi' })
    spy.mockRestore()
  })

  it('handles 409 FEEDBACK_EXISTS', async () => {
    const spy = vi.spyOn(api, 'feedback').mockRejectedValue(new ApiError(409, { code: 'FEEDBACK_EXISTS', message: 'exists' }))
    renderWithProviders(<FeedbackBar queryId="Q1" />)
    await userEvent.click(screen.getByRole('button', { name: 'Helpful' }))
    expect(await screen.findByText(/already saved/)).toBeInTheDocument()
    spy.mockRestore()
  })
})
