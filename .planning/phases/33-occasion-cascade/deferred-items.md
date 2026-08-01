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
