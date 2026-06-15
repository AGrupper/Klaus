/**
 * GlanceRail.tsx — Desktop right column for at-a-glance data.
 *
 * UI-SPEC constraints:
 *   - Desktop: 280px fixed right column; hidden md:block
 *   - Card on #1A1A1A background
 *   - "Nutrition" section heading at Heading (20px/600)
 *   - Running nutrition totals (TIME-08) from /api/today via useToday()
 *
 * useToday() shares the cached ['today'] query (React Query dedupes), so this
 * does not add a second network round-trip alongside the timeline.
 */
import { useToday } from '../../hooks/useToday'

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

function NutritionRow({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        padding: '6px 0',
        fontFamily: FONT,
      }}
    >
      <span style={{ fontSize: '13px', fontWeight: 400, color: '#9CA3AF' }}>{label}</span>
      <span style={{ fontSize: '14px', fontWeight: 600, color: '#F9FAFB' }}>{value}</span>
    </div>
  )
}

export function GlanceRail() {
  const { data } = useToday()
  const totals = data?.nutrition_totals
  const hasData = !!totals && totals.kcal > 0

  return (
    /*
     * hidden md:block — desktop only column (280px).
     * On phone this element is hidden; the glance strip below the timeline
     * header is rendered in the TimelineHeader component (26-07).
     */
    <aside
      className="hidden md:block"
      style={{
        width: '280px',
        flexShrink: 0,
        borderLeft: '1px solid #2A2A2A',
        backgroundColor: '#0A0A0A',
        overflowY: 'auto',
        padding: '16px',
      }}
      aria-label="At a glance"
    >
      {/* Nutrition card */}
      <div
        style={{
          backgroundColor: '#1A1A1A',
          border: '1px solid #2A2A2A',
          borderRadius: '10px',
          padding: '16px',
        }}
      >
        {/* Section heading — Heading (20px/600) */}
        <h2
          style={{
            fontSize: '20px',
            fontWeight: 600,
            lineHeight: 1.2,
            color: '#F9FAFB',
            margin: '0 0 12px',
            fontFamily: FONT,
          }}
        >
          Nutrition
        </h2>

        {hasData ? (
          <div>
            <NutritionRow label="Calories" value={`${Math.round(totals!.kcal)} kcal`} />
            <NutritionRow label="Protein" value={`${Math.round(totals!.protein_g)} g`} />
            <NutritionRow label="Carbs" value={`${Math.round(totals!.carbs_g)} g`} />
            <NutritionRow label="Fat" value={`${Math.round(totals!.fat_g)} g`} />
            <NutritionRow label="Fiber" value={`${Math.round(totals!.fiber_g)} g`} />
          </div>
        ) : (
          <p
            style={{
              fontSize: '13px',
              fontWeight: 400,
              lineHeight: 1.4,
              color: '#9CA3AF',
              margin: 0,
              fontFamily: FONT,
            }}
          >
            No meals logged yet today.
          </p>
        )}
      </div>
    </aside>
  )
}
