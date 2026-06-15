/**
 * GlanceRail.tsx — Desktop right column for at-a-glance data.
 *
 * UI-SPEC constraints:
 *   - Desktop: 280px fixed right column; hidden md:block
 *   - Card on #1A1A1A background
 *   - "Nutrition" section heading at Heading (20px/600)
 *   - Slots for nutrition running totals (data wired in 26-07)
 *   - Phone: surfaced as a horizontal scroll strip below the timeline header
 *     (rendered here for now as a hidden mobile slot; 26-07 handles phone layout)
 */

export function GlanceRail() {
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
            fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          }}
        >
          Nutrition
        </h2>

        {/*
         * Data slot — running totals wired in 26-07.
         * For now render the D-06 placeholder copy.
         */}
        <p
          style={{
            fontSize: '13px',
            fontWeight: 400,
            lineHeight: 1.4,
            color: '#9CA3AF',
            margin: 0,
            fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          }}
        >
          No meals logged yet today.
        </p>
      </div>
    </aside>
  )
}
