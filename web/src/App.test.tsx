import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createHash } from 'node:crypto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetMockStore } from './api/mock/mockApi'
import { App } from './App'
import { resetLoginLimits } from './lib/adminAuth'
import { renderWithProviders } from './test/render'

const PASSWORD = 'test-pass-42'
const withLogin = () => vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', createHash('sha256').update(PASSWORD).digest('hex'))

beforeEach(() => {
  resetMockStore()
  resetLoginLimits()
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllEnvs()
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

  it('opens admin pages directly when no admin password is set up', async () => {
    renderWithProviders(<App />, '/dashboard')
    expect(await screen.findByText('Total queries', {}, { timeout: 3000 })).toBeInTheDocument()
  })
})

describe('admin login in the web app', () => {
  it('asks for the login, refuses a wrong password and opens with the right one', async () => {
    withLogin()
    renderWithProviders(<App />, '/dashboard')
    expect(await screen.findByText('Admin login')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Wrong user name or password.')
    await userEvent.type(screen.getByLabelText('Password'), PASSWORD)
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByText('Total queries', {}, { timeout: 3000 })).toBeInTheDocument()
    // Only a session is saved, never the password.
    expect(sessionStorage.getItem('ka.admin')).not.toContain(PASSWORD)
  })

  it('locks the form for a while after 5 wrong tries', async () => {
    withLogin()
    renderWithProviders(<App />, '/login')
    for (let i = 0; i < 5; i++) {
      await userEvent.type(screen.getByLabelText('Password'), 'nope')
      await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    }
    expect(screen.getByRole('alert')).toHaveTextContent(/Too many wrong tries/)
  })

  it('logs out back to the chat, and the admin pages ask again', async () => {
    withLogin()
    renderWithProviders(<App />, '/login')
    await userEvent.type(screen.getByLabelText('Password'), PASSWORD)
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Log out' }))
    expect(await screen.findByText('Ask the knowledge base')).toBeInTheDocument()
    expect(sessionStorage.getItem('ka.admin')).toBeNull()
    await userEvent.click(screen.getByRole('link', { name: 'Admin' }))
    expect(await screen.findByText('Admin login')).toBeInTheDocument()
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
