/**
 * Design tokens for Klaus Hub — single source of truth for the dark theme.
 *
 * These values are locked by the Phase 26 UI-SPEC and must not be changed
 * without a corresponding UI-SPEC revision.
 *
 * Color roles (from UI-SPEC § Color):
 *  - dominant (60%): page background, sidebar, main surface
 *  - secondary (30%): cards, chat panel, bottom tab bar
 *  - accent (10%): unread badge, active tab/sidebar icon, send button, now-line, install CTA
 *  - destructive: sign-out-everywhere CTA, send-error state
 *  - textPrimary: all body copy and headings on dark surfaces
 *  - textSecondary: timestamps, metadata, dimmed past timeline items
 *  - border: dividers, card borders, separator lines
 *  - success: message "sent" checkmark, "connected" indicator
 *  - offline: 4px top border strip on offline banner only
 *  - skeleton: animated shimmer background for in-flight API data
 *
 * Typography (from UI-SPEC § Typography):
 *  Exactly 2 weights: 400 (regular) and 600 (semibold). No 500.
 */

// --------------------------------------------------------------------------- //
// Colors                                                                       //
// --------------------------------------------------------------------------- //

export const dominant = '#0A0A0A'
export const secondary = '#1A1A1A'
export const accent = '#6366F1'       // indigo-500 — reserved uses only (see above)
export const destructive = '#EF4444' // red-500
export const textPrimary = '#F9FAFB'
export const textSecondary = '#9CA3AF'
export const border = '#2A2A2A'
export const success = '#22C55E'     // green-500
export const offline = '#F59E0B'     // amber-500 — top border strip only
export const skeleton = '#1F1F1F'    // animated shimmer background

// --------------------------------------------------------------------------- //
// Typography                                                                   //
// --------------------------------------------------------------------------- //

/** System font stack — no web font download. */
export const fontFamily = 'system-ui, -apple-system, "Segoe UI", sans-serif'

/** Exactly 2 weights per UI-SPEC. */
export const fontWeightRegular = 400
export const fontWeightSemibold = 600

/** Type scale. */
export const typography = {
  body:    { fontSize: '16px', fontWeight: fontWeightRegular,  lineHeight: 1.5  },
  label:   { fontSize: '13px', fontWeight: fontWeightRegular,  lineHeight: 1.4  },
  heading: { fontSize: '20px', fontWeight: fontWeightSemibold, lineHeight: 1.2  },
  display: { fontSize: '28px', fontWeight: fontWeightSemibold, lineHeight: 1.15 },
} as const
