# Phase 17: Reflection & Journal - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-19
**Phase:** 17-reflection-journal
**Areas discussed:** Day data gathering, Journal entry schema, Prompt digest injection, Idempotency & overwrite, Self-recall, Cron timing, Reflection tone, Pinecone self-memory, get_self_status journal field, LLM failure handling, recent_context strategy, Reflection continuity, Digest slot

---

## Day Data Gathering

| Option | Description | Selected |
|--------|-------------|----------|
| Message count + cost only | LLMUsageStore.summary("today") only — fast, cheap, no privacy concern | |
| Message count + cost + summary paragraph | Worker summarizes today's conversation; LLM then reflects on the summary | ✓ |
| Last N messages as transcript snippet | Fetch raw conversation tail — richer but heavier | |

**User's choice:** Message count + cost + summary paragraph

**Additional sources selected (all four):**
- LLM cost (today) — `LLMUsageStore.summary("today")`
- Calendar events (today) — via existing calendar tool
- TickTick tasks completed today
- Heartbeat last-run status

---

## Journal Entry Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Structured fields | LLM outputs JSON with fixed fields; maps directly to self_state | ✓ |
| Free-form prose + extracted fields | Prose + second-pass field extraction — two LLM calls | |
| Prose only | Single text blob; no structured self_state update | |

**User's choice:** Structured fields

**Fields selected:** summary + mood + current_focus + recent_context + highlights[]
(user chose this over the minimal 4-field set — richer recall surface area)

**Model assignment:** Summary pass = worker (gemini-2.5-flash); Reflection pass = brain (gemini-3-flash-preview)

---

## Prompt Digest Injection

| Option | Description | Selected |
|--------|-------------|----------|
| Bullet digest block | Compact dated bullets after {self_state}, smart-only | ✓ |
| Inline paragraph | Prose weaving last 3 days together | |
| Full structured dump | All fields for each of the last 3 days | |

**User's choice:** Bullet digest block

**Digest content per entry:** summary + mood + top highlight (if highlights non-empty)

**Placeholder slot:** After {self_state}, before {today_date}. Smart-only (worker excluded).

---

## Idempotency & Overwrite

| Option | Description | Selected |
|--------|-------------|----------|
| Overwrite the day's entry | Second run regenerates and overwrites | ✓ |
| Skip if entry already exists | Return early if journal/{date} exists | |
| Skip by default, ?force=true to overwrite | Flexible but more code paths | |

**User's choice:** Overwrite

**Gather failure behavior:** Best-effort — each source wrapped in try/except; failed sources omitted, reflection still runs.

**Core LLM failure behavior:** Write minimal fallback doc (raw metrics + "reflection unavailable" placeholder). Journal stays gap-free.

---

## Self-Recall (kind="self")

| Option | Description | Selected |
|--------|-------------|----------|
| Extend recall tool with optional kind param | One tool, no new registration sites | ✓ (Claude's call) |
| New dedicated recall_journal tool | Clearer intent but 6th direct tool + 5-site registration | |

**User's choice:** Deferred to Claude. Claude chose: extend existing `recall` tool — lower surface area, journal recall is semantically the same vector search. `recall()` already accepts `kinds` param.

---

## Cron Timing

| Option | Description | Selected |
|--------|-------------|----------|
| 22:00 Asia/Jerusalem daily | After 21:30 proactive-alerts — day effectively closed | ✓ |
| 23:30 Asia/Jerusalem daily | Captures more evening activity | |
| 00:30 Asia/Jerusalem (next day) | Cleanest boundary but targets "yesterday" | |

**User's choice:** 22:00 Asia/Jerusalem daily

**Cloud Scheduler job:** Route + documented gcloud command in plan/DEPLOYMENT.md — consistent with other 7 crons.

---

## Reflection Tone

| Option | Description | Selected |
|--------|-------------|----------|
| First person, as Klaus | "Today I helped Amit..." — journal reads as Klaus's diary | ✓ |
| Third person, observational | "Klaus assisted with..." — more like a system log | |

**User's choice:** First person, as Klaus

---

## Pinecone Self-Memory

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic ID 'self-{date}', embed summary+highlights | Overwrite-safe; richer embedding | ✓ |
| Deterministic ID 'self-{date}', embed summary only | Lighter but less recall surface | |
| Random UUID via remember() | Appends duplicate on re-run — conflicts with overwrite | |

**User's choice:** Deterministic ID `self-{date}`, embed summary+highlights

---

## Journal Doc Storage

| Option | Description | Selected |
|--------|-------------|----------|
| LLM output + raw day-data metrics | All 5 fields + message_count, cost_usd, etc. — auditable | ✓ |
| LLM output only | Lean doc; input metrics discarded | |

**User's choice:** LLM output + raw day-data metrics

---

## get_self_status Journal Field

| Option | Description | Selected |
|--------|-------------|----------|
| Last entry: date + summary + mood | {date, summary, mood} from most recent JournalStore entry | ✓ |
| Last reflection date only | {last_reflection_date} — minimal | |
| Last 3 entries | [{date, summary}...] — same as digest | |

**User's choice:** Last entry: date + summary + mood

---

## Core LLM Failure Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Fail the cron, write nothing | Clean gap; _log_cron_run records ok=False | |
| Write minimal fallback entry | Raw metrics + "reflection unavailable" placeholder | ✓ |

**User's choice:** Write minimal fallback entry (journal stays gap-free)

---

## recent_context Update Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Replace each reflection | Always fresh, short | |
| Rolling 3-day window | Accumulate last 3 days — deliberate redundancy with digest | ✓ |

**User's choice:** Rolling 3-day window

---

## Reflection Continuity

| Option | Description | Selected |
|--------|-------------|----------|
| Include yesterday's entry | journal/{yesterday} summary+current_focus passed in prompt | ✓ |
| Each reflection is independent | Simpler; no cross-day references | |

**User's choice:** Include yesterday's entry (best-effort — absent on first run)

---

## Digest Placeholder Slot

| Option | Description | Selected |
|--------|-------------|----------|
| After {self_state}, smart-only | SELF.md → self_state → journal_digest → today_date | ✓ |
| Before {self_state}, smart-only | Different volatile-content ordering | |

**User's choice:** After {self_state}, smart-only

---

## Claude's Discretion

- Digest empty state: omit block when no entries exist (consistent with Phase 16 D-05)
- highlights[] cap: suggest 3-5 items
- Exact reflection.md prompt wording
- JSON-parse hardening for brain output
- Embedded-text truncation if summary+highlights exceeds CONTENT_MAX_CHARS
- user_id sourcing for run_reflection() (reuse proactive-alerts cron pattern)

## Deferred Ideas

None — discussion stayed within phase scope.
