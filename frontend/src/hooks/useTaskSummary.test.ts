/**
 * useTaskSummary.test.ts — Tests for the task summary hook.
 *
 * Covers TASK-07: useTaskSummary fetches /api/tasks/summary and returns
 * {due_today: number, overdue: number} for the GlanceRail and DueTasksBand.
 *
 * Mirrors the renderHook pattern from useChat.test.tsx but kept as .ts
 * using createElement instead of JSX to avoid .tsx rename.
 * Network-free: fetchTaskSummary is mocked.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// ---------------------------------------------------------------------------
// Mock the tasks API module so no real fetch is made
// ---------------------------------------------------------------------------

vi.mock('../api/tasks', () => ({
  fetchTaskSummary: vi.fn(),
  fetchTasks: vi.fn(),
  createTask: vi.fn(),
  updateTask: vi.fn(),
  completeTask: vi.fn(),
  undoTask: vi.fn(),
  hardDeleteTask: vi.fn(),
}))

import { fetchTaskSummary } from '../api/tasks'
import { useTaskSummary, TASK_SUMMARY_QUERY_KEY } from './useTaskSummary'

const mockFetchTaskSummary = vi.mocked(fetchTaskSummary)

// ---------------------------------------------------------------------------
// Test wrapper factory — one fresh QueryClient per test to prevent cache bleed
// ---------------------------------------------------------------------------

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })

  // Use createElement to avoid JSX in a .ts file
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)

  return { wrapper, queryClient }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useTaskSummary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Case 1: Hook returns data shape from API
  it('returns {due_today, overdue} when fetch succeeds', async () => {
    mockFetchTaskSummary.mockResolvedValue({ due_today: 3, overdue: 1 })
    const { wrapper } = makeWrapper()

    const { result } = renderHook(() => useTaskSummary(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.data?.due_today).toBe(3)
    expect(result.current.data?.overdue).toBe(1)
    expect(result.current.isError).toBe(false)
  })

  // Case 2: Hook is loading while fetch is in-flight
  it('isLoading is true before fetch resolves', () => {
    // Never-resolving promise keeps the hook in loading state
    mockFetchTaskSummary.mockReturnValue(new Promise(() => {}))
    const { wrapper } = makeWrapper()

    const { result } = renderHook(() => useTaskSummary(), { wrapper })

    // Immediately after mount, hook is loading
    expect(result.current.isLoading).toBe(true)
  })

  // Case 3: Hook handles API error gracefully
  it('returns error when fetch fails', async () => {
    mockFetchTaskSummary.mockRejectedValue(new Error('Network error'))
    const { wrapper } = makeWrapper()

    const { result } = renderHook(() => useTaskSummary(), { wrapper })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })

    expect(result.current.error?.message).toBe('Network error')
  })

  // Case 4: Multiple consumers share the same React Query cache key
  it('multiple hook instances share the same query cache (TASK_SUMMARY_QUERY_KEY)', async () => {
    mockFetchTaskSummary.mockResolvedValue({ due_today: 2, overdue: 0 })
    const { wrapper } = makeWrapper()

    // Mount two hooks with the same QueryClient (same wrapper)
    renderHook(() => useTaskSummary(), { wrapper })
    renderHook(() => useTaskSummary(), { wrapper })

    await waitFor(() => {
      // fetchTaskSummary should have been deduped — called only once
      expect(mockFetchTaskSummary).toHaveBeenCalledTimes(1)
    })
  })

  // Case 5: TASK_SUMMARY_QUERY_KEY exported with the correct shape
  it('TASK_SUMMARY_QUERY_KEY is ["tasks", "summary"]', () => {
    expect(TASK_SUMMARY_QUERY_KEY).toEqual(['tasks', 'summary'])
  })
})
