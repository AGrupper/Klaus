/**
 * Skeleton.tsx — Reusable animated shimmer for in-flight API fetches (HUB-03).
 *
 * Renders a #1F1F1F background with Tailwind animate-pulse over the #0A0A0A
 * surface. Use className to size/shape the skeleton to match the target element.
 *
 * This is the canonical Skeleton component for Phase 26. The 26-07 timeline
 * plan may have defined a local Skeleton stub — it should be replaced by
 * importing this component from 'components/shared/Skeleton'.
 *
 * Distinct from D-06 PlaceholderCard: skeletons shimmer for in-flight network
 * fetches; placeholders are stable text for data that genuinely won't exist yet.
 *
 * Accessibility: role="status" with a screen-reader-only label announces the
 * loading state to assistive technology.
 */
interface SkeletonProps {
  /** Additional Tailwind classes for sizing, shape, margin, etc. */
  className?: string
  /** Screen-reader label. Defaults to the locked UI-SPEC SR string. */
  'aria-label'?: string
}

export function Skeleton({
  className = '',
  'aria-label': ariaLabel = 'Loading today\'s timeline…',
}: SkeletonProps) {
  return (
    <div
      role="status"
      aria-label={ariaLabel}
      className={`animate-pulse rounded ${className}`}
      style={{ backgroundColor: '#1F1F1F' }}
    >
      <span className="sr-only">{ariaLabel}</span>
    </div>
  )
}
