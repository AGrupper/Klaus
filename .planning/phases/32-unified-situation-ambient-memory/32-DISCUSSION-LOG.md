# Phase 32: Unified Situation (Ambient Memory) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-22
**Phase:** 32-Unified Situation (Ambient Memory)
**Areas discussed:** training_reality reconciliation, Recall/forget/continuity, Location derivation, Groq ledger + cap behavior

---

## training_reality reconciliation (MEM-04)

### Source-of-truth precedence

| Option | Description | Selected |
|--------|-------------|----------|
| Evidence wins | Garmin/Hevy actual data is ground truth for "did it happen"; training_log second; calendar/planned = intent | ✓ |
| Self-report wins | training_log authoritative when present; Garmin/Hevy fills gaps | |
| Show all, don't rank | Surface all 4 side-by-side, judge per-case, no fixed precedence | |

**User's choice:** Evidence wins
**Notes:** Matches how Amit actually trains — sensors capture reality even when he doesn't self-log.

### Slot-matching tolerance

| Option | Description | Selected |
|--------|-------------|----------|
| Same-day + type | Right modality on the planned day satisfies the slot; don't demand pace/distance match | ✓ |
| Same-day, any modality | Any logged activity that day counts as trained | |
| Type + rough target | Must be right modality AND roughly hit the prescription | |

**User's choice:** Same-day + type
**Notes:** A completed-but-imperfect session is "done" and never re-asked; quality coaching is separate.

---

## Recall, forget & continuity (MEM-01/02/03)

### Auto-recall vs manual recall tool

| Option | Description | Selected |
|--------|-------------|----------|
| Both, keep manual | Auto-block for ambient background; manual `recall` for deep targeted lookups | ✓ |
| Auto-only, retire manual | Auto-block replaces the manual tool entirely | |
| Auto, manual as fallback | Auto primary; manual demoted to "only if auto missed something" | |

**User's choice:** Both, keep manual

### Contradicted-memory handling (forget_memory is deliberate-only)

| Option | Description | Selected |
|--------|-------------|----------|
| Flag in nightly, you decide | Reflection surfaces contradiction in nightly; delete only on Amit's confirmation | ✓ |
| Klaus self-forgets, announces | Reflection deletes clearly-superseded facts and reports it | |
| Flag silently, no delete | Mark stale so recall de-weights; never delete, never in nightly | |

**User's choice:** Flag in nightly, you decide
**Notes:** Honors "deliberate-only, no auto-decay" — the flag is a suggestion, Amit pulls the trigger.

### Continuity framing (MEM-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Labeled recap block | Tail as a marked context block, separate from live history | |
| Rehydrate as history | Prepend actual prior messages for continuous conversation | (basis of final) |

**User's choice:** "Whatever you think is better regardless of the amount of work it takes."
**Notes:** Claude's call → rehydrate the tail as real history PLUS a time-gap boundary marker
("~8h elapsed; new session begins here") so continuity feels natural while the brain won't re-act
on stale messages. Best-of-both; not the cheap labeled-block shortcut.

---

## Location derivation (MEM-07)

| Option | Description | Selected |
|--------|-------------|----------|
| Default Tel Aviv silently | Assume home unless a signal positively places Amit elsewhere | (partial) |
| Default home, note if stale | Keep derived location across multi-day trip windows | |
| Ask when ambiguous | On conflicting/unclear trip windows, ask before serving weather/travel | ✓ |

**User's choice:** Ask when ambiguous
**Notes:** Correct-over-quiet for conflict cases (Paris-getting-TLV is a felt bug); common home case
stays silent. Reuses Phase 31's "still in France, Sir?" nightly-ask pattern.

---

## Groq ledger + cap behavior (MEM-06)

### Warning threshold

| Option | Description | Selected |
|--------|-------------|----------|
| 80% (160K) | Warn crossing ~80% of the 200K cap — runway to react | ✓ |
| 90% (180K) | Warn only when genuinely close | |
| Two-stage | Soft note at 80%, louder at ~95% | |

**User's choice:** 80% (160K)

### At-cap behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Fall to Gemini tick-brain | Route tick reasoning to TICK_BRAIN_FALLBACK for the day | ✓ |
| Stop ticking until reset | Suppress autonomous ticks entirely | |
| Skip triage, gather only | Keep gathering, skip LLM triage (reads no-speak) | |

**User's choice:** Fall to Gemini tick-brain
**Notes:** Preserves function; ledger + 80% warning make the small cost visible. Reuses existing fallback path.

---

## Claude's Discretion

- Auto-recall score threshold + recency-weighting formula (k≈5 locked in REQUIREMENTS).
- Rendering/labels of the "Things you remember" and `training_reality` blocks per prompt (chat/triage/paid).
- Continuity boundary-marker wording.
- Token-ledger schema, reset mechanism, heartbeat alert phrasing.
- How location derivation reads calendar travel events + composes with directive location text.
- New-block placement in `smart_agent.md` (after the cached prefix — 30.5 caching landmine).

## Deferred Ideas

- Occasion cascade routing for nightly/morning/weekly — Phase 33.
- Write-backs to the training source of truth (calendar/chat → planned rows) — Phase 34.
- Hub surface for browsing/forgetting memories — out of scope.
