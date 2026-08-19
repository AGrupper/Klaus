/**
 * tokens.test.ts — the runtime theme engine behind the Customize sheet.
 */
import { describe, expect, it } from 'vitest'
import {
  applyAppearance,
  defaultAccent,
  FONT_STACKS,
  graphemes,
  KLAUS_MARK_MAX,
  latestMark,
  luminance,
  normalizeHex,
  normalizeMark,
} from './tokens'

describe('normalizeHex', () => {
  it('accepts 6-digit hex with or without #, uppercasing', () => {
    expect(normalizeHex('#1c2540')).toBe('#1C2540')
    expect(normalizeHex('b02a2a')).toBe('#B02A2A')
    expect(normalizeHex('  #B02A2A ')).toBe('#B02A2A')
  })

  it('rejects short, long, and non-hex input', () => {
    expect(normalizeHex('#fff')).toBeNull()
    expect(normalizeHex('1C25401')).toBeNull()
    expect(normalizeHex('zzzzzz')).toBeNull()
    expect(normalizeHex('')).toBeNull()
  })
})

describe('luminance', () => {
  it('is low for dark colors and high for light ones', () => {
    expect(luminance('#000000')).toBe(0)
    expect(luminance('#FFFFFF')).toBeCloseTo(1)
    expect(luminance('#1C2540')).toBeLessThan(0.3)
    expect(luminance('#F2F2F6')).toBeGreaterThan(0.9)
  })
})

describe('applyAppearance', () => {
  const root = () => document.documentElement.style

  it('sets accent, flame, and font vars', () => {
    applyAppearance({ accent: '#20563A', flame: '#C2410C', font: 'serif' })
    expect(root().getPropertyValue('--accent')).toBe('#20563A')
    expect(root().getPropertyValue('--flame')).toBe('#C2410C')
    expect(root().getPropertyValue('--flame-soft')).toContain('#C2410C')
    expect(root().getPropertyValue('--font-display')).toBe(FONT_STACKS.serif.display)
  })

  it('flips button text to ink over a light accent', () => {
    applyAppearance({ accent: '#F5E9C8', flame: '#B02A2A', font: 'default' })
    expect(root().getPropertyValue('--accent-ink')).toBe('#1C1C1E')
    applyAppearance({ accent: '#1C2540', flame: '#B02A2A', font: 'default' })
    expect(root().getPropertyValue('--accent-ink')).toBe('#FFFFFF')
  })

  it('falls back to defaults on invalid hex or font', () => {
    applyAppearance({
      accent: 'not-a-color',
      flame: '#B02A2A',
      font: 'comic' as never,
    })
    expect(root().getPropertyValue('--accent')).toBe(defaultAccent)
    expect(root().getPropertyValue('--font-ui')).toBe(FONT_STACKS.default.ui)
  })
})

describe("Klaus's mark", () => {
  it('keeps a multi-code-point emoji whole', () => {
    // The failure this guards: slicing by code unit turns a family into a man
    // and two orphans, and a flag into two regional-indicator letters.
    expect(normalizeMark('👨‍👩‍👧')).toBe('👨‍👩‍👧')
    expect(normalizeMark('🇮🇱')).toBe('🇮🇱')
    expect(normalizeMark('👍🏽')).toBe('👍🏽')
  })

  it('reduces anything longer to a single glyph', () => {
    expect(normalizeMark('🎩🧠')).toBe('🎩')
    expect(normalizeMark('Klaus')).toBe('K')
    expect(graphemes('🎩🧠⚡')).toHaveLength(3)
  })

  it('has room for the most elaborate real emoji', () => {
    // The couple-with-heart-and-kiss sequence is about as long as Unicode
    // emoji get: two people, two skin tones, a heart and a kiss, joined. If
    // the cap were ever tightened below this, real marks would start vanishing.
    const longest = '👩🏽‍❤️‍💋‍👨🏿'
    expect([...longest].length).toBeLessThanOrEqual(KLAUS_MARK_MAX)
    expect(normalizeMark(longest)).toBe(longest)
  })

  it('rejects an over-long cluster whole rather than slicing it', () => {
    // A base letter buried under combining marks is one cluster and no kind of
    // mark. Cutting it to the cap would emit half a cluster; dropping it falls
    // back to the pen nib, which is a thing the user can actually see.
    const zalgo = 'a' + '\u0301'.repeat(40)
    expect(normalizeMark(zalgo)).toBe('')
  })

  it("treats blank and invisible input as 'use the pen nib'", () => {
    expect(normalizeMark('')).toBe('')
    expect(normalizeMark(null)).toBe('')
    expect(normalizeMark(undefined)).toBe('')
    expect(normalizeMark('  ')).toBe('')
    expect(normalizeMark('\u200e\u200f')).toBe('')  // bidi marks render as nothing
  })

  it('takes the newest glyph while typing, because the keyboard appends', () => {
    expect(latestMark('🎩🧠')).toBe('🧠')
    expect(latestMark('🎩👨‍👩‍👧')).toBe('👨‍👩‍👧')
    expect(latestMark('')).toBe('')
  })
})
