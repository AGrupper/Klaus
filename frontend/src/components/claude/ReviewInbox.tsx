import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchReviews, type RoutineReview } from '../../api/reviews'
import {
  accent,
  border,
  secondary,
  textPrimary,
  textSecondary,
  typography,
} from '../../tokens'

const PREVIEW_LENGTH = 160

function routineLabel(routine: RoutineReview['routine']): string {
  return `${routine.charAt(0).toUpperCase()}${routine.slice(1)}`
}

function statusLabel(status: RoutineReview['routine_status']): string {
  switch (status) {
    case 'published_fallback':
      return 'Fallback'
    case 'late_upgraded':
      return 'Late upgrade'
    default:
      return 'Claude'
  }
}

function previewFor(reviewText: string): string {
  const plainText = reviewText.replace(/\s+/g, ' ').trim()
  return plainText.length > PREVIEW_LENGTH
    ? `${plainText.slice(0, PREVIEW_LENGTH).trimEnd()}…`
    : plainText
}

function countLabel(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`
}

export function ReviewInbox() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['reviews', 'recent'],
    queryFn: () => fetchReviews(),
  })

  if (isLoading) {
    return <p role="status" style={{ color: textSecondary }}>Loading routine reviews…</p>
  }

  if (isError) {
    return (
      <section aria-label="Routine reviews" style={{ color: textSecondary }}>
        <p>Could not load routine reviews.</p>
        <button type="button" onClick={() => void refetch()}>
          Retry reviews
        </button>
      </section>
    )
  }

  const reviews = [...(data?.reviews ?? [])].sort(
    (left, right) => Date.parse(right.published_at) - Date.parse(left.published_at),
  )

  return (
    <section aria-labelledby="routine-reviews-heading" style={{ marginTop: '28px' }}>
      <h2
        id="routine-reviews-heading"
        style={{ margin: '0 0 12px', fontSize: typography.heading.fontSize, color: textPrimary }}
      >
        Recent routine reviews
      </h2>
      {reviews.length === 0 ? (
        <p style={{ margin: 0, color: textSecondary }}>No routine reviews are available yet.</p>
      ) : (
        <div style={{ display: 'grid', gap: '12px' }}>
          {reviews.map((review) => {
            const label = `${routineLabel(review.routine)} review for ${review.target_date}`
            return (
              <article
                key={review.review_id}
                aria-label={label}
                style={{ backgroundColor: secondary, border: `1px solid ${border}`, borderRadius: '12px' }}
              >
                <Link
                  to={`/klaus/reviews/${review.routine}/${review.target_date}`}
                  style={{ display: 'block', padding: '16px', color: textPrimary, textDecoration: 'none' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                    <h3 style={{ margin: 0, fontSize: typography.label.fontSize }}>{label}</h3>
                    <span style={{ color: accent, fontSize: typography.label.fontSize }}>
                      {statusLabel(review.routine_status)}
                    </span>
                  </div>
                  <p style={{ margin: '10px 0 0', color: textSecondary, lineHeight: 1.5 }}>
                    {previewFor(review.review_text)}
                  </p>
                  {(review.action_ids.length > 0 || review.partial_actions.length > 0) && (
                    <p style={{ margin: '10px 0 0', color: textSecondary, fontSize: typography.label.fontSize }}>
                      {review.action_ids.length > 0 && countLabel(review.action_ids.length, 'action', 'actions')}
                      {review.action_ids.length > 0 && review.partial_actions.length > 0 ? ' · ' : ''}
                      {review.partial_actions.length > 0
                        && countLabel(review.partial_actions.length, 'partial action', 'partial actions')}
                    </p>
                  )}
                </Link>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
