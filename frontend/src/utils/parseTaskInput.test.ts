/**
 * parseTaskInput.test.ts — Wave 0 stub for the NL-date + token parser.
 *
 * Covers TASK-03 (D-10): client-side deterministic parser for quick-add.
 * - NL date resolution in Asia/Jerusalem via chrono-node 2.9.1
 * - Todoist-style tokens: #list (list_name) and !priority (priority level)
 * - Token stripping before chrono parse to avoid date confusion
 * - Near-midnight timezone edge case: "tomorrow" must resolve in Asia/Jerusalem
 *
 * All tests are skip-marked (it.skip) — implemented in plan 27-04.
 * The file exists now so downstream plans have an automated Vitest target.
 *
 * Implementation note: parseTaskInput is a pure function exported from
 * frontend/src/utils/parseTaskInput.ts with the signature:
 *   parseTaskInput(raw: string, refDate?: Date): ParsedTask
 * where ParsedTask = { title: string, due_date: string|null, list_name: string|null, priority: string|null }
 */

import { describe, it, expect } from 'vitest'

// The module under test — will not exist until 27-04.
// Import is wrapped in a lazy import inside each test to prevent
// module-resolution errors from failing the whole suite.

// ---------------------------------------------------------------------------
// Wave 0: skip-marked test cases (≥8 as required by 27-VALIDATION.md)
// ---------------------------------------------------------------------------

describe('parseTaskInput — Wave 0 stubs (implemented in 27-04)', () => {
  // Case 1: Simple NL date — "tomorrow"
  it.skip('parses "Buy milk tomorrow" → due_date is tomorrow in Asia/Jerusalem', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const refDate = new Date('2026-06-18T10:00:00+03:00')
    const result = parseTaskInput('Buy milk tomorrow', refDate)
    expect(result.title).toBe('Buy milk')
    expect(result.due_date).toBe('2026-06-19')
    expect(result.list_name).toBeNull()
    expect(result.priority).toBeNull()
  })

  // Case 2: List token + priority token + NL date
  it.skip('parses "meeting #work !high friday" → list_name=work, priority=high, due_date=friday', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    // refDate = Wednesday 2026-06-17 → next Friday = 2026-06-19
    const refDate = new Date('2026-06-17T10:00:00+03:00')
    const result = parseTaskInput('meeting #work !high friday', refDate)
    expect(result.title.toLowerCase()).toContain('meeting')
    expect(result.list_name).toBe('work')
    expect(result.priority).toBe('high')
    expect(result.due_date).toBe('2026-06-19')
  })

  // Case 3: No date — pure task with list token
  it.skip('parses "Buy groceries #personal" → no due_date, list_name=personal', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const result = parseTaskInput('Buy groceries #personal')
    expect(result.title).toContain('groceries')
    expect(result.list_name).toBe('personal')
    expect(result.due_date).toBeNull()
  })

  // Case 4: Priority token variations — !medium maps to 'medium'
  it.skip('parses "!medium call dentist" → priority=medium, title has call dentist', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const result = parseTaskInput('!medium call dentist')
    expect(result.priority).toBe('medium')
    expect(result.title.toLowerCase()).toContain('dentist')
  })

  // Case 5: Priority token variation !low
  it.skip('parses "!low water plants" → priority=low', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const result = parseTaskInput('!low water plants')
    expect(result.priority).toBe('low')
  })

  // Case 6: "next week" relative date
  it.skip('parses "Report next week" → due_date is next Monday or week-start', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const refDate = new Date('2026-06-18T10:00:00+03:00') // Thursday
    const result = parseTaskInput('Report next week', refDate)
    expect(result.due_date).toBeTruthy()
    // Must be a future date (>= 2026-06-19)
    expect(result.due_date! >= '2026-06-19').toBe(true)
  })

  // Case 7: Near-midnight timezone edge case
  // At 23:30 Israel time (UTC+3), "tomorrow" must resolve to the NEXT Israel day,
  // NOT the same day (which would happen if the parser used UTC "today")
  it.skip('near-midnight Asia/Jerusalem: "tomorrow" resolves to next calendar day', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    // 2026-06-18 at 23:30 Israel time (UTC+3) = 2026-06-18T20:30:00Z
    const refDate = new Date('2026-06-18T20:30:00Z')
    const result = parseTaskInput('Reminder tomorrow', refDate)
    // In Israel it is still June 18 at 23:30 → "tomorrow" = June 19
    expect(result.due_date).toBe('2026-06-19')
  })

  // Case 8: Title cleaned of date phrase after parsing
  it.skip('date phrase is removed from title after extraction', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const refDate = new Date('2026-06-18T10:00:00+03:00')
    const result = parseTaskInput('Submit report tomorrow', refDate)
    // "tomorrow" should not appear in the resulting title
    expect(result.title.toLowerCase()).not.toContain('tomorrow')
    expect(result.title.toLowerCase()).toContain('report')
    expect(result.due_date).toBe('2026-06-19')
  })

  // Case 9: Numeric date — "June 25"
  it.skip('parses "gym June 25" → due_date=2026-06-25', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const refDate = new Date('2026-06-18T10:00:00+03:00')
    const result = parseTaskInput('gym June 25', refDate)
    expect(result.due_date).toBe('2026-06-25')
    expect(result.title.toLowerCase()).toContain('gym')
  })

  // Case 10: All tokens combined
  it.skip('parses full input with all tokens: title, list, priority, NL date', async () => {
    const { parseTaskInput } = await import('./parseTaskInput')
    const refDate = new Date('2026-06-18T10:00:00+03:00')
    const result = parseTaskInput('Doctor appointment #health !high next monday', refDate)
    expect(result.title.toLowerCase()).toContain('doctor')
    expect(result.list_name).toBe('health')
    expect(result.priority).toBe('high')
    expect(result.due_date).toBeTruthy()
    // Next Monday from Thursday Jun 18 = Jun 22
    expect(result.due_date).toBe('2026-06-22')
  })
})
