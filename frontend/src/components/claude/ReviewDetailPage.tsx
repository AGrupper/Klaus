import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { fetchReview, type RoutineName, type RoutineReview } from '../../api/reviews'
import {
  accent,
  border,
  dominant,
  fontFamily,
  secondary,
  textPrimary,
  textSecondary,
  typography,
} from '../../tokens'

function isRoutineName(value: string | undefined): value is RoutineName {
  return value === 'morning' || value === 'nightly' || value === 'weekly'
}

function routineLabel(routine: RoutineName): string {
  return `${routine.charAt(0).toUpperCase()}${routine.slice(1)}`
}

function ReviewDetail({ routine, targetDate }: { routine: RoutineName; targetDate: string }) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['reviews', routine, targetDate],
    queryFn: () => fetchReview(routine, targetDate),
  })

  if (isLoading) {
    return <p role="status" style={{ color: textSecondary }}>Loading routine review…</p>
  }

  if (isError || !data) {
    return (
      <section aria-label="Routine review error">
        <p style={{ color: textSecondary }}>Could not load this routine review.</p>
        <button type="button" onClick={() => void refetch()}>
          Retry review
        </button>
      </section>
    )
  }

  const review: RoutineReview = data.review

  return (
    <article aria-labelledby="routine-review-heading">
      <p
        style={{
          margin: '0 0 8px',
          color: accent,
          fontSize: typography.label.fontSize,
          fontWeight: 600,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }}
      >
        Routine review
      </p>
      <h1
        id="routine-review-heading"
        style={{ margin: 0, color: textPrimary, fontSize: '28px', lineHeight: 1.15 }}
      >
        {routineLabel(review.routine)} review for {review.target_date}
      </h1>
      <p style={{ color: textSecondary, margin: '10px 0 24px' }}>
        {review.routine_status === 'published_fallback' ? 'Fallback review' : 'Claude review'}
      </p>

      <div
        style={{
          padding: '20px',
          backgroundColor: secondary,
          border: `1px solid ${border}`,
          borderRadius: '12px',
          color: textPrimary,
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
        }}
      >
        {review.review_text}
      </div>

      {review.action_ids.length > 0 && (
        <section aria-labelledby="review-actions-heading" style={{ marginTop: '24px' }}>
          <h2 id="review-actions-heading" style={{ color: textPrimary, fontSize: typography.heading.fontSize }}>
            Actions
          </h2>
          <ul style={{ color: textSecondary }}>
            {review.action_ids.map((actionId) => <li key={actionId}>{actionId}</li>)}
          </ul>
        </section>
      )}

      {review.partial_actions.length > 0 && (
        <section aria-labelledby="partial-actions-heading" style={{ marginTop: '24px' }}>
          <h2 id="partial-actions-heading" style={{ color: textPrimary, fontSize: typography.heading.fontSize }}>
            Partial actions
          </h2>
          {review.partial_actions.map((partialAction, index) => (
            <pre
              key={`${review.review_id}-partial-${index}`}
              style={{
                margin: '12px 0 0',
                padding: '12px',
                overflowX: 'auto',
                backgroundColor: secondary,
                border: `1px solid ${border}`,
                borderRadius: '8px',
                color: textSecondary,
              }}
            >
              {JSON.stringify(partialAction, null, 2)}
            </pre>
          ))}
        </section>
      )}

      <section aria-label="Claude session" style={{ marginTop: '28px' }}>
        {review.claude_session_url ? (
          <a
            href={review.claude_session_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: accent }}
          >
            Continue in Claude
          </a>
        ) : (
          <p style={{ margin: 0, color: textSecondary }}>Claude session unavailable for this review.</p>
        )}
      </section>
    </article>
  )
}

export function ReviewDetailPage() {
  const { routine, targetDate } = useParams()

  if (!isRoutineName(routine) || !targetDate) {
    return <p>This routine review is unavailable.</p>
  }

  return (
    <main
      style={{
        flex: 1,
        minHeight: '100%',
        padding: '32px 20px 96px',
        backgroundColor: dominant,
        color: textPrimary,
        fontFamily,
      }}
    >
      <div style={{ maxWidth: '760px', margin: '0 auto' }}>
        <ReviewDetail routine={routine} targetDate={targetDate} />
      </div>
    </main>
  )
}
