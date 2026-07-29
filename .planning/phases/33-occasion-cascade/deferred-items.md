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
