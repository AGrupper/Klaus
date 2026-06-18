/**
 * parseTaskInput.test.ts — Deterministic NL-date + token parser tests.
 *
 * Covers TASK-03 (D-10): client-side deterministic parser for quick-add.
 * - NL date resolution in Asia/Jerusalem via chrono-node 2.9.1
 * - Todoist-style tokens: #list (list_name) and !priority (priority level)
 * - Token stripping before chrono parse to avoid date confusion
 * - Near-midnight timezone edge case: "tomorrow" must resolve in Asia/Jerusalem
 *
 * All tests use a fixed refDate so date assertions are deterministic.
 * Implemented in plan 27-04.
 */

import { describe, it, expect } from 'vitest'
import { parseTaskInput } from './parseTaskInput'

// ---------------------------------------------------------------------------
// Fixed reference date: Thursday 2026-06-18 at 10:00 Israel time (UTC+3)
// ---------------------------------------------------------------------------
const REF_DATE = new Date('2026-06-18T10:00:00+03:00')

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

describe('parseTaskInput — NL-date + token parser', () => {

  // Case 1: Simple NL date — "tomorrow"
  it('parses "Buy milk tomorrow" → due_date is tomorrow in Asia/Jerusalem', () => {
    const result = parseTaskInput('Buy milk tomorrow', REF_DATE)
    expect(result.title).toBe('Buy milk')
    expect(result.due_date).toBe('2026-06-19')
    expect(result.list_name).toBeNull()
    expect(result.priority).toBeNull()
  })

  // Case 2: List token + priority token + NL date
  // refDate = Wednesday 2026-06-17 → next Friday = 2026-06-19
  it('parses "meeting #work !high friday" → list_name=work, priority=high, due_date=friday', () => {
    const refDate = new Date('2026-06-17T10:00:00+03:00') // Wednesday
    const result = parseTaskInput('meeting #work !high friday', refDate)
    expect(result.title.toLowerCase()).toContain('meeting')
    expect(result.list_name).toBe('work')
    expect(result.priority).toBe('high')
    expect(result.due_date).toBe('2026-06-19')
  })

  // Case 3: No date — pure task with list token
  it('parses "Buy groceries #personal" → no due_date, list_name=personal', () => {
    const result = parseTaskInput('Buy groceries #personal')
    expect(result.title).toContain('groceries')
    expect(result.list_name).toBe('personal')
    expect(result.due_date).toBeNull()
  })

  // Case 4: Priority token variations — !medium maps to 'medium'
  it('parses "!medium call dentist" → priority=medium, title has call dentist', () => {
    const result = parseTaskInput('!medium call dentist')
    expect(result.priority).toBe('medium')
    expect(result.title.toLowerCase()).toContain('dentist')
  })

  // Case 5: Priority token variation !low
  it('parses "!low water plants" → priority=low', () => {
    const result = parseTaskInput('!low water plants')
    expect(result.priority).toBe('low')
  })

  // Case 6: "next week" relative date
  it('parses "Report next week" → due_date is a future date', () => {
    const result = parseTaskInput('Report next week', REF_DATE)
    expect(result.due_date).toBeTruthy()
    // Must be a future date (>= 2026-06-19 from Thursday 2026-06-18)
    expect(result.due_date! >= '2026-06-19').toBe(true)
  })

  // Case 7: Near-midnight timezone edge case (Pitfall 6)
  // At 23:30 Israel time (UTC+3), "tomorrow" must resolve to the NEXT Israel day.
  // In UTC it would be 2026-06-18T20:30:00Z — but Israel-local date is still June 18,
  // so "tomorrow" must yield 2026-06-19, not 2026-06-20.
  it('near-midnight Asia/Jerusalem: "tomorrow" resolves to next calendar day in Israel', () => {
    // 2026-06-18 at 23:30 Israel time = 2026-06-18T20:30:00Z
    const nearMidnightRef = new Date('2026-06-18T20:30:00Z')
    const result = parseTaskInput('Reminder tomorrow', nearMidnightRef)
    // In Israel it is still June 18 at 23:30 → "tomorrow" = June 19
    expect(result.due_date).toBe('2026-06-19')
  })

  // Case 8: Title cleaned of date phrase after parsing
  it('date phrase is removed from title after extraction', () => {
    const result = parseTaskInput('Submit report tomorrow', REF_DATE)
    // "tomorrow" should not appear in the resulting title
    expect(result.title.toLowerCase()).not.toContain('tomorrow')
    expect(result.title.toLowerCase()).toContain('report')
    expect(result.due_date).toBe('2026-06-19')
  })

  // Case 9: Numeric date — "June 25"
  it('parses "gym June 25" → due_date=2026-06-25', () => {
    const result = parseTaskInput('gym June 25', REF_DATE)
    expect(result.due_date).toBe('2026-06-25')
    expect(result.title.toLowerCase()).toContain('gym')
  })

  // Case 10: All tokens combined
  it('parses full input with all tokens: title, list, priority, NL date', () => {
    // Next Monday from Thursday Jun 18 = Jun 22
    const result = parseTaskInput('Doctor appointment #health !high next monday', REF_DATE)
    expect(result.title.toLowerCase()).toContain('doctor')
    expect(result.list_name).toBe('health')
    expect(result.priority).toBe('high')
    expect(result.due_date).toBeTruthy()
    expect(result.due_date).toBe('2026-06-22')
  })

  // Case 11: Numeric priority shortcuts (!1 = high, !2 = medium, !3 = low)
  it('parses !1 as high priority and !2 as medium and !3 as low', () => {
    expect(parseTaskInput('!1 fix bug').priority).toBe('high')
    expect(parseTaskInput('!2 write docs').priority).toBe('medium')
    expect(parseTaskInput('!3 water plants').priority).toBe('low')
  })

  // Case 12: Plain task with no tokens or date → all nulls
  it('returns all nulls for a plain task with no tokens', () => {
    const result = parseTaskInput('plain task')
    expect(result.title).toBe('plain task')
    expect(result.due_date).toBeNull()
    expect(result.list_name).toBeNull()
    expect(result.priority).toBeNull()
  })
})
