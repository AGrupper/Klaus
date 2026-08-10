import { apiFetch } from './client'

export type RoutineName = 'morning' | 'nightly' | 'weekly'

export interface RoutineReview {
  review_id: string
  correlation_id: string
  routine: RoutineName
  target_date: string
  routine_status: 'published_claude' | 'published_fallback' | 'late_upgraded'
  provider: 'claude_subscription' | 'deterministic'
  review_text: string
  structured: Record<string, unknown>
  action_ids: string[]
  partial_actions: Array<Record<string, unknown>>
  published_at: string
  claude_session_url?: string
}

export function fetchReviews(limit = 20) {
  return apiFetch<{ reviews: RoutineReview[] }>(`/api/reviews?limit=${limit}`)
}

export function fetchReview(routine: RoutineName, targetDate: string) {
  return apiFetch<{ review: RoutineReview }>(
    `/api/reviews/${routine}/${targetDate}`,
  )
}
