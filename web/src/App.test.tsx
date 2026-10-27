import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createHash } from 'node:crypto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockApi, resetMockStore } from './api/mock/mockApi'
import { App } from './App'
import { resetLoginLimits } from './lib/adminAuth'
import { renderWithProviders } from './test/render'

const PASSWORD = 'test-pass-42'
const withLogin = () => vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', createHash('sha256').update(PASSWORD).digest('hex'))

beforeEach(() => {
  resetMockStore()
  resetLoginLimits()
  sessionStorage.clear()
  // Most tests look at the pages, not the login; the login tests set their own password.
  vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', 'off')
})

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('every route renders on mock data', () => {
  it.each([
    ['/dashboard', 'Total queries'],
    ['/queries', 'Recent queries'],
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

  it('opens admin pages directly when the login is off, with no Log out', async () => {
    renderWithProviders(<App />, '/dashboard')
    expect(await screen.findByText('Total queries', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to chat' })).toBeInTheDocument()
  })
})

describe('admin dashboard', () => {
  it('shows the 10 KPIs, one chart and the recent queries', async () => {
    renderWithProviders(<App />, '/dashboard')
    expect(await screen.findAllByTestId('kpi-tile', {}, { timeout: 3000 })).toHaveLength(10)
    expect(screen.getByRole('region', { name: 'Outcome over time' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Recent queries' })).toBeInTheDocument()
  })

  it('filters recent queries with a chip and opens the query detail from a row', async () => {
    renderWithProviders(<App />, '/dashboard')
    const recent = await screen.findByRole('region', { name: 'Recent queries' })
    await userEvent.click(screen.getByRole('button', { name: 'Partial' }))
    await screen.findAllByText('PARTIAL', {}, { timeout: 3000 })
    expect(recent.querySelectorAll('tbody tr').length).toBeGreaterThan(0)
    expect(recent.textContent).not.toMatch(/SUCCESS/)
    await userEvent.click(recent.querySelector('tbody tr a') as HTMLElement)
    expect(await screen.findByText('Query drill-down', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('shows tokens, with cost as the secondary number', async () => {
    renderWithProviders(<App />, '/dashboard')
    await screen.findAllByTestId('kpi-tile', {}, { timeout: 3000 })
    const tile = screen.getAllByTestId('kpi-tile').find((t) => t.textContent?.startsWith('Tokens')) as HTMLElement
    expect(tile).toHaveTextContent(/in · .* out · \$/)
    const recent = screen.getByRole('region', { name: 'Recent queries' })
    expect(within(recent).getByRole('columnheader', { name: 'Tokens' })).toBeInTheDocument()
    expect(within(recent).queryByRole('columnheader', { name: 'Cost' })).not.toBeInTheDocument()
  })

  it('falls back to cost when the server sends no tokens for a row', async () => {
    const real = mockApi.listQueries
    vi.spyOn(mockApi, 'listQueries').mockImplementation(async (f) => {
      const page = await real(f)
      return { ...page, items: page.items.map(({ tokens_in: _i, tokens_out: _o, ...row }) => row) }
    })
    renderWithProviders(<App />, '/dashboard')
    const recent = await screen.findByRole('region', { name: 'Recent queries' })
    await waitFor(() => expect(recent.querySelectorAll('tbody tr').length).toBeGreaterThan(0), { timeout: 3000 })
    expect(recent.querySelector('tbody tr td:nth-child(5)')?.textContent).toMatch(/^\$\d|price not set/)
    vi.restoreAllMocks()
  })

  it('changes the time range', async () => {
    renderWithProviders(<App />, '/dashboard')
    await screen.findAllByTestId('kpi-tile', {}, { timeout: 3000 })
    const range = within(screen.getByRole('group', { name: 'Time range' }))
    await userEvent.click(range.getByRole('button', { name: 'All' }))
    expect(range.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('OCR tokens', () => {
  it('shows OCR tokens next to the cost in the document list', async () => {
    renderWithProviders(<App />, '/admin/documents')
    const row = (title: RegExp, version: string) =>
      screen.getAllByRole('row').find((r) => title.test(r.textContent ?? '') && r.textContent?.includes(version)) as HTMLElement
    await screen.findAllByText('Travel and Expense Policy', {}, { timeout: 3000 })
    await waitFor(() => expect(row(/Travel and Expense Policy/, 'v1.0')).toHaveTextContent('1,700 tokens · $0.001100'), { timeout: 3000 })
    expect(row(/Travel and Expense Policy/, 'v2.0')).toHaveTextContent('no OCR')
    await waitFor(() => expect(row(/Vendor Onboarding Note/, 'v1.0')).toHaveTextContent('3,140 tokens · price not set'), { timeout: 3000 })
  })

  it('shows OCR tokens and cost per page on the document page', async () => {
    renderWithProviders(<App />, '/admin/documents/doc_19c0')
    expect(await screen.findByText('gemini-flash · 1,700 tokens · $0.000400', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('1,700 tokens (1,290 in · 410 out)')).toBeInTheDocument()
  })
})

describe('admin login in the web app', () => {
  it('uses the demo password when nothing is set up', async () => {
    vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', '')
    renderWithProviders(<App />, '/dashboard')
    expect(await screen.findByText('Admin login')).toBeInTheDocument()
    expect(screen.getByText(/Demo setup/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Password'), 'demo')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByText('Total queries', {}, { timeout: 3000 })).toBeInTheDocument()
  })

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

  it('places Log out at the far right of the header, outside the page menu', async () => {
    withLogin()
    renderWithProviders(<App />, '/login')
    await userEvent.type(screen.getByLabelText('Password'), PASSWORD)
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    const logout = await screen.findByRole('button', { name: 'Log out' })
    expect(screen.getByRole('navigation', { name: 'Admin' })).not.toContainElement(logout)
    const controls = screen.getByRole('banner').querySelectorAll('a, button')
    expect(controls[controls.length - 1]).toBe(logout)
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
