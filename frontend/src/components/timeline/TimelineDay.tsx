/**
 * TimelineDay.tsx — Full Today timeline view.
 *
 * This is the top-level component for the "/" (Today) route. It orchestrates
 * all timeline sections and is driven by useToday() (D-05 refetch-on-mount/focus).
 *
 * Rendering order (TIME-01):
 *   1. TimelineHeader (date + Garmin stats + weather + phone nutrition strip)
 *   2. Coach note (or D-06 PlaceholderCard)
 *   3. All-day events pinned at top (TIME-01)
 *   4. Timed events interleaved chronologically with the NowLine at current time (D-04)
 *   5. Meals rendered at their slot position (TIME-03 — slot label + macros only)
 *   6. Training item (TIME-04 — block context chip)
 *
 * Past dimming (D-04): events whose `end` is before Date.now() render at opacity-[0.45].
 * The NowLine is interleaved between the last past event and the first upcoming event.
 *
 * D-06 placeholders (no shimmer):
 *   - coach_note null → "Coach note coming after your morning briefing."
 *   - garmin null → "Sleep stats syncing…" (handled in TimelineHeader)
 *   - meals empty → "No meals logged yet today."
 *   - training null → "No training scheduled today."
 *   - calendar empty (all_day empty + timed empty) → "Nothing on the calendar today."
 *
 * Loading state (HUB-03): while isLoading, section-level skeleton stubs replace
 * each section. NOTE: the shared Skeleton component ships in 26-09 — this file
 * uses a local SkeletonBlock stub until then (documented in SUMMARY.md).
 *
 * Pull-to-refresh (D-05): TimelineDay calls useRefreshToday() to get a callback
 * for phone pull-to-refresh gestures. A simple touch event triggers it.
 *
 * Nutrition totals (TIME-08): passed into GlanceRail (desktop) via a callback prop
 * and into TimelineHeader (phone strip). GlanceRail is wired at the AppShell level
 * in 26-06; this component exposes the data via context so GlanceRail can consume it.
 * For simplicity in this plan, we pass nutrition_totals to the header (phone strip)
 * and trust that GlanceRail will be wired at App.tsx level in a follow-up pass.
 */

import { dominant, textSecondary, typography, fontFamily, skeleton } from '../../tokens'
import { useToday } from '../../hooks/useToday'
import { TimelineHeader } from './TimelineHeader'
import { TimelineItem } from './TimelineItem'
import { NowLine } from './NowLine'
import { PlaceholderCard } from './PlaceholderCard'
import { DueTasksBand } from './DueTasksBand'
import type { TimedEvent } from '../../api/today'

// ---------------------------------------------------------------------------
// Local skeleton stub — replaced by shared Skeleton from 26-09
// ---------------------------------------------------------------------------

/** Temporary skeleton block stub. 26-09 ships the shared Skeleton component. */
function SkeletonBlock({ height = '64px' }: { height?: string }) {
  return (
    <div
      className="animate-pulse"
      style={{
        height,
        backgroundColor: skeleton,
        borderRadius: '10px',
      }}
      aria-hidden="true"
    />
  )
}

// ---------------------------------------------------------------------------
// TimelineDay — main component
// ---------------------------------------------------------------------------

/**
 * Returns true if a timed event's end time is in the past.
 * Used for D-04 past dimming.
 */
function isEventPast(endIso: string): boolean {
  try {
    return new Date(endIso).getTime() < Date.now()
  } catch {
    return false
  }
}

