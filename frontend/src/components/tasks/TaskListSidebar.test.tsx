/**
 * TaskListSidebar.test.tsx — regression spec for the desktop list sidebar.
 *
 * Guards the duplicate-Inbox bug (UAT 2026-06-19): GET /api/task-lists already
 * prepends the implicit Inbox server-side, so the sidebar must render the API
 * list directly and NOT prepend a second hardcoded Inbox.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'

// useTaskLists returns the API shape — Inbox already prepended by the server.
vi.mock('../../hooks/useTaskLists', () => ({
  useTaskLists: () => ({
    data: [
      { id: 'inbox', name: 'Inbox' },
      { id: 'list-1', name: 'Work' },
    ],
    isLoading: false,
  }),
  useCreateList: () => ({ mutate: vi.fn() }),
}))

import { TaskListSidebar } from './TaskListSidebar'

describe('TaskListSidebar', () => {
  it('renders the API-provided Inbox exactly once (no duplicate)', () => {
    render(<TaskListSidebar activeListId="inbox" onSelect={() => {}} />)
    expect(screen.getAllByText('Inbox')).toHaveLength(1)
  })

  it('renders user-created lists alongside Inbox', () => {
    render(<TaskListSidebar activeListId="inbox" onSelect={() => {}} />)
    expect(screen.getByText('Work')).toBeInTheDocument()
  })
})
