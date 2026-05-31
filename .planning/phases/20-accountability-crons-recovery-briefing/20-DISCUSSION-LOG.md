# Phase 20: Accountability Crons & Recovery Briefing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 20-accountability-crons-recovery-briefing
**Areas discussed:** Planned-workout detection, Check-in interaction (21:30), Recovery concern, Weekly review, Matching/Dedup, meal_audits gap, Trend windowing, Edge cases (notes capture, sleep rule, time gate, empty review), Minor UX/ops

---

## Planned-workout detection

| Option | Selected |
|--------|----------|
| "Get Ready" block signal | |
| Event-title keyword match | |
| Dedicated workout calendar | ✓ |
| Both Get-Ready + keyword | |

| Five Fingers scope | Selected |
|--------|----------|
| Exclude Five Fingers | |
| Include Five Fingers | ✓ |

| Calendar identification | Selected |
|--------|----------|
| By name lookup | ✓ |
| By explicit calendar ID | |

| Buffers on training cal? | Selected |
|--------|----------|
| Workouts only | |
| Buffers also present | ✓ |

**User's choice:** Dedicated calendar named "Training", located by name lookup. Five Fingers IS tracked. Buffer events titled "Get Ready: \<workout\>" → filtered out; remaining events are workouts. Calendar exists but is empty for now.

---

## Check-in interaction (21:30)

| Persistence | Selected |
|--------|----------|
| Carry to morning briefing | |
| Ask once, then drop | (see note) |
| Re-prompt until answered | |

**User's choice:** Persistence deferred to a future "daily review" skill; Phase 20 asks once. Check-in time → 21:30, **folded into the existing proactive-alerts cron** (deviation from CHECKIN-01/06; reconciled in CONTEXT D-09).

| Notes step resolution | Selected |
|--------|----------|
| Open until you reply | ✓ |
| Pending window then auto-finalize | |

| Multiple sessions/day | Selected |
|--------|----------|
| Key by session | ✓ |
| One per day | |

| Watch-off branch | Selected |
|--------|----------|
| Then ask RPE 1–10 | ✓ |
| Log completed, no RPE | |

---

## Recovery concern

| Tone vs action | Selected |
|--------|----------|
| Tone + light suggestion | |
| Tone only | |
| Tone + concrete prescription | ✓ |

**Note:** Guardrail captured — concrete prescription stays general/qualitative (no fabricated personal numbers) while profile is empty.

| Granularity | Selected |
|--------|----------|
| Single boolean | |
| Severity levels | ✓ |

| Intensity classification | Selected |
|--------|----------|
| By workout type | |
| By event keyword/title | ✓ |
| Defer — any workout = intense | |

| Where surfaced | Selected |
|--------|----------|
| Morning only, evening optional | |
| Both equally | ✓ |
| Morning only, skip evening | |

---

## Weekly review (Sun 10:00)

| Composer | Selected |
|--------|----------|
| Brain (gemini-3.5-flash) | ✓ |
| Tick-brain (qwen3-32b free) | |

| Format | Selected |
|--------|----------|
| Emoji/bullet scorecard | ✓ |
| Monospace code-block table | |

| Depth | Selected |
|--------|----------|
| Tight scorecard + trends + 1 suggestion | |
| Richer narrative | ✓ |

| Suggestion grounding | Selected |
|--------|----------|
| This week's data, JARVIS voice | ✓ |
| Forward-planning toward goals | |

---

## Matching / Dedup / Nutrition source / Trend window

| Planned↔Garmin matching | Selected |
|--------|----------|
| Time-overlap + loose type | ✓ |
| Time-overlap only | |
| Same-day, any activity | |

| Garmin-vs-manual dedup | Selected |
|--------|----------|
| Garmin objective + manual fills gaps | ✓ |
| Manual reply overrides | |
| Keep both separate | |

| meal_audits source | Selected |
|--------|----------|
| Raw MealStore 7-day totals | ✓ |
| Build a MealAuditStore | |
| Drop nutrition from review | |

| Trend window | Selected |
|--------|----------|
| Week-over-week | ✓ |
| 7-day arrows only | |
| 28-day baseline | |

---

## Edge cases

| Notes-reply disambiguation | Selected |
|--------|----------|
| Telegram reply-to the prompt | ✓ (primary) |
| Brain decides from context | ✓ (fallback when no reply-to) |
| Next message within a window | |

| Consecutive-low-sleep rule | Selected |
|--------|----------|
| 2 nights, score <60 | |
| 3 nights, score <60 | |
| 2 nights, score <50 | |

**User's choice:** 2 consecutive nights, sleep score **< 70** (free-text override of the offered options — more sensitive).

| Check-in time gate | Selected |
|--------|----------|
| Only already-passed sessions | ✓ |
| All of today's planned | |

| Empty-log weekly review | Selected |
|--------|----------|
| Silent when truly empty | |
| Always send | ✓ |

---

## Minor UX / ops

| RPE button layout | Selected |
|--------|----------|
| Two rows of 5, labeled in prompt | ✓ |
| Two rows of 5, bare numbers | |
| One row of 10 | |

| 'Skipped' reason capture | Selected |
|--------|----------|
| Quick reason buttons | ✓ |
| Free-text reason | |
| Just log skipped | |

| Bootstrap idempotency | Selected |
|--------|----------|
| Re-runnable (describe-or-create/update) | ✓ |
| Create-only | |

| Weekly-review week boundary | Selected |
|--------|----------|
| Previous Sun–Sat calendar week | ✓ |
| Rolling last 7 days | |

## Claude's Discretion
- Callback/pending-state persistence shape; webhook router callback_query dispatch; `send_and_inject` reply_markup extension; module layout; match-window minutes + type-synonym map; logging style; TDD commit discipline.

## Deferred Ideas
- Recurring "daily review" skill (owns check-in persistence); `MealAuditStore`; personalized thresholds & prescriptions; Apple Watch workout source.
