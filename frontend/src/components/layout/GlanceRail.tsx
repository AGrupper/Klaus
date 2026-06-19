/**
 * GlanceRail.tsx — Desktop right column for at-a-glance data.
 *
 * UI-SPEC constraints:
 *   - Desktop: 280px fixed right column; hidden md:block
 *   - Card on #1A1A1A background
 *   - "Nutrition" section heading at Heading (20px/600)
 *   - Running nutrition totals (TIME-08) from /api/today via useToday()
 *
 * Phase 27 addition (D-12):
 *   - "Tasks" card below the Nutrition card, consuming useTaskSummary()
 *   - Shows "N due today" (textPrimary value) + "N overdue" (destructive #EF4444 when >0,
 *     hidden when 0). Tapping the card navigates to /tasks.
 *   - useTaskSummary shares TASK_SUMMARY_QUERY_KEY with DueTasksBand — react-query
 *     deduplicates: one fetch serves both consumers.
 *
 * useToday() shares the cached ['today'] query (React Query dedupes), so this
 * does not add a second network round-trip alongside the timeline.
 */
import { useNavigate } from 'react-router-dom'
import { useToday } from '../../hooks/useToday'
import { useTaskSummary } from '../../hooks/useTaskSummary'

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
  const navigate = useNavigate()
  const { data } = useToday()
  const { data: taskSummary } = useTaskSummary()

  const totals = data?.nutrition_totals
  const hasData = !!totals && totals.kcal > 0

  const dueToday = taskSummary?.due_today ?? 0
  const overdue = taskSummary?.overdue ?? 0

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
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
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

      {/* Tasks card (D-12) — tappable, navigates to /tasks */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => navigate('/tasks')}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && navigate('/tasks')}
        aria-label="Tasks overview — navigate to tasks"
        style={{
          backgroundColor: '#1A1A1A',
          border: '1px solid #2A2A2A',
          borderRadius: '10px',
          padding: '16px',
          cursor: 'pointer',
        }}
      >
        {/* Section heading */}
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
          Tasks
        </h2>

        {/* "N due today" row — always shown */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            padding: '6px 0',
            fontFamily: FONT,
          }}
        >
          <span style={{ fontSize: '13px', fontWeight: 400, color: '#9CA3AF' }}>
            due today
          </span>
          <span style={{ fontSize: '14px', fontWeight: 600, color: '#F9FAFB' }}>
            {dueToday}
          </span>
        </div>

        {/* "N overdue" row — hidden when overdue === 0 */}
        {overdue > 0 && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              padding: '6px 0',
              fontFamily: FONT,
            }}
          >
            <span style={{ fontSize: '13px', fontWeight: 400, color: '#9CA3AF' }}>
              overdue
            </span>
            <span style={{ fontSize: '14px', fontWeight: 600, color: '#EF4444' }}>
              {overdue}
            </span>
          </div>
        )}
      </div>
    </aside>
  )
}
