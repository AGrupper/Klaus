/**
 * KlausMark.tsx — the glyph that stands for Klaus.
 *
 * One component so the Talk to Klaus button and the coach note can never drift
 * apart: both are "Klaus", and a mark chosen in Customize has to change both in
 * the same tap. The pen nib is the default and the fallback — an account that
 * has never opened Customize, or one whose stored mark is blank, gets exactly
 * what shipped before the setting existed.
 *
 * Callers own the tile around the mark, because the two sites need different
 * ones: white-on-accent inside the button, tinted on the card.
 */
import { PenTool } from 'lucide-react'
import { normalizeMark } from '../../tokens'

interface KlausMarkProps {
  /** The stored mark. Empty, null or undefined renders the pen nib. */
  emoji?: string | null
  /** Rendered size in px — the icon's box, or the emoji's font-size. */
  size: number
}

export function KlausMark({ emoji, size }: KlausMarkProps) {
  const mark = normalizeMark(emoji)
  if (!mark) {
    return <PenTool size={size} strokeWidth={1.7} aria-hidden="true" />
  }
  return (
    <span
      aria-hidden="true"
      style={{
        // Emoji sit on their own baseline with generous side bearings; a flex
        // line-box plus a nudged font-size keeps them optically centred in the
        // same tile the icon uses, instead of riding high in it.
        fontSize: `${Math.round(size * 0.95)}px`,
        lineHeight: 1,
        display: 'block',
        // Never let a font stack substitute a text glyph for the emoji.
        fontFamily: '"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif',
      }}
    >
      {mark}
    </span>
  )
}
