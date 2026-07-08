/**
 * SleepRecoveryPage.tsx — Root content for the Sleep sub-tab (HLTH-03).
 *
 * `RangeToggle` (owns its own `useState<RangeKey>('30d')`, D-06 — never
 * persisted) → `useSleepRecovery(range)` → `HeaderStatRow` + three stacked
 * `ChartCard`s (HRV, Sleep, Body Battery) — vertically stacked per D-17
 * (recovery is read as a narrative, not side-by-side comparisons).
 *
 * Pipeline-not-live guard (D-06-style, new for this phase, T-30-07-02):
 * `pipeline_active: false` means the `daily_biometrics` pipeline has NEVER
 * populated a row — distinct from "no rows in the selected range". In that
 * case render the `PlaceholderCard` "isn't syncing yet" copy INSTEAD of the
 * header stats + charts entirely. This guards the documented biometric-sync
 * cron deploy dependency (30-CONTEXT.md). When `pipeline_active` is true but
 * the selected range has zero rows, the normal per-chart `ChartEmptyState`
 * handles it (each chart component already does this) — the two states are
 * visibly distinct: one placeholder card vs. header stats + three charts
 * (each showing its own "No data" message).
 *
 * Loading: shared `Skeleton` shimmer. Error: fixed copy per 30-UI-SPEC
 * Copywriting Contract § Page-level.
 */
import { useState } from 'react'
import { useSleepRecovery } from '../../../hooks/useHealth'
import { RangeToggle } from '../RangeToggle'
import { HeaderStatRow } from './HeaderStatRow'
import { HRVChart } from './HRVChart'
import { SleepChart } from './SleepChart'
import { BodyBatteryChart } from './BodyBatteryChart'
import { PlaceholderCard } from '../../timeline/PlaceholderCard'
import { Skeleton } from '../../shared/Skeleton'
import { textSecondary, typography, fontFamily } from '../../../tokens'
import type { RangeKey } from '../../../api/health'

/** 160 phone / 220 desktop per 30-UI-SPEC Spacing § Chart height. */
const CHART_HEIGHT_PHONE = 160
const CHART_HEIGHT_DESKTOP = 220

export function SleepRecoveryPage() {
  const [range, setRange] = useState<RangeKey>('30d')
  const { data, isLoading, isError } = useSleepRecovery(range)

  const isPhone = typeof window !== 'undefined' && window.innerWidth < 768
  const chartHeight = isPhone ? CHART_HEIGHT_PHONE : CHART_HEIGHT_DESKTOP

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '16px' }}>
      <RangeToggle value={range} onChange={setRange} />

      {isLoading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <Skeleton
            className="h-16 w-full rounded-lg"
            aria-label="Loading sleep & recovery data…"
          />
          <Skeleton
            className="h-40 w-full rounded-lg"
            aria-label="Loading sleep & recovery data…"
          />
          <Skeleton
            className="h-40 w-full rounded-lg"
            aria-label="Loading sleep & recovery data…"
          />
          <Skeleton
            className="h-40 w-full rounded-lg"
            aria-label="Loading sleep & recovery data…"
          />
        </div>
      ) : isError || !data ? (
        <p
          role="alert"
          style={{
            margin: 0,
            fontSize: typography.label.fontSize,
            fontWeight: typography.label.fontWeight,
            lineHeight: typography.label.lineHeight,
            color: textSecondary,
            fontFamily,
          }}
        >
          Couldn't load sleep & recovery data — pull to refresh.
        </p>
      ) : !data.pipeline_active ? (
        // T-30-07-02: pipeline has NEVER populated a row — distinct
        // "isn't syncing yet" placeholder, never silently implying zero data.
        <PlaceholderCard text="Sleep & recovery data isn't syncing yet." />
      ) : (
        <>
          <HeaderStatRow stats={data.header_stats} />
          <HRVChart
            overnight={data.series.hrv_overnight}
            baseline={data.series.hrv_baseline}
            height={chartHeight}
          />
          <SleepChart
            score={data.series.sleep_score}
            duration={data.series.sleep_duration}
            height={chartHeight}
          />
          <BodyBatteryChart points={data.series.body_battery_max} height={chartHeight} />
        </>
      )}
    </div>
  )
}
