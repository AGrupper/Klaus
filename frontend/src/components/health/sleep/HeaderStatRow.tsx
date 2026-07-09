/**
 * HeaderStatRow.tsx — Last-night stat strip for the Sleep & Recovery sub-page
 * (HLTH-03, D-19).
 *
 * Adapts the exact NutritionStrip pattern from
 * frontend/src/components/timeline/TimelineHeader.tsx (~119-199): horizontal
 * scroll strip on phone, inline row on desktop — layout driven by Tailwind
 * classes only (`flex md:hidden` / `hidden md:flex`), NEVER an inline CSS
 * display override (documented responsive-display gotcha, bit 4x per
 * project memory, re-swept for Phase 30).
 *
 * 5 stats sourced from SleepHeaderStats: HRV, Sleep score, Body battery,
 * Resting HR, Readiness — Body(16px/600) value over Label(13px/400
 * textSecondary) label. `header_stats` is null (or any individual field may
 * be null) when the biometric pipeline hasn't populated a row for the
 * selected range or a given metric is missing — defensive `?? ` null
 * coalescing throughout, matching NutritionStrip's `.toFixed()` crash guard.
 * If all 5 stats are null, renders nothing (the pipeline-not-live guard in
 * SleepRecoveryPage handles the `pipeline_active: false` case separately).
 */
import { textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'
import type { SleepHeaderStats } from '../../../api/health'

interface HeaderStatRowProps {
  stats: SleepHeaderStats | null
}

interface StatItem {
  label: string
  value: string | null
}

export function HeaderStatRow({ stats }: HeaderStatRowProps) {
  const hrv = stats?.hrv_overnight ?? null
  const sleepScore = stats?.sleep_score ?? null
  const bodyBattery = stats?.body_battery_max ?? null
  const restingHr = stats?.resting_hr ?? null
  const readiness = stats?.training_readiness ?? null

  // Nothing synced yet for any stat — render no strip rather than a row of
  // dashes (same "nothing rather than a row of zeros" precedent as
  // NutritionStrip).
  if (
    hrv === null &&
    sleepScore === null &&
    bodyBattery === null &&
    restingHr === null &&
    readiness === null
  ) {
    return null
  }

  const items: StatItem[] = [
    { label: 'HRV', value: hrv !== null ? `${hrv} ms` : null },
    { label: 'Sleep score', value: sleepScore !== null ? String(sleepScore) : null },
    { label: 'Body battery', value: bodyBattery !== null ? `${bodyBattery}/100` : null },
    { label: 'Resting HR', value: restingHr !== null ? `${restingHr} bpm` : null },
    { label: 'Readiness', value: readiness !== null ? String(readiness) : null },
  ]

  function renderItem({ label, value }: StatItem) {
    if (value === null) return null
    return (
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
            fontWeight: 600,
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
    )
  }

  return (
    <>
      {/* Phone — horizontal scroll strip. Class-driven display only (never
          inline `display`) so `md:hidden` isn't overridden. */}
      <div
        className="flex md:hidden"
        style={{ overflowX: 'auto', gap: '16px', paddingBottom: '4px' }}
        aria-label="Last night's recovery stats"
      >
        {items.map(renderItem)}
      </div>
      {/* Desktop — inline row, no scroll needed. */}
      <div
        className="hidden md:flex"
        style={{ gap: '24px' }}
        aria-label="Last night's recovery stats"
      >
        {items.map(renderItem)}
      </div>
    </>
  )
}
