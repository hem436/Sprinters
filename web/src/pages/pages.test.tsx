import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { saveCredentials } from '../api/client'
import { mockApi, resetMockStore } from '../api/mock/mockApi'
import { FALLBACK_TEXT } from '../api/mock/scenarios'
import type { QueryResponse } from '../api/types'
import { renderWithProviders } from '../test/render'
import { ChatMessage, type Turn } from './chat/ChatMessage'
import { Comparison } from './eval/EvalPage'
import { DrillDownView } from './queries/QueryDetailPage'

const ask = (question: string, session = 's-test') => mockApi.query({ question, session_id: session })

function turnOf(response: QueryResponse): Turn {
  return { id: 't', question: 'q', status: 'done', partial: '', citations: [], response }
}

beforeEach(() => {
  resetMockStore()
  saveCredentials({ username: 'reviewer', password: 'x' })
})

describe('ChatMessage', () => {
  it('shows the fixed fallback text, LOW confidence and no invented answer', async () => {
    const r = await ask("What is the CEO's salary?")
    renderWithProviders(<ChatMessage turn={turnOf(r)} onRetry={() => {}} />)
    expect(screen.getByText(FALLBACK_TEXT)).toBeInTheDocument()
    expect(screen.getByText('LOW confidence')).toBeInTheDocument()
    expect(screen.getByText('PARTIAL')).toHaveTextContent('NO_EVIDENCE')
  })

  it('shows a conflict between versions with both citations', async () => {
    const r = await ask('What is the per diem in Mumbai?')
    renderWithProviders(<ChatMessage turn={turnOf(r)} onRetry={() => {}} />)
    expect(screen.getByText('Sources disagree.')).toBeInTheDocument()
    expect(screen.getByText('Conflict')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Travel and Expense Policy/ })).toHaveLength(2)
  })
})

describe('DrillDownView', () => {
  it('fills all 16 panels of case section 8.2', async () => {
    const r = await ask('Is P-104 over its travel budget, and what does the policy say about overruns?')
    const d = await mockApi.getQuery(r.query_id)
    renderWithProviders(<DrillDownView d={d} />)
    const panels = [
      'Identity', 'Question', 'Execution status', 'Overall outcome', 'Retrieval', 'Evidence quality', 'Conversation context', 'Tool calls',
      'Generation', 'Citations', 'Grounding', 'Safety', 'Performance', 'Usage', 'Feedback', 'Errors',
    ]
    for (const p of panels) expect(screen.getByTestId(`panel-${p}`)).toBeInTheDocument()
    expect(screen.getByText('budget_status')).toBeInTheDocument()
    expect(screen.getAllByText(r.query_id).length).toBeGreaterThan(0)
  })
})

describe('Comparison', () => {
  it('marks B better on hit@5 and A better on latency when A is faster', () => {
    const base = { status: 'DONE' as const, started_at: '', cases_done: 1, cases_total: 1, results: [] }
    renderWithProviders(
      <Comparison
        a={{ ...base, run_id: 'a', config_id: 'A', summary: { 'hit@5': 0.7, 'latency p50 (ms)': 2000 } }}
        b={{ ...base, run_id: 'b', config_id: 'B', summary: { 'hit@5': 0.9, 'latency p50 (ms)': 2600 } }}
      />,
    )
    const hitRow = screen.getByText('hit@5').closest('tr') as HTMLElement
    const latRow = screen.getByText('latency p50 (ms)').closest('tr') as HTMLElement
    expect(hitRow.lastElementChild).toHaveTextContent('B')
    expect(latRow.lastElementChild).toHaveTextContent('A')
  })
})
