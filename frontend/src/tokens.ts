/**
 * Design tokens for the Paper Hub — the Native skin, Amit's palette.
 *
 * Two layers:
 *  1. CSS custom properties on :root (declared in index.css, defaults below).
 *     Components reference them via `var(--...)` so the Customize sheet can
 *     re-theme the whole app at runtime with setProperty — no re-render pass.
 *  2. These TS exports for the few places that need a literal (canvas, SVG
 *     attrs, meta tags) or the default values to seed the sheet.
 *
 * Dynamic tokens (accent / flame / fonts) are user settings persisted by
 * PATCH /api/settings; applyAppearance() is the single writer of the vars.
 */

// --------------------------------------------------------------------------- //
// Static palette (Native skin)                                                //
// --------------------------------------------------------------------------- //

export const ground = '#F2F2F6'   // iOS grouped-list background
export const surface = '#FFFFFF'  // cards / grouped rows
export const ink = '#1C1C1E'      // primary text
export const muted = '#85858B'    // secondary text
export const faint = '#AEAEB4'    // tertiary / disabled
export const sep = '#E5E5EA'      // hairline separators
export const good = '#2E7D4F'     // success (send/connected/undo)
export const goodSoft = '#E7F2EB'
export const destructive = '#C0392B'

// Defaults for the dynamic tokens — Amit's picks from the mockup gate.
export const defaultAccent = '#1C2540'  // midnight
export const defaultFlame = '#B02A2A'   // dark red

// ---------------------------------------------------------------------------
// Palette — Google Calendar's event colours                                   //
// ---------------------------------------------------------------------------

/**
 * The eleven named colours Google Calendar uses for events, plus the two
 * defaults above. Amit asked for exactly this set and no free-form picker:
 * they're familiar, they're already tuned to read on a light ground, and a
 * fixed list means no unreadable choices.
 */
export const CALENDAR_COLORS: Array<{ name: string; hex: string }> = [
  { name: 'Tomato', hex: '#D50000' },
  { name: 'Flamingo', hex: '#E67C73' },
  { name: 'Tangerine', hex: '#F4511E' },
  { name: 'Banana', hex: '#F6BF26' },
  { name: 'Sage', hex: '#33B679' },
  { name: 'Basil', hex: '#0B8043' },
  { name: 'Peacock', hex: '#039BE5' },
  { name: 'Blueberry', hex: '#3F51B5' },
  { name: 'Lavender', hex: '#7986CB' },
  { name: 'Grape', hex: '#8E24AA' },
  { name: 'Graphite', hex: '#616161' },
]

/** Accent options: the calendar palette plus Klaus's own midnight. */
export const ACCENT_COLORS: Array<{ name: string; hex: string }> = [
  { name: 'Midnight', hex: defaultAccent },
  ...CALENDAR_COLORS,
]

/** Flame options: the calendar palette plus Klaus's own dark red. */
export const FLAME_COLORS: Array<{ name: string; hex: string }> = [
  { name: 'Ember', hex: defaultFlame },
  ...CALENDAR_COLORS,
]

export const radius = 12

// --------------------------------------------------------------------------- //
// Fonts — all four ship with iOS/macOS; zero downloads (Customize sheet)      //
// --------------------------------------------------------------------------- //

export type FontChoice = 'default' | 'serif' | 'rounded' | 'mono'

export const FONT_STACKS: Record<FontChoice, { ui: string; display: string }> = {
  default: {
    ui: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif',
    display: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", sans-serif',
  },
  serif: {
    ui: 'ui-serif, "New York", Georgia, serif',
    display: 'ui-serif, "New York", Georgia, serif',
  },
  rounded: {
    ui: 'ui-rounded, -apple-system, BlinkMacSystemFont, sans-serif',
    display: 'ui-rounded, -apple-system, BlinkMacSystemFont, sans-serif',
  },
  mono: {
    ui: 'ui-monospace, "SF Mono", Menlo, monospace',
    display: 'ui-monospace, "SF Mono", Menlo, monospace',
  },
}

// --------------------------------------------------------------------------- //
// Appearance application — single writer of the dynamic CSS vars              //
// --------------------------------------------------------------------------- //

export interface Appearance {
  accent: string
  flame: string
  font: FontChoice
}

export const defaultAppearance: Appearance = {
  accent: defaultAccent,
  flame: defaultFlame,
  font: 'default',
}

/** Relative luminance 0..1 — decides readable text color over an accent. */
export function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
}

/** Return a normalized "#RRGGBB" or null if the input is not a valid hex. */
export function normalizeHex(value: string): string | null {
  const m = value.trim().replace(/^#/, '')
  return /^[0-9a-fA-F]{6}$/.test(m) ? `#${m.toUpperCase()}` : null
}

/**
 * Apply an appearance to the document. Idempotent; safe to call on every
 * settings load and on every Customize-sheet interaction (live preview).
 */
export function applyAppearance(appearance: Appearance): void {
  const root = document.documentElement.style
  const accent = normalizeHex(appearance.accent) ?? defaultAccent
  const flame = normalizeHex(appearance.flame) ?? defaultFlame
  const fonts = FONT_STACKS[appearance.font] ?? FONT_STACKS.default
  root.setProperty('--accent', accent)
  root.setProperty('--accent-ink', luminance(accent) > 0.62 ? ink : '#FFFFFF')
  root.setProperty('--flame', flame)
  root.setProperty('--flame-soft', `color-mix(in srgb, ${flame} 12%, white)`)
  root.setProperty('--font-ui', fonts.ui)
  root.setProperty('--font-display', fonts.display)
}
