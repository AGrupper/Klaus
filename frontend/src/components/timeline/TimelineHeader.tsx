/**
 * TimelineHeader.tsx — Date heading + Garmin morning stats + weather (TIME-02).
 *
 * UI-SPEC constraints:
 *   - Date heading: Heading (20px/600/1.2) "Today — {Weekday Day Month}" (e.g., "Today — Sunday 15 June")
 *   - Garmin stats: sleep/HRV/body battery rows — Label (13px/400) in textSecondary
 *   - Weather: one-line summary — Label in textSecondary
 *   - Collapses to one line on phone (sleep stat visible; HRV/body battery hidden below md:)
 *   - D-06 placeholder when garmin is null: "Sleep stats syncing…" — PlaceholderCard (no shimmer)
 *   - Phone glance strip: nutrition totals as a horizontal scroll row below the header
 *     (TIME-08 on phone; desktop version is in GlanceRail)
 *
 * Loading state: the real Skeleton component ships in 26-09. Until then, we use a
 * local "SkeletonLine" stub with animate-pulse on a #1F1F1F background so in-flight
 * states are distinguishable from D-06 placeholders. This stub will be replaced when
 * 26-09 ships — documented as a known TODO in SUMMARY.md.
 *
 * Phone-only gear button (D-15/D-20 nav placement note — desktop already has a
 * Settings entry in Sidebar; BottomTabs has no free slot) routes to /settings.
 * Uses a Tailwind `md:hidden` class, never inline `display` (responsive-display
 * gotcha — inline display overrides Tailwind's md: classes).
 */

import { useNavigate } from 'react-router-dom'
import { Settings } from 'lucide-react'
import { skeleton, textPrimary, textSecondary, border, typography, fontFamily } from '../../tokens'
import { PlaceholderCard } from './PlaceholderCard'
import type { GarminStats, Macros } from '../../api/today'

// ---------------------------------------------------------------------------
// Local skeleton stub (to be replaced by shared Skeleton from 26-09)
// ---------------------------------------------------------------------------

/** Temporary skeleton line stub. 26-09 ships the shared Skeleton component. */
function SkeletonLine({ width = '100%' }: { width?: string }) {
  return (
    <div
      className="animate-pulse"
      style={{
        height: '14px',
        width,
        backgroundColor: skeleton,
        borderRadius: '4px',
      }}
      aria-hidden="true"
    />
  )
}

// ---------------------------------------------------------------------------
// Date formatting helpers
// ---------------------------------------------------------------------------

