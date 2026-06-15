/**
 * Sanity test for tokens.ts — verifies the locked palette values from UI-SPEC.
 *
 * If these assertions fail, the UI-SPEC was violated. Change the tokens.ts
 * values ONLY if the UI-SPEC is revised.
 */
import { describe, it, expect } from 'vitest'
import {
  accent,
  dominant,
  secondary,
  destructive,
  textPrimary,
  textSecondary,
  border,
  success,
  offline,
  skeleton,
  fontWeightRegular,
  fontWeightSemibold,
  typography,
} from './tokens'

describe('tokens', () => {
  it('accent is #6366F1 (indigo-500 per UI-SPEC)', () => {
    expect(accent).toBe('#6366F1')
  })

  it('dominant background is #0A0A0A', () => {
    expect(dominant).toBe('#0A0A0A')
  })

  it('secondary surface is #1A1A1A', () => {
    expect(secondary).toBe('#1A1A1A')
  })

  it('destructive is #EF4444 (red-500)', () => {
    expect(destructive).toBe('#EF4444')
  })

  it('textPrimary is #F9FAFB', () => {
    expect(textPrimary).toBe('#F9FAFB')
  })

  it('textSecondary is #9CA3AF', () => {
    expect(textSecondary).toBe('#9CA3AF')
  })

  it('border is #2A2A2A', () => {
    expect(border).toBe('#2A2A2A')
  })

  it('success is #22C55E (green-500)', () => {
    expect(success).toBe('#22C55E')
  })

  it('offline is #F59E0B (amber-500)', () => {
    expect(offline).toBe('#F59E0B')
  })

  it('skeleton shimmer is #1F1F1F', () => {
    expect(skeleton).toBe('#1F1F1F')
  })

  it('exactly 2 font weights: 400 and 600 (no 500)', () => {
    expect(fontWeightRegular).toBe(400)
    expect(fontWeightSemibold).toBe(600)
  })

  it('typography scale has the 4 required roles', () => {
    expect(typography.body.fontSize).toBe('16px')
    expect(typography.label.fontSize).toBe('13px')
    expect(typography.heading.fontSize).toBe('20px')
    expect(typography.display.fontSize).toBe('28px')
  })

  it('heading and display use semibold weight', () => {
    expect(typography.heading.fontWeight).toBe(600)
    expect(typography.display.fontWeight).toBe(600)
  })

  it('body and label use regular weight', () => {
    expect(typography.body.fontWeight).toBe(400)
    expect(typography.label.fontWeight).toBe(400)
  })
})
