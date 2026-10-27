import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetMockStore } from '../../api/mock/mockApi'
import { App } from '../../App'
import { renderWithProviders } from '../../test/render'
import { versionLabels } from './UserDocumentsPage'

beforeEach(() => resetMockStore())

describe('versionLabels', () => {
  it('marks the newest effective date of a doc_key as current', () => {
    const base = { title: 't', category: 'Policy', pages: 1 }
    const labels = versionLabels([
      { ...base, document_id: 'a', doc_key: 'travel', version: '1.0', effective_date: '2024-04-01' },
      { ...base, document_id: 'b', doc_key: 'travel', version: '2.0', effective_date: '2026-04-01' },
      { ...base, document_id: 'c', doc_key: 'faq', version: '1.2', effective_date: '2025-07-01' },
    ])
    expect([labels.get('a'), labels.get('b'), labels.get('c')]).toEqual(['older', 'current', null])
  })
})

describe('user Documents page', () => {
  it('lists readable documents, searches them and shows a page', async () => {
    renderWithProviders(<App />, '/documents')
    const list = await screen.findByRole('navigation', { name: 'Documents' })
    expect(await within(list).findAllByRole('button', { name: /Travel and Expense Policy/ })).toHaveLength(2)
    expect(within(list).getByRole('button', { name: /older version/ })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search documents'), 'security')
    const only = within(list).getAllByRole('button')
    expect(only).toHaveLength(1)
    await userEvent.click(only[0])
    const viewer = screen.getByRole('region', { name: 'Document viewer' })
    expect(within(viewer).getByRole('heading', { name: 'IT Security SOP' })).toBeInTheDocument()
    await userEvent.click(within(viewer).getByRole('button', { name: 'Next page' }))
    await userEvent.click(within(viewer).getByRole('button', { name: 'Next page' }))
    await userEvent.click(within(viewer).getByRole('button', { name: 'Next page' }))
    expect(await within(viewer).findByText(/full-disk encryption/)).toBeInTheDocument()
    expect(within(viewer).getByText('Page 4 of 9')).toBeInTheDocument()
  })

  it('filters by category', async () => {
    renderWithProviders(<App />, '/documents')
    await userEvent.click(await screen.findByRole('button', { name: 'HR' }))
    const list = screen.getByRole('navigation', { name: 'Documents' })
    expect(await within(list).findByRole('button', { name: /Employee Onboarding FAQ/ })).toBeInTheDocument()
    expect(within(list).queryByRole('button', { name: /Travel/ })).not.toBeInTheDocument()
  })

  it('says when a page waits for review, and opens the chat with the document filter', async () => {
    renderWithProviders(<App />, '/documents?doc=doc_88d2&page=3')
    expect(await screen.findByText(/not available to read yet/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Ask about this document' }))
    expect(await screen.findByRole('tab', { name: 'Filters (1)' })).toBeInTheDocument()
  })
})
