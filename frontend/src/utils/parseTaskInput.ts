/**
 * parseTaskInput.ts — Deterministic quick-add parser for Klaus Hub tasks.
 *
 * Parses a raw quick-add string and extracts:
 *   - title: the text remaining after stripping all tokens and the date phrase
 *   - due_date: YYYY-MM-DD string resolved in Asia/Jerusalem, or null
 *   - list_name: extracted from the first #tag token, or null
 *   - priority: one of 'none'|'low'|'medium'|'high', or null
 *
 * Token grammar (D-10):
 *   #list     — first occurrence; e.g. "#work" → list_name="work"
 *   !priority — one of !high|!1|!medium|!2|!low|!3|!none
 *
 * Tokens are stripped BEFORE chrono.parseDate is called — prevents the
 * parser from confusing token text for date phrases (Pitfall 6).
 *
 * Timezone: all date resolution is done in Asia/Jerusalem (UTC+3, DST aware).
 *
 * Security note (T-27-TI): token regex strips to safe charset [a-zA-Z0-9_-];
 * the resulting title is plain text; React default escaping applies on render.
 * dangerouslySetInnerHTML is never used on task content (27-05 enforcement).
 */
import * as chrono from 'chrono-node'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Priority = 'none' | 'low' | 'medium' | 'high' | null

export interface ParsedTask {
  title: string
  due_date: string | null
  list_name: string | null
  priority: Priority
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Maps !token strings to the canonical priority value.
 * Keys are lowercase. !1=high, !2=medium, !3=low per Todoist convention.
 */
export const PRIORITY_MAP: Record<string, Priority> = {
  '!high': 'high',
  '!1': 'high',
  '!medium': 'medium',
  '!2': 'medium',
  '!low': 'low',
  '!3': 'low',
  '!none': 'none',
}

// Regex for #list tokens: # followed by word characters (letters, digits, _, -)
const LIST_TOKEN_RE = /#([a-zA-Z0-9_-]+)/

// Regex for !priority tokens (longest match first to avoid !h matching !high)
const PRIORITY_TOKEN_RE = /!(high|medium|low|none|[123])\b/i

// ---------------------------------------------------------------------------
// Core parser
// ---------------------------------------------------------------------------

/**
 * Parse a raw quick-add string into its constituent parts.
 *
 * @param raw     - The raw input string (e.g. "Buy milk tomorrow #work !high")
 * @param refDate - Reference date for relative NL parsing (defaults to now).
 *                  Must be a real Date; pass a fixed date in tests for determinism.
 * @returns       ParsedTask with title, due_date, list_name, priority
 */
export function parseTaskInput(raw: string, refDate?: Date): ParsedTask {
  // ---- Step 1: extract and strip the #list token ----
  let list_name: string | null = null
  let working = raw.trim()

  const listMatch = LIST_TOKEN_RE.exec(working)
  if (listMatch) {
    list_name = listMatch[1].toLowerCase()
    working = working.replace(listMatch[0], '').trim()
  }

  // ---- Step 2: extract and strip the !priority token ----
  let priority: Priority = null
  const prioMatch = PRIORITY_TOKEN_RE.exec(working)
  if (prioMatch) {
    const token = prioMatch[0].toLowerCase()
    // Look up in PRIORITY_MAP (e.g. "!high" or "!1")
    priority = PRIORITY_MAP[token] ?? null
    working = working.replace(prioMatch[0], '').trim()
  }

  // ---- Step 3: resolve NL date via chrono-node ----
  // refDate is the reference "now" for relative phrases like "tomorrow", "next week".
  // We pass it as the `instant` option to chrono.parse().
  const instant = refDate ?? new Date()

  let due_date: string | null = null
  let title = working.trim()

  const parsed = chrono.parse(working, { instant, timezone: 'Asia/Jerusalem' })

  if (parsed.length > 0) {
    const result = parsed[0]
    const date = result.start.date()

    // Format as YYYY-MM-DD in Asia/Jerusalem local time using en-CA locale
    // which produces "YYYY-MM-DD" format natively.
    due_date = date.toLocaleDateString('en-CA', { timeZone: 'Asia/Jerusalem' })

    // Remove the matched date phrase from the title
    const text = result.text
    title = (working.slice(0, result.index) + working.slice(result.index + text.length))
      .replace(/\s+/g, ' ')
      .trim()
  }

  return {
    title: title || raw.trim(), // fall back to raw if everything was stripped
    due_date,
    list_name,
    priority,
  }
}
