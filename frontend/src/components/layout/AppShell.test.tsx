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

/**
 * Bounded-height root (UAT gap-closure, 2026-07).
 *
 * Bug: the root used `minHeight: 100dvh`. A *min*-height lets the flex
 * container grow past the viewport to fit tall content, so `<main>`'s
 * `overflow-y-auto` never becomes the real scrolling element — the
 * container itself grows and the page/body scrolls instead. Downstream,
 * ChatWindow's message list relies on a `height: 100%` chain through this
 * root to become its own bounded scroll region; an unbounded root breaks
 * that chain, which is why chat always opened at the top of history
 * instead of the latest message on phone.
 *
 * `height: 100dvh` is a definite viewport-relative value — locking it here
 * (not `minHeight`) is the regression guard for that root cause.
 */
describe('AppShell — bounded-height root (Problem 1 root-cause fix)', () => {
  it('renders a height:100dvh root, not minHeight (which lets content overflow the viewport)', () => {
    const { container } = renderShell('/')
    const root = container.firstElementChild as HTMLElement
    expect(root.style.height).toBe('100dvh')
    expect(root.style.minHeight).toBe('')
  })
})
