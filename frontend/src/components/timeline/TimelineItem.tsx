/**
 * TimelineItem.tsx — Single event row in the Today timeline.
 *
 * UI-SPEC constraints:
 *   - Card on #1A1A1A background with #2A2A2A border
 *   - Title: Body (16px/400/1.5) in textPrimary
 *   - Time + metadata: Label (13px/400/1.4) in textSecondary
 *   - Past items (end < Date.now()): opacity-[0.45] (D-04 dimming via opacity, NOT a color change)
 *   - Leave-by / Get Ready chip: Label text when leave_by/get_ready_at is present (TIME-05)
 *   - Meal rows: render slot_label + macros; NEVER "eaten at" / eating-time framing (TIME-03 / CLAUDE.md §6)
 *   - Training item: render item + block_context as a chip (TIME-04)
 *   - Minimum touch target: 44px height on all interactive surfaces (iOS HIG)
 *
 * TIME-03 invariant — HealthKit/Lifesum canonical slot times (08:00/12:00/20:00)
 * are NOT eating times. slot_label ("Breakfast", "Lunch", "Dinner") is what we
 * render. The server enforces this at the API level; this component enforces it
 * at the render level by only reading slot_label from MealItem, never a timestamp.
 *
 * Item variants:
 *   - type === 'event':    regular calendar event (title + time range + optional location chip)
 *   - type === 'meal':     meal slot label + macro grid
 *   - type === 'training': training item + block context chip
 */

import { secondary, border, textPrimary, textSecondary, accent, typography, fontFamily } from '../../tokens'
import type { TimedEvent, MealItem, TrainingItem } from '../../api/today'

// ---------------------------------------------------------------------------
// Variant types
// ---------------------------------------------------------------------------

interface EventItemProps {
  type: 'event'
  event: TimedEvent
  isPast: boolean
}

interface MealItemProps {
  type: 'meal'
  meal: MealItem
  /** Meals are never in the "past" in the same sense as events — always rendered at full opacity. */
  isPast?: false
}

interface TrainingItemProps {
  type: 'training'
  training: TrainingItem
  isPast: boolean
}

export type TimelineItemProps = EventItemProps | MealItemProps | TrainingItemProps

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format an ISO datetime to "HH:MM" for display. */
function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-IL', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}

/** Round a number to one decimal place and strip trailing zero. */
function fmt1(n: number): string {
  return n % 1 === 0 ? String(n) : n.toFixed(1)
}

// ---------------------------------------------------------------------------
// Chip sub-component (for leave-by, get-ready, block-context)
// ---------------------------------------------------------------------------

interface ChipProps {
  label: string
}

function Chip({ label }: ChipProps) {
  return (
    <span
      style={{
        display: 'inline-block',
        fontSize: typography.label.fontSize,
        fontWeight: typography.label.fontWeight,
        lineHeight: 1,
        color: textSecondary,
        fontFamily,
        backgroundColor: '#2A2A2A',
        borderRadius: '6px',
        padding: '3px 8px',
        marginTop: '4px',
      }}
    >
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Event variant
// ---------------------------------------------------------------------------

function EventItem({ event, isPast }: { event: TimedEvent; isPast: boolean }) {
  return (
    <article
      data-past={isPast ? 'true' : undefined}
      style={{
        opacity: isPast ? 0.45 : 1,
        backgroundColor: secondary,
        border: `1px solid ${border}`,
        borderRadius: '10px',
        padding: '12px 16px',
        minHeight: '44px',
        fontFamily,
      }}
    >
      {/* Event title — Body */}
      <p
        style={{
          margin: '0 0 4px',
          fontSize: typography.body.fontSize,
          fontWeight: typography.body.fontWeight,
          lineHeight: typography.body.lineHeight,
          color: textPrimary,
        }}
      >
        {event.title}
      </p>

      {/* Time range — Label */}
      <p
        style={{
          margin: 0,
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: textSecondary,
        }}
      >
        {formatTime(event.start)} – {formatTime(event.end)}
        {event.location ? ` · ${event.location}` : ''}
      </p>

      {/* TIME-05: Leave-by chip */}
      {event.leave_by && (
        <div style={{ marginTop: '4px' }}>
          <Chip label={`Leave by ${formatTime(event.leave_by)}`} />
        </div>
      )}

      {/* TIME-05: Get Ready chip */}
      {event.get_ready_at && (
        <div style={{ marginTop: '4px' }}>
          <Chip label={`Get Ready at ${formatTime(event.get_ready_at)}`} />
        </div>
      )}
    </article>
  )
}

// ---------------------------------------------------------------------------
// Meal variant — TIME-03: slot label + macros ONLY, never eating-time framing
// ---------------------------------------------------------------------------

function MealRow({ meal }: { meal: MealItem }) {
  const { slot_label, macros } = meal
  return (
    <article
      style={{
        backgroundColor: secondary,
        border: `1px solid ${border}`,
        borderRadius: '10px',
        padding: '12px 16px',
        minHeight: '44px',
        fontFamily,
      }}
    >
      {/* Slot label — Body (e.g., "Breakfast", "Lunch", "Dinner") — TIME-03 */}
      <p
        style={{
          margin: '0 0 4px',
          fontSize: typography.body.fontSize,
          fontWeight: typography.body.fontWeight,
          lineHeight: typography.body.lineHeight,
          color: textPrimary,
        }}
      >
        {slot_label}
      </p>

      {/* Macros — Label in textSecondary — TIME-03 */}
      <p
        style={{
          margin: 0,
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: textSecondary,
        }}
      >
        {macros.kcal} kcal · {fmt1(macros.protein_g)}g protein · {fmt1(macros.carbs_g)}g carbs · {fmt1(macros.fat_g)}g fat
        {macros.fiber_g > 0 ? ` · ${fmt1(macros.fiber_g)}g fiber` : ''}
      </p>
    </article>
  )
}

// ---------------------------------------------------------------------------
// Training variant — TIME-04: item + block_context chip
// ---------------------------------------------------------------------------

function TrainingRow({ training, isPast }: { training: TrainingItem; isPast: boolean }) {
  return (
    <article
      data-past={isPast ? 'true' : undefined}
      style={{
        opacity: isPast ? 0.45 : 1,
        backgroundColor: secondary,
        border: `1px solid ${border}`,
        borderRadius: '10px',
        padding: '12px 16px',
        minHeight: '44px',
        fontFamily,
      }}
    >
      {/* Training item — Body */}
      <p
        style={{
          margin: '0 0 4px',
          fontSize: typography.body.fontSize,
          fontWeight: typography.body.fontWeight,
          lineHeight: typography.body.lineHeight,
          color: textPrimary,
        }}
      >
        {training.item}
      </p>

      {/* Block context chip — TIME-04 e.g. "Week 3 of 16 — Lower Body A" */}
      <Chip label={training.block_context} />
    </article>
  )
}

// ---------------------------------------------------------------------------
// Public component — dispatches to the correct variant
// ---------------------------------------------------------------------------

export function TimelineItem(props: TimelineItemProps) {
  if (props.type === 'meal') {
    return <MealRow meal={props.meal} />
  }
  if (props.type === 'training') {
    return <TrainingRow training={props.training} isPast={props.isPast} />
  }
  // Default: event
  return <EventItem event={props.event} isPast={props.isPast} />
}
