# Phase 18: The Autonomous Engine (Capstone) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `18-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-05-20
**Phase:** 18-autonomous-engine
**Areas discussed:** Outreach latitude, Repeat-suppression, Follow-up behavior, Escalation & compose, Judgment eval harness

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Outreach latitude | What should Klaus proactively reach out about; how chatty vs reserved | ✓ |
| Repeat-suppression | Whole-day mute vs cooldown vs per-topic dedup | ✓ |
| Follow-up behavior | How `when` is expressed; whether due follow-ups fire directly or pass triage | ✓ |
| Escalation & compose | What Layer 2 sees; veto; conversation-history injection | ✓ |

**User's choice:** All four (multi-select).

---

## Outreach latitude

### Q1 — Trigger types (multi-select)

| Option | Description | Selected |
|--------|-------------|----------|
| Overdue tasks | TickTick task past due, not done | ✓ |
| Upcoming event prep | Same-day event needing prep | |
| Calendar gaps / overload | Intra-day gap or back-to-back overload | ✓ |
| Long silence | Hours-since-contact crosses threshold | ✓ |

**User's choice:** Overdue tasks, Calendar gaps / overload, Long silence.
**Notes:** Same-day event prep skipped because 21:30 proactive-alerts cron + morning-briefing-tick already cover that ground. Follow-ups treated as non-negotiable (AUTO-05) — not on this list.

### Q2 — Daily cadence cap

| Option | Description | Selected |
|--------|-------------|----------|
| 0–1 per day | Very reserved | |
| 1–3 per day | Recommended; present but not noisy | |
| 3–6 per day | Chatty | |

**User's choice (Other):** *"I don't want to put a limit. if he feels like he wants or needs to talk to me then he should feel free to do so"*
**Notes:** No cadence cap. Mirrors PROJECT.md's "measure, never enforce." Cost discipline lives in Layer 0's gate, not in throttles.

### Q3 — Message shape / voice

| Option | Description | Selected |
|--------|-------------|----------|
| Always actionable | Every message names a thing + offers an action | |
| Action when there is one, observation when there isn't | RECOMMENDED — mixed register | ✓ |
| Pure first-person voice, no suggested actions | Klaus just speaks his mind | |

**User's choice:** Action when there is one, observation when there isn't.

### Q4 — Self-state in triage

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include self-state | Last ~3 journal entries + current_focus + mood in triage prompt | ✓ |
| Only on escalation (Layer 2) | Cheap triage, self-state only in compose | |
| No, situation snapshot only | Triage sees facts only | |

**User's choice:** Yes, include self-state.

### Q5 — `hours_since_contact` floor

| Option | Description | Selected |
|--------|-------------|----------|
| Soft floor at ~6h | Don't surface below 6h | |
| Soft floor at ~12h | Don't surface below 12h | |
| No floor — pure judgment | Pass raw, Klaus decides | ✓ |

**User's choice:** No floor — pure judgment.

---

## Repeat-suppression

### Q1 — Strictness model

| Option | Description | Selected |
|--------|-------------|----------|
| Per-topic dedup | RECOMMENDED — topic_key tagging, informative not blocking | |
| Time-based cooldown | Blanket silence for N hours after any send | |
| Whole-day mute on any send | One proactive per day max | |

**User's choice (Other):** *"Per-topic dedup and also maybe check in at the end of the day if necessary or at a specific time if it's a task with a deadline"*
**Notes:** Per-topic dedup as default, but suppression is **informative** (triage is told what was already raised) not **blocking** — Klaus can re-raise if a deadline is now imminent or for an EOD check-in.

### Q2 — Topic key generation

| Option | Description | Selected |
|--------|-------------|----------|
| Structural keys from source data | Deterministic: `overdue:<task_id>` | |
| Klaus generates the key in triage output | RECOMMENDED — free-form short slug in JSON output | ✓ |
| Hybrid — source prefix + LLM detail | `overdue:reply-to-maya` shape | |

**User's choice:** Klaus generates the key in triage output.

### Q3 — Time context in triage

| Option | Description | Selected |
|--------|-------------|----------|
| Current time + window position | RECOMMENDED — "now: 19:40, tick 39 of ~42, last tick at 20:40" | ✓ |
| Current time only | ISO timestamp only | |
| No explicit time | Leave time out | |

**User's choice:** Current time + window position.

### Locked as Claude's discretion (user said "cover anything you think we should cover")
- Daily reset (outreach_log keyed by date, fresh slate each day; cross-day continuity from journal_digest).
- Triage prompt receives day's outreach as a compact JSON list `[{topic_key, time, draft}]`.
- Log on success only — mirror `proactive_alerts._mark_processed(alert_sent=True)`.
- Layer 0 gate — if `gather_situation()` produces no salient signals, skip the tick-brain call entirely. Mechanism behind SC-3 ("quiet situation → silent + near-zero cost").

---

## Follow-up behavior

### Q1 — `when` argument format

| Option | Description | Selected |
|--------|-------------|----------|
| ISO datetime (machine) | `2026-05-20T18:30:00+03:00` | |
| Natural language, parsed server-side | `tomorrow at 6pm` | |
| Both — ISO preferred, NL accepted | RECOMMENDED | ✓ |

**User's choice:** Both — ISO preferred, NL accepted.

### Q2 — Due follow-up fire path

