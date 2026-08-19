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

/**
 * Accent and flame keep Klaus's own deep, low-chroma sets rather than the
 * calendar palette — Amit preferred these once he saw both. The calendar
 * colours stay in use for per-routine identity, where variety is the point.
 */
export const ACCENT_COLORS: Array<{ name: string; hex: string }> = [
  { name: 'Midnight', hex: defaultAccent },
  { name: 'Black', hex: '#1C1C1E' },
  { name: 'Deep teal', hex: '#1F4E63' },
  { name: 'Forest', hex: '#20563A' },
]

export const FLAME_COLORS: Array<{ name: string; hex: string }> = [
  { name: 'Dark red', hex: defaultFlame },
  { name: 'Wine', hex: '#8F2D3C' },
  { name: 'Ember', hex: '#C2410C' },
  { name: 'Bronze', hex: '#B0762A' },
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
  /**
   * Klaus's mark — the glyph on the Talk to Klaus button and beside his note.
   * Empty, null or absent means the pen nib, which is the shipped default and
   * what every account had before this field existed.
   */
  emoji?: string | null
}

export const defaultAppearance: Appearance = {
  accent: defaultAccent,
  flame: defaultFlame,
  font: 'default',
  emoji: null,
}

// --------------------------------------------------------------------------- //
// Klaus's mark                                                                //
// --------------------------------------------------------------------------- //

/**
 * Suggested marks for the Customize sheet. Convenience only — the field below
 * takes anything the iOS emoji keyboard can produce, so this list never has to
 * be exhaustive.
 */
export const KLAUS_MARKS: string[] = ['🎩', '🧠', '⚡️', '🧭', '🦉', '🐺', '🖋️']

/** Hard cap on a stored mark. Mirrors the server's `max_length` (misc.py). */
export const KLAUS_MARK_MAX = 16

/**
 * Split text into grapheme clusters — what a person calls "one character".
 *
 * Slicing by code unit would split a flag or a skin-toned emoji into mojibake,
 * so anything that trims a mark has to count clusters instead: 👨‍👩‍👧 is one
 * family, not a man and two orphans. Intl.Segmenter is everywhere the Hub runs
 * (iOS 16.4+, Node 18+); the crude fallback is for anywhere it isn't.
 */
export function graphemes(value: string): string[] {
  // No segmenter: treat the whole string as one cluster rather than guessing
  // where to cut. The length check downstream rejects it if that is too long,
  // which is a mark that does not apply — never a mark rendered as mojibake.
  if (typeof Intl.Segmenter !== 'function') return value ? [value] : []
  return Array.from(
    new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(value),
    (part) => part.segment,
  )
}

/**
 * Drop characters that occupy the field but draw nothing — the LRM/RLM and
 * zero-width spaces a paste can smuggle in, which would otherwise leave the
 * button looking blank with no way to tell why.
 *
 * The zero-width joiner is the exception and has to survive: it is a format
 * character by category, but it is what holds 👨‍👩‍👧 together, and stripping
 * it turns one family into a man and two orphans.
 */
function stripInvisible(value: string | null | undefined): string {
  return String(value ?? '').replace(/\p{C}/gu, (ch) => (ch === '\u200d' ? ch : '')).trim()
}

/**
 * Strip a typed mark down to something safe to render and store: exactly one
 * glyph, or '' meaning "use the pen nib".
 */
export function normalizeMark(value: string | null | undefined): string {
  const cleaned = stripInvisible(value)
  if (!cleaned) return ''
  return withinCap(graphemes(cleaned)[0] ?? '')
}

/**
 * The newest glyph in a field the user is typing into.
 *
 * The mark field holds one glyph, and the emoji keyboard *appends* — so when
 * the text grows, the character the user just picked is the one they meant,
 * not the one already sitting there.
 */
export function latestMark(value: string): string {
  const cleaned = stripInvisible(value)
  if (!cleaned) return ''
  const parts = graphemes(cleaned)
  return withinCap(parts[parts.length - 1] ?? '')
}

/**
 * Accept a cluster whole or not at all, measured the way the server measures.
 *
 * Trimming to the cap would cut a long joined sequence mid-cluster and produce
 * exactly the mojibake the segmenter exists to prevent — and the server counts
 * code points, so a UTF-16 slice here would disagree with it besides.
 */
function withinCap(mark: string): string {
  return [...mark].length <= KLAUS_MARK_MAX ? mark : ''
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
