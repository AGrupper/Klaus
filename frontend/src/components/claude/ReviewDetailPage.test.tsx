import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReviewDetailPage } from './ReviewDetailPage'

vi.mock('../../api/reviews', () => ({ fetchReview: vi.fn() }))

import { fetchReview } from '../../api/reviews'
import type { RoutineReview } from '../../api/reviews'

const mockFetchReview = vi.mocked(fetchReview)

function review(overrides: Partial<RoutineReview> = {}): RoutineReview {
  return {
    review_id: 'review-1',
    correlation_id: 'correlation-1',
    routine: 'nightly',
    target_date: '2026-08-10',
    routine_status: 'published_claude',
    provider: 'claude_subscription',
    review_text: 'A complete review.',
    structured: {},
    action_ids: [],
    partial_actions: [],
    published_at: '2026-08-10T21:00:00Z',
    ...overrides,
  }
}

function renderDetail(initialPath = '/klaus/reviews/nightly/2026-08-10') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/klaus/reviews/:routine/:targetDate" element={<ReviewDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReviewDetailPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders the exact complete review text including line breaks', async () => {
    const reviewText = 'First line.\n\nSecond line.\nThird line.'
    mockFetchReview.mockResolvedValue({ review: review({ review_text: reviewText }) })
    renderDetail()

    expect(await screen.findByText((_, element) => element?.textContent === reviewText))
      .toHaveStyle({ whiteSpace: 'pre-wrap' })
  })

  it('renders action IDs and inert complete partial-action disclosures', async () => {
    mockFetchReview.mockResolvedValue({
      review: review({
        action_ids: ['calendar-event-1', 'task-2'],
        partial_actions: [{ kind: 'calendar', reason: 'Needs confirmation' }],
      }),
    })
    renderDetail()

    expect(await screen.findByText('calendar-event-1')).toBeInTheDocument()
    expect(screen.getByText('task-2')).toBeInTheDocument()
    const disclosure = '{\n  "kind": "calendar",\n  "reason": "Needs confirmation"\n}'
    expect(screen.getByText((_, element) => element?.tagName === 'PRE' && element.textContent === disclosure))
      .toBeInTheDocument()
  })

  it('shows Continue in Claude only for a backend-provided session URL', async () => {
    mockFetchReview.mockResolvedValue({
      review: review({ claude_session_url: 'https://claude.ai/chat/session-123' }),
    })
    renderDetail()

    const link = await screen.findByRole('link', { name: 'Continue in Claude' })
    expect(link).toHaveAttribute('href', 'https://claude.ai/chat/session-123')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('states when a fallback review has no Claude session', async () => {
    mockFetchReview.mockResolvedValue({
      review: review({ routine_status: 'published_fallback', provider: 'deterministic' }),
    })
    renderDetail()

    expect(await screen.findByText('Claude session unavailable for this review.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Continue in Claude' })).not.toBeInTheDocument()
  })

  it('shows accessible loading and recoverable error states', async () => {
    let rejectRequest: (error: Error) => void = () => undefined
    mockFetchReview.mockImplementation(() => new Promise((_, reject) => {
      rejectRequest = reject
    }))
    renderDetail()

    expect(screen.getByRole('status')).toHaveTextContent('Loading routine review…')
    await act(async () => rejectRequest(new Error('Network unavailable')))
    await waitFor(() => expect(screen.getByText('Could not load this routine review.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Retry review' })).toBeInTheDocument()
  })

  it('rejects unexpected routine parameters before calling the reviews API', () => {
    renderDetail('/klaus/reviews/other/2026-08-10')

    expect(screen.getByText('This routine review is unavailable.')).toBeInTheDocument()
    expect(mockFetchReview).not.toHaveBeenCalled()
  })
})