| Option | Description | Selected |
|--------|-------------|----------|
| Direct fire | Skip tick-brain entirely; send the note (or quick polish) | |
| Through tick-brain | Due follow-ups are an extra signal in `gather_situation` | |
| Hybrid — fire, but Klaus may polish or defer | RECOMMENDED — always-fires Layer-2 compose | ✓ |

**User's choice:** Hybrid — fire, but Klaus may polish or defer.

### Q3 — Deferral mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-push 1h, cap at 3 defers | RECOMMENDED — defer_count protects against infinite punt | ✓ |
| Klaus picks the new time | More flexible; needs strict cap | |
| Single defer to next tick | Skip-then-re-eval; cap at 3 skips | |

**User's choice:** Auto-push 1h, cap at 3 defers.

### Q4 — Management tools

| Option | Description | Selected |
|--------|-------------|----------|
| Schedule only | Just `schedule_followup` per AUTO-05 letter | |
| Schedule + list | Adds `list_followups` | |
| Schedule + list + cancel | RECOMMENDED — full CRUD-ish | ✓ |

**User's choice:** Schedule + list + cancel.
**Notes:** Stretches AUTO-05's letter but matches its intent ("Klaus's check-backs" — he should manage his own).

---

## Escalation & compose

### Q1 — Layer 2 context

| Option | Description | Selected |
|--------|-------------|----------|
| Tick-brain draft + situation snapshot | Lean | |
| Snapshot + draft + journal_digest + self_state | RECOMMENDED | ✓ |
| Full smart_system context | Maximum persona fidelity | |

**User's choice:** Snapshot + draft + journal_digest + self_state.

### Q2 — Second veto

| Option | Description | Selected |
|--------|-------------|----------|
| No second veto | RECOMMENDED — tick-brain is the gate | ✓ |
| Layer 2 may veto with reason | `{send: bool, message: str, reason: str}` | |
| Layer 2 may defer to next tick | Don't add to outreach_log; re-eval next tick | |

**User's choice:** No second veto.

### Q3 — Inject into conversation history

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, inject | RECOMMENDED — `inject_into_conversation=True` | ✓ |
| No, don't inject | Mirror `proactive_alerts` | |
| Inject only on certain triggers | Per-trigger logic | |

**User's choice:** Yes, inject.

### Q4 — Layer 2 failure fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Fall back to tick-brain's draft | RECOMMENDED — mirrors Phase 17 D-13 | ✓ |
| Skip entirely | No send, no log | |
| Send a fixed plain-text fallback | "Heads up — something to check on" | |

**User's choice:** Fall back to tick-brain's draft.

### Q5 — Compose mode

| Option | Description | Selected |
|--------|-------------|----------|
| One-shot generation | Single LLM call; no tool use | |
| Tool-loop (smart_agent style) | Full `_run_smart_loop` with tools | ✓ |
| Limited tools — recall + get_self_status only | Bounded tool path | |

**User's choice:** Tool-loop (smart_agent style).
**Notes:** Layer 2 = synthetic smart_agent turn. Feed `situation_snapshot + draft` as a synthetic user message into `_run_smart_loop` with `prompts/autonomous.md` as the system prompt — SELF.md/self_state/journal_digest inject automatically via the existing per-message render step.

---

## Judgment eval harness (AUTO-08/09)

### Q1 — Fixture source

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-written by you | 20–30 hand-authored fixtures | |
| Captured from live ticks | RECOMMENDED — log every tick, label retroactively | ✓ |
| Synthetic via LLM | LLM generates 25 fixtures | |

**User's choice:** Captured from live ticks.
**Notes:** Ship Phase 18 with ~5 hand-written seed fixtures so the eval runner works on day 1; grow to 20-30 by labeling real captured ticks over a week of use. Implies `tick_logs/{date}/{tick_time}` situation_snapshot logging.

### Q2 — Eval output format

| Option | Description | Selected |
|--------|-------------|----------|
| Single precision/recall/F1 | One number triplet | |
| Overall + per-trigger-type breakdown | RECOMMENDED — small table per trigger type | ✓ |
| Full per-fixture diff report | Maximum visibility | |

**User's choice:** Overall + per-trigger-type breakdown.

---

## Claude's Discretion

Areas where decisions were locked without specific user input (per user's "cover anything you think we should cover" instruction):

- Daily reset of `outreach_log` (keyed by date).
- Triage prompt format for outreach_log presentation (compact JSON list of `{topic_key, time, draft}`).
- Log-on-success-only pattern.
- Layer 0 gate (skip tick-brain when zero salient signals).
- Firestore schema details for `outreach_log/{date}`, `followups`, `tick_logs/{date}/{tick_time}`.
- Eval fixture JSON schema specifics.
- `prompts/autonomous_triage.md` and `prompts/autonomous.md` exact wording.
- Layer 2 model fallback chain (uses established `SMART_AGENT_FALLBACK_*` pattern).
- INFRA-01 / `docs/DEPLOYMENT.md` updates (9 crons + Groq secret + Five Fingers job-id quirk).

## Deferred Ideas

(Captured in CONTEXT.md `<deferred>` section.)

- Per-trigger inject-into-conversation logic — rejected in favor of always-inject (D-18).
- Layer 2 second veto — rejected in favor of single judgment gate (D-17).
- Layer 2 deferral for non-follow-up sends — only follow-ups defer.
- Cancel-via-natural-language — Klaus uses `cancel_followup(id)` programmatically when needed.
- Cost-aware judgment (today's running cost to triage) — Claude's discretion if useful.
- Tick-log retention TTL — Claude's discretion during planning.
- Web/Notion UI for follow-up management — out of scope.