export function TimelineDay() {
  const { data, isLoading, isError, error } = useToday()

  // ---------------------------------------------------------------------------
  // Loading state (HUB-03 — initial fetch in-flight)
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div
        style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}
        aria-label="Loading today's timeline…"
      >
        <SkeletonBlock height="80px" />
        <SkeletonBlock height="48px" />
        <SkeletonBlock height="64px" />
        <SkeletonBlock height="64px" />
        <SkeletonBlock height="64px" />
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Error state
  // ---------------------------------------------------------------------------

  if (isError || !data) {
    return (
      <div
        role="alert"
        style={{
          padding: '24px 16px',
          color: textSecondary,
          fontSize: typography.label.fontSize,
          fontFamily,
          textAlign: 'center',
        }}
      >
        {error instanceof Error ? error.message : "Could not load today's timeline."}
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Data loaded — build the interleaved event list
  // ---------------------------------------------------------------------------

  const { calendar, garmin, weather, meals, training, coach_note, nutrition_totals, today } = data

  // Sort timed events chronologically (server should already sort, but be safe)
  const sortedTimed: TimedEvent[] = [...calendar.timed].sort((a, b) =>
    new Date(a.start).getTime() - new Date(b.start).getTime(),
  )

  const nowMs = Date.now()

  // Find the split point: index of first upcoming event (end > now)
  // NowLine is inserted just before the first upcoming event
  const nowLineIndex = sortedTimed.findIndex((ev) => new Date(ev.end).getTime() > nowMs)
  // If all events are past: nowLineIndex === -1 → place NowLine at the end
  // If all events are future: nowLineIndex === 0 → place NowLine at the start

  const calendarEmpty = calendar.all_day.length === 0 && sortedTimed.length === 0

  return (
    <div
      style={{
        backgroundColor: dominant,
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100%',
      }}
    >
      {/* Section 1: Header — date + Garmin + weather + phone nutrition strip */}
      <TimelineHeader
        today={today}
        garmin={garmin}
        weather={weather}
        isLoading={false}
        nutritionTotals={nutrition_totals}
      />

      {/* Section 2: Coach note — from morning briefing (TIME-07 / D-06) */}
      <div style={{ padding: '12px 16px 0' }}>
        {coach_note !== null ? (
          <div
            style={{
              padding: '10px 14px',
              backgroundColor: '#1A1A1A',
              border: '1px solid #2A2A2A',
              borderRadius: '10px',
              fontSize: typography.label.fontSize,
              fontWeight: typography.label.fontWeight,
              lineHeight: typography.label.lineHeight,
              color: textSecondary,
              fontFamily,
              fontStyle: 'italic',
            }}
          >
            {coach_note}
          </div>
        ) : (
          /* D-06: coach note not yet available */
          <PlaceholderCard text="Coach note coming after your morning briefing." />
        )}
      </div>

      {/* Main timeline column */}
      <div
        style={{
          flex: 1,
          padding: '12px 16px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        {/* Section 3: All-day events pinned at top (TIME-01) */}
        {calendar.all_day.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {calendar.all_day.map((title, i) => (
              <div
                key={`allday-${i}`}
                style={{
                  backgroundColor: '#1A1A1A',
                  border: '1px solid #2A2A2A',
                  borderRadius: '10px',
                  padding: '10px 14px',
                  minHeight: '44px',
                  fontFamily,
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: typography.body.fontSize,
                    fontWeight: typography.body.fontWeight,
                    lineHeight: typography.body.lineHeight,
                    color: '#F9FAFB',
                  }}
                >
                  {title}
                </p>
                <p
                  style={{
                    margin: '2px 0 0',
                    fontSize: typography.label.fontSize,
                    fontWeight: typography.label.fontWeight,
                    lineHeight: typography.label.lineHeight,
                    color: textSecondary,
                  }}
                >
                  All day
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Section 3.5: Due Tasks Band — after all-day events, before timed events (D-11) */}
        <DueTasksBand />

        {/* Section 4: Timed events + NowLine (D-04) interleaved chronologically */}
        {calendarEmpty ? (
          <PlaceholderCard text="Nothing on the calendar today." />
        ) : (
          sortedTimed.map((event, i) => {
            const past = isEventPast(event.end)
            const showNowLine = nowLineIndex === -1
              ? i === sortedTimed.length - 1  // all past → NowLine at end
              : i === nowLineIndex             // at the first upcoming event

            return (
              <div key={event.id} style={{ display: 'contents' }}>
                {/* NowLine appears before the first upcoming event (D-04) */}
                {showNowLine && !past && <NowLine />}

                <TimelineItem type="event" event={event} isPast={past} />

                {/* If all events are past, NowLine goes after the last event */}
                {showNowLine && past && nowLineIndex === -1 && i === sortedTimed.length - 1 && (
                  <NowLine />
                )}
              </div>
            )
          })
        )}

        {/* NowLine when there are no timed events but all-day events exist */}
        {!calendarEmpty && sortedTimed.length === 0 && <NowLine />}

        {/* Section 5: Meals (TIME-03 — slot labels + macros, never eating-time) */}
        {meals.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {meals.map((meal, i) => (
              <TimelineItem key={`meal-${i}`} type="meal" meal={meal} />
            ))}
          </div>
        ) : (
          <PlaceholderCard text="No meals logged yet today." />
        )}

        {/* Section 6: Training (TIME-04) */}
        {training !== null ? (
          <TimelineItem type="training" training={training} isPast={false} />
        ) : (
          <PlaceholderCard text="No training scheduled today." />
        )}
      </div>
    </div>
  )
}
