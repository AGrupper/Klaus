/**
 * AppShell.test.tsx — regression guard for the global undo toast.
 *
 * Bug: <UndoToast /> was rendered inside TasksPage, so deleting a habit on
 * /habits (where TasksPage is not mounted) produced no undo toast. The toast
 * must be mounted by AppShell so it exists on every route.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { AppShell } from './AppShell'
import { useUndoStore } from '../../store/undoStore'

function renderShell(path = '/habits') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppShell>
          <div>content</div>
        </AppShell>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShell — global UndoToast mount', () => {
  beforeEach(() => {
    useUndoStore.getState().clear()
    vi.useRealTimers()
  })

  it('shows the habit undo toast on /habits (where TasksPage is not mounted)', () => {
    useUndoStore.getState().show({
      id: 'h1',
      action: 'delete',
      listId: 'habits',
      nextId: null,
      resourceType: 'habit',
    })
    renderShell('/habits')
    expect(screen.getByText('Habit deleted.')).toBeInTheDocument()
  })
})
