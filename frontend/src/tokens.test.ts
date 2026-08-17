/**
 * tokens.test.ts — the runtime theme engine behind the Customize sheet.
 */
import { describe, expect, it } from 'vitest'
import {
  applyAppearance,
  defaultAccent,
  FONT_STACKS,
  luminance,
  normalizeHex,
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
