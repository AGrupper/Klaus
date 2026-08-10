import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReviewInbox } from './ReviewInbox'

vi.mock('../../api/reviews', () => ({ fetchReviews: vi.fn() }))

import { fetchReviews } from '../../api/reviews'
import type { RoutineReview } from '../../api/reviews'

const mockFetchReviews = vi.mocked(fetchReviews)

function review(overrides: Partial<RoutineReview> = {}): RoutineReview {
  return {
    review_id: 'review-1',
    correlation_id: 'correlation-1',
    routine: 'nightly',
    target_date: '2026-08-10',
    routine_status: 'published_claude',
    provider: 'claude_subscription',
    review_text: 'A concise review.',
    structured: {},
    action_ids: [],
    partial_actions: [],
    published_at: '2026-08-10T21:00:00Z',
    ...overrides,
  }
}

function renderInbox() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReviewInbox />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReviewInbox', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows mixed routine cards newest first with a plain-text preview and status', async () => {
    const nightlyText = 'Nightly line one\nNightly line two '.repeat(16)
    const nightly = review({
      review_id: 'nightly-1',
      review_text: nightlyText,
      published_at: '2026-08-10T21:00:00Z',
    })
    const morning = review({
      review_id: 'morning-1',
      routine: 'morning',
      target_date: '2026-08-10',
      routine_status: 'published_fallback',
      published_at: '2026-08-10T07:00:00Z',
    })
    const weekly = review({
      review_id: 'weekly-1',
      routine: 'weekly',
      target_date: '2026-08-09',
      routine_status: 'late_upgraded',
      published_at: '2026-08-09T12:00:00Z',
    })
    mockFetchReviews.mockResolvedValue({ reviews: [weekly, morning, nightly] })

    renderInbox()

    const cards = await screen.findAllByRole('article')
    expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual([
      'Nightly review for 2026-08-10',
      'Morning review for 2026-08-10',
      'Weekly review for 2026-08-09',
    ])
    expect(cards[0]).toHaveTextContent('Claude')
    expect(cards[1]).toHaveTextContent('Fallback')
    expect(cards[2]).toHaveTextContent('Late upgrade')
    expect(cards[0]).toHaveTextContent('Nightly line one Nightly line two')
    expect(cards[0]).toHaveTextContent('…')
    expect(nightly.review_text).toBe(nightlyText)
  })

  it('links each card to its nested routine review route', async () => {
    mockFetchReviews.mockResolvedValue({ reviews: [review()] })
    renderInbox()

    expect(await screen.findByRole('link', { name: /Nightly review for 2026-08-10/i }))
      .toHaveAttribute('href', '/klaus/reviews/nightly/2026-08-10')
  })

  it('shows action and partial-action indicators when present', async () => {
    mockFetchReviews.mockResolvedValue({
      reviews: [review({ action_ids: ['action-1', 'action-2'], partial_actions: [{ id: 'partial-1' }] })],
    })
    renderInbox()

    const card = await screen.findByRole('article')
    expect(card).toHaveTextContent('2 actions')
    expect(card).toHaveTextContent('1 partial action')
  })

  it('explains when no reviews are available', async () => {
    mockFetchReviews.mockResolvedValue({ reviews: [] })
    renderInbox()

    expect(await screen.findByText('No routine reviews are available yet.')).toBeInTheDocument()
  })

  it('offers a retry after a recoverable loading failure', async () => {
    mockFetchReviews.mockRejectedValue(new Error('Network unavailable'))
    renderInbox()

    expect(await screen.findByText('Could not load routine reviews.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry reviews' })).toBeInTheDocument()
  })
})