/** Format a date for the header: "Today — Sunday 15 June" */
function formatDateHeader(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`)
  const weekday = date.toLocaleDateString('en-GB', { weekday: 'long' })
  const day = date.getDate()
  const month = date.toLocaleDateString('en-GB', { month: 'long' })
  return `Today — ${weekday} ${day} ${month}`
}

// ---------------------------------------------------------------------------
// Garmin stats sub-section
// ---------------------------------------------------------------------------

interface GarminStatsRowProps {
  garmin: GarminStats
}

function GarminStatsRows({ garmin }: GarminStatsRowProps) {
  const rows: Array<{ label: string; value: string | null }> = [
    {
      label: 'Sleep',
      value: garmin.sleep !== null ? `${garmin.sleep.toFixed(1)}h` : null,
    },
    {
      label: 'HRV',
      value: garmin.hrv !== null ? `${garmin.hrv} ms` : null,
    },
    {
      label: 'Body battery',
      value: garmin.body_battery !== null ? `${garmin.body_battery}/100` : null,
    },
    {
      label: 'Resting HR',
      value: garmin.resting_hr !== null ? `${garmin.resting_hr} bpm` : null,
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      {rows.map(({ label, value }) =>
        value !== null ? (
          <p
            key={label}
            style={{
              margin: 0,
              fontSize: typography.label.fontSize,
              fontWeight: typography.label.fontWeight,
              lineHeight: typography.label.lineHeight,
              color: textSecondary,
              fontFamily,
            }}
          >
            <span style={{ color: textPrimary }}>{label}</span>{' '}
            {value}
          </p>
        ) : null,
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Nutrition totals phone strip (TIME-08 on mobile)
// ---------------------------------------------------------------------------

interface NutritionStripProps {
  totals: Macros
}

/** Horizontal scroll strip of nutrition running totals — shown below the header on phone. */
function NutritionStrip({ totals }: NutritionStripProps) {
  // Defensive coercion: /api/today returns an empty object (or null fields) on a
  // fresh day before any meal is logged. Calling .toFixed() on a missing value
  // throws and — with no error boundary — blanks the entire app. Coerce to 0.
  const kcal = totals?.kcal ?? 0
  const protein = totals?.protein_g ?? 0
  const carbs = totals?.carbs_g ?? 0
  const fat = totals?.fat_g ?? 0
  const fiber = totals?.fiber_g ?? 0

  // Nothing logged yet — render no strip rather than a row of zeros.
  if (!kcal && !protein && !carbs && !fat && !fiber) return null

  const items = [
    { label: 'kcal', value: String(kcal) },
    { label: 'protein', value: `${protein.toFixed(0)}g` },
    { label: 'carbs', value: `${carbs.toFixed(0)}g` },
    { label: 'fat', value: `${fat.toFixed(0)}g` },
    ...(fiber > 0 ? [{ label: 'fiber', value: `${fiber.toFixed(0)}g` }] : []),
  ]

  return (
    /*
     * Phone-only strip — surfaced as horizontal scroll row below the header.
     * Hidden on desktop (md:hidden) because GlanceRail handles desktop nutrition.
     */
    <div
      className="md:hidden"
      style={{
        display: 'flex',
        overflowX: 'auto',
        gap: '12px',
        paddingTop: '8px',
        paddingBottom: '4px',
      }}
      aria-label="Today's nutrition totals"
    >
      {items.map(({ label, value }) => (
        <div
          key={label}
          style={{
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '2px',
          }}
        >
          <span
            style={{
              fontSize: typography.body.fontSize,
              fontWeight: typography.body.fontWeight,
              lineHeight: typography.body.lineHeight,
              color: textPrimary,
              fontFamily,
            }}
          >
            {value}
          </span>
          <span
            style={{
              fontSize: typography.label.fontSize,
              fontWeight: typography.label.fontWeight,
              lineHeight: typography.label.lineHeight,
              color: textSecondary,
              fontFamily,
            }}
          >
            {label}
          </span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// TimelineHeader props + component
// ---------------------------------------------------------------------------

interface TimelineHeaderProps {
  /** ISO date string "YYYY-MM-DD" (Asia/Jerusalem) from /api/today. */
  today: string
  /** Garmin morning stats — null → D-06 placeholder (D-06). */
  garmin: GarminStats | null
  /** One-line weather summary — null = unavailable (not a D-06 placeholder). */
  weather: string | null
  /** Whether the /api/today query is in its initial loading state (HUB-03). */
  isLoading?: boolean
  /** Nutrition running totals for the phone strip (TIME-08). */
  nutritionTotals: Macros
}

export function TimelineHeader({
  today,
  garmin,
  weather,
  isLoading = false,
  nutritionTotals,
}: TimelineHeaderProps) {
  const navigate = useNavigate()

  return (
    <header
      style={{
        padding: '16px 16px 0',
        borderBottom: `1px solid ${border}`,
        paddingBottom: '16px',
        fontFamily,
      }}
    >
      {/* Date heading row — Heading (20px/600/1.2) + phone-only settings gear */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '8px',
          margin: '0 0 12px',
        }}
      >
        <h1
          style={{
            fontSize: typography.heading.fontSize,
            fontWeight: typography.heading.fontWeight,
            lineHeight: typography.heading.lineHeight,
            color: textPrimary,
            margin: 0,
            fontFamily,
          }}
        >
          {formatDateHeader(today)}
        </h1>

        {/* Phone-only gear → /settings (desktop uses Sidebar's Settings entry) */}
        <button
          type="button"
          className="md:hidden"
          title="Settings"
          aria-label="Settings"
          onClick={() => navigate('/settings')}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '44px',
            height: '44px',
            flexShrink: 0,
            background: 'none',
            border: 'none',
            borderRadius: '8px',
            color: textSecondary,
            cursor: 'pointer',
          }}
        >
          <Settings size={20} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </div>

      {/* Garmin stats section — TIME-02 */}
      {isLoading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '8px' }}>
          <SkeletonLine width="60%" />
          <SkeletonLine width="45%" />
          <SkeletonLine width="50%" />
        </div>
      ) : garmin !== null ? (
        <div style={{ marginBottom: '8px' }}>
          <GarminStatsRows garmin={garmin} />
        </div>
      ) : (
        /* D-06 placeholder — "Sleep stats syncing…" — no shimmer */
        <div style={{ marginBottom: '8px' }}>
          <PlaceholderCard text="Sleep stats syncing…" />
        </div>
      )}

      {/* Weather one-liner — TIME-02 */}
      {weather && (
        <p
          style={{
            margin: '0 0 4px',
            fontSize: typography.label.fontSize,
            fontWeight: typography.label.fontWeight,
            lineHeight: typography.label.lineHeight,
            color: textSecondary,
            fontFamily,
          }}
        >
          {weather}
        </p>
      )}

      {/* Phone nutrition strip (TIME-08 on mobile) */}
      <NutritionStrip totals={nutritionTotals} />
    </header>
  )
}
