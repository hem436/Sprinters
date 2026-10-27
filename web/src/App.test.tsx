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

  it('opens admin pages without a login when VITE_ADMIN_LOGIN is off', async () => {
    saveCredentials(null)
    renderWithProviders(<App />, '/dashboard')
    expect(await screen.findByText('Total queries', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('logs out from an admin page back to the chat and clears the saved login', async () => {
    renderWithProviders(<App />, '/dashboard')
    await userEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByText('Ask the knowledge base')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument()
    expect(sessionStorage.getItem('ka.auth')).toBeNull()
  })
})

describe('two simple views', () => {
  it('shows the user nav on the chat and the admin nav on the dashboard', async () => {
    const { unmount } = renderWithProviders(<App />, '/chat')
    expect(screen.getByRole('navigation', { name: 'Main' })).toHaveTextContent('Admin')
    expect(screen.queryByRole('link', { name: 'Evaluation' })).not.toBeInTheDocument()
    unmount()
    renderWithProviders(<App />, '/dashboard')
    const nav = screen.getByRole('navigation', { name: 'Admin' })
    for (const label of ['Dashboard', 'Documents', 'Evaluation', 'Settings', 'Back to chat']) expect(nav).toHaveTextContent(label)
  })
})

describe('chat end to end on mock data', () => {
  it('asks without streaming and shows the source in the viewer', async () => {
    renderWithProviders(<App />, '/chat')
    await userEvent.click(screen.getByRole('tab', { name: /^Filters/ }))
    await userEvent.click(screen.getByLabelText('Stream answer'))
    await userEvent.type(screen.getByLabelText('Question'), 'What does POL-HR-014 say about laptops?{enter}')
    expect(await screen.findByText('High confidence', {}, { timeout: 3000 })).toBeInTheDocument()
    const source = screen.getByRole('button', { name: /IT Security SOP/ })
    expect(source).toHaveAttribute('aria-pressed', 'true')
    const viewer = screen.getByRole('complementary', { name: 'Source viewer' })
    expect(viewer).toHaveTextContent('IT Security SOP')
    expect(viewer).toHaveTextContent('POL-HR-014 Laptops')
    expect(viewer).toHaveTextContent(/blocked from the network/)
    expect(screen.getByRole('button', { name: 'Helpful' })).toBeInTheDocument()
  })

  it('streams an answer and switches the viewer between sources', async () => {
    renderWithProviders(<App />, '/chat')
    await userEvent.type(screen.getByLabelText('Question'), 'What is the per diem in Mumbai?{enter}')
    expect(await screen.findByText('Two versions disagree', {}, { timeout: 6000 })).toBeInTheDocument()
    const viewer = screen.getByRole('complementary', { name: 'Source viewer' })
    expect(viewer).toHaveTextContent('v2.0 · current')
    await userEvent.click(screen.getByRole('button', { name: /E2/ }))
    expect(viewer).toHaveTextContent('v1.0 · older version')
  })
})
