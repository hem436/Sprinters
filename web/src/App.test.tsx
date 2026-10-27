import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { saveCredentials } from './api/client'
import { resetMockStore } from './api/mock/mockApi'
import { App } from './App'
import { renderWithProviders } from './test/render'

beforeEach(() => {
  resetMockStore()
  saveCredentials({ username: 'admin', password: 'x' })
})

describe('every route renders on mock data', () => {
  it.each([
    ['/dashboard', 'Total queries'],
    ['/queries', 'Query executions'],
    ['/eval', 'A vs B comparison'],
    ['/admin/documents', 'Travel and Expense Policy'],
    ['/admin/documents/doc_88d2', 'Extraction report'],
    ['/admin/documents/doc_88d2/pages/3', 'Approve'],
    ['/admin/finance', 'tbl_seg_58'],
    ['/admin/tools', 'Try it (read-only)'],
  ])('%s', async (route, text) => {
    renderWithProviders(<App />, route)
    expect((await screen.findAllByText(text, {}, { timeout: 3000 })).length).toBeGreaterThan(0)
  })

  it('sends a login-less user to the login page for the dashboard', async () => {
    saveCredentials(null)
    renderWithProviders(<App />, '/dashboard')
    expect(await screen.findByText('Admin and reviewer login')).toBeInTheDocument()
  })
})

describe('chat end to end on mock data', () => {
  it('asks without streaming and shows citations, badges and feedback', async () => {
    renderWithProviders(<App />, '/chat')
    await userEvent.click(screen.getByRole('button', { name: /^Filters/ }))
    await userEvent.click(screen.getByLabelText('Stream answer'))
    await userEvent.type(screen.getByLabelText('Question'), 'What does POL-HR-014 say about laptops?{enter}')
    expect(await screen.findByText(/full-disk encryption/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /IT Security SOP/ })).toBeInTheDocument()
    expect(screen.getByText('HIGH confidence')).toBeInTheDocument()
    expect(screen.getByText('Was this helpful?')).toBeInTheDocument()
  })

  it('streams an answer token by token', async () => {
    renderWithProviders(<App />, '/chat')
    await userEvent.type(screen.getByLabelText('Question'), 'Total travel spend of P-104 in FY2026-27?{enter}')
    expect(await screen.findByText(/₹4,35,500/, {}, { timeout: 6000 })).toBeInTheDocument()
    expect(await screen.findByText('SQL', {}, { timeout: 6000 })).toBeInTheDocument()
  })
})
