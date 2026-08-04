# Phase 33 — Deferred Items

Out-of-scope discoveries logged during execution, per the executor's SCOPE
BOUNDARY rule (not fixed — flagged for a future plan/cleanup pass).

## core/tools.py — orphaned dead code near line ~2033 (found during plan 33-09)

Between `_handle_forget_memory` and `_handle_run_morning_briefing` there is a
stray, unreachable `return json.dumps({"date": date, "logged": logged,
"warnings": warnings})` statement, indented to the same level as
`_handle_forget_memory`'s body. It is syntactically valid (Python treats
blank lines as non-terminating, so the dedented `return` is technically
still inside `_handle_forget_memory`'s block) but it is dead code —
`_handle_forget_memory` already returns on the line above, so this line can
never execute. It references `date`/`logged`/`warnings` names that do not
exist in that function's scope either.

Pre-existing, unrelated to plan 33-09's `get_recent_decisions` change
(which was inserted lower in the file, before `_handle_notion_search`).
Not fixed here — out of scope per the SCOPE BOUNDARY rule (only auto-fix
issues directly caused by the current task's changes). Flag for a future
cleanup plan.

## Tick-brain `skip_cause` arriving empty on every observed cascade run (found during plan 33-12/33-13)

Both production cascade runs observed during the 33-12 operator checkpoint
(2026-07-31 and 2026-08-01) logged `morning_briefing: skipped_by_judgment
for <date> (focus, cause=)` — `verdict.get("skip_cause", "")` is not being
populated by the tick-brain layer on a skip verdict. Non-breaking:
`check_occasion_health`'s anomaly #1/#2 key off `composed_via`/`status`
presence, not `skip_cause` content, so no false alert results. But it
degrades the audit trail the D-29/D-30 observation window (plan 33-13 Task 3)
depends on — Amit reading "why didn't Klaus speak today" loses the one-line
reason. Not fixed here — plan 33-13 explicitly scopes this as a "record,
don't fix" item (prior_wave_context) and it isn't in any task's `<action>`.
Candidate for Phase 35 (or a `prompts/autonomous_triage.md` prompt-tuning
pass): the tick-brain triage prompt likely isn't emitting the `skip_cause`
field the compose layer expects, or the parse site is reading the wrong key.

## D-11 `garmin_missing` never fires on a null-sleep Garmin record (found 2026-08-04, live)

**Deferred by Amit's explicit decision (2026-08-04): he does not want sleep
analysis in the morning briefing — he uses a separate app for that. Recorded for
the post-milestone overhaul, NOT to be fixed during v6.0.**

`core/morning_briefing.py:236` sets the D-11 gap flag only on one status code:

```python
if (today_data.get("garmin") or {}).get("state") == 2:
    today_data["garmin_missing"] = True
```

On 2026-08-04 the morning gather returned `state: 1` with EVERY sleep field null
(`sleep_score`, `sleep_hours`, `body_battery_morning`, `resting_hr`,
`training_readiness`, `hrv_overnight` — only `hrv_status: "BALANCED"` and
`hrv_baseline: 103` were set). That is genuinely "no sleep data", but it is not
`state == 2`, so `garmin_missing` was never added to the payload — confirmed
absent from the persisted `tick_logs/2026-08-04/ticks/occasion:morning`
`situation_snapshot`.

Consequence: nothing signalled the gap, so Layer 2 papered over it with a
pleasantry ("Morning — hope you slept well. What's on for today?") instead of
naming it. This is precisely the outcome D-11 exists to prevent. It also defeats
plan 33-CR-01's Layer-1 occasion digest, which forwards `garmin_missing` but can
only forward what was set — **the fix belongs upstream of the digest.**

Fix direction: derive the gap from the data rather than a single status code —
e.g. treat sleep as missing when `sleep_score` and `sleep_hours` are both `None`,
independent of `state`. Keep `state == 2` as one input, not the only one.

**Related, likely upstream and worth checking first:** `biometric_ingest` holds
only a `state` document — no dated docs at all. If the 05:30 `klaus-biometric-sync`
cron is not landing daily records, sleep may be absent most mornings rather than
just this one. Diagnose the sync before tuning the flag.
