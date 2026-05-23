---
phase: 18-autonomous-engine
plan: 07
type: execute
wave: 2
depends_on: [06]
files_modified:
  - interfaces/web_server.py
  - core/heartbeat.py
  - tests/test_web_server.py
  - tests/test_heartbeat.py
autonomous: true
requirements: [AUTO-06]
requirements_addressed: [AUTO-06]

must_haves:
  truths:
    - "/cron/autonomous-tick route exists and is OIDC-protected (returns 401 on missing/bad bearer)"
    - "Route invokes core.autonomous.run_autonomous_tick with _application.bot and current Jerusalem datetime"
    - "Route returns 500 when _application is None (not initialised)"
    - "Route calls _log_cron_run('autonomous-tick', ok=True) on success and ok=False on exception"
    - "core/heartbeat.py _CRON_MAX_STALENESS_HOURS has an autonomous-tick entry with value 1 (one hour = 3 missed 20-min ticks)"
  artifacts:
    - path: "interfaces/web_server.py"
      provides: "POST /cron/autonomous-tick async route"
      contains: "cron_autonomous_tick"
    - path: "core/heartbeat.py"
      provides: "Staleness threshold entry for autonomous-tick"
      contains: "autonomous-tick"
    - path: "tests/test_web_server.py"
      provides: "OIDC + invocation + ledger-write tests for /cron/autonomous-tick"
      contains: "test_cron_autonomous_tick"
    - path: "tests/test_heartbeat.py"
      provides: "Staleness-threshold test for autonomous-tick"
      contains: "test_autonomous_tick_staleness"
  key_links:
    - from: "interfaces/web_server.py:cron_autonomous_tick"
      to: "core/autonomous.py:run_autonomous_tick"
      via: "await _auto.run_autonomous_tick(_application.bot, now)"
      pattern: "run_autonomous_tick"
    - from: "core/heartbeat.py _CRON_MAX_STALENESS_HOURS"
      to: "interfaces/web_server.py _log_cron_run job-id"
      via: "job-id string 'autonomous-tick' matches"
      pattern: "autonomous-tick"
---

<objective>
Add the `POST /cron/autonomous-tick` Cloud Run endpoint that Cloud Scheduler
fires every 20 minutes (`*/20 7-21 * * *` Asia/Jerusalem), and register the
job-id in `core/heartbeat.py` so the staleness check picks it up.

Purpose: AUTO-06 requires the route + schedule. The route is a verbatim copy of
`cron_reflect` (Phase 17, most recent + closest in shape) with three changes:
endpoint path, schedule docstring, and call target. The `_application is None`
guard is taken from `cron_proactive_alerts`. The heartbeat staleness entry uses
threshold `1.0` (1 hour = 3 missed 20-min ticks — clear alert signal per
RESEARCH Pitfall 5).

Output: 1 new route block in `interfaces/web_server.py`, 1 line added in
`core/heartbeat.py`, tests for both.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/18-autonomous-engine/18-CONTEXT.md
@.planning/phases/18-autonomous-engine/18-RESEARCH.md
@.planning/phases/18-autonomous-engine/18-PATTERNS.md
@.planning/phases/18-autonomous-engine/18-06-SUMMARY.md
@interfaces/web_server.py
@core/heartbeat.py

<interfaces>
<!-- The cron_reflect template — copy verbatim with replacements. -->

From interfaces/web_server.py:334-355 (cron_reflect — Phase 17, the analog):

```python
@app.post("/cron/reflect")
async def cron_reflect(request: Request) -> JSONResponse:
    """Daily reflection — gather the day, write a journal entry, evolve self_state.

    Schedule: 0 22 * * *  (Asia/Jerusalem)
    Authenticated via OIDC bearer token from Cloud Scheduler.
    """
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.reflection as _reflection
    try:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        loop = _asyncio.get_running_loop()
        await loop.run_in_executor(None, _reflection.run_reflection, today)
        _log_cron_run("reflect", ok=True)
    except Exception:
        _log_cron_run("reflect", ok=False)
        raise
    return JSONResponse(content={"ok": True})
```

From interfaces/web_server.py:321 (proactive_alerts pattern — _application guard):

```python
if _application is None:
    raise HTTPException(status_code=500, detail={"error": "Not initialised"})
```

From core/heartbeat.py:108-114 (_CRON_MAX_STALENESS_HOURS — Phase 17 reflect entry at :113):

```python
_CRON_MAX_STALENESS_HOURS = {
    "morning-briefing": 26,
    "proactive-alerts": 26,
    "ingest-chats": 26,
    "ingest-chat-exports": 26,
    "reflect": 26,                # Phase 17 daily reflect cron
    # ↑ Phase 18: add "autonomous-tick": 1 below this line
}
```

From core/autonomous.py (Plan 06 output):

```python
async def run_autonomous_tick(bot, now: datetime | None = None) -> dict
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add /cron/autonomous-tick route + heartbeat staleness entry + tests</name>
  <files>interfaces/web_server.py, core/heartbeat.py, tests/test_web_server.py, tests/test_heartbeat.py</files>
  <read_first>
    - interfaces/web_server.py (read fully — confirm current line numbers; `_verify_cron_request`, `_log_cron_run`, `cron_reflect`, `cron_proactive_alerts`, the `_application` module-level variable)
    - core/heartbeat.py (read fully — confirm `_CRON_MAX_STALENESS_HOURS` location and current entries; confirm staleness check loop that consumes it)
    - core/autonomous.py (verify Plan 06's `run_autonomous_tick` signature: `async def run_autonomous_tick(bot, now: datetime | None = None) -> dict`)
    - tests/test_web_server.py (read fully — observe FastAPI TestClient pattern + mocking style for cron endpoints + the OIDC bypass via `CRON_DEV_BYPASS=true` env var)
    - tests/test_heartbeat.py (read fully — observe how `_CRON_MAX_STALENESS_HOURS` is tested; current tests reference each existing job-id)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "interfaces/web_server.py (MODIFIED)" lines 459-499; section "core/heartbeat.py (MODIFIED)" lines 503-521)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "interfaces/web_server.py — `/cron/autonomous-tick` route" lines 207-232; Pitfall 5 — staleness threshold rationale)
  </read_first>
  <behavior>
    Tests in `tests/test_web_server.py` (extend existing file with a `TestCronAutonomousTick` class):
    - `test_returns_200_with_dev_bypass_and_app_present`: set `CRON_DEV_BYPASS=true`; mock `_application.bot`; patch `core.autonomous.run_autonomous_tick` to AsyncMock returning `{"sent": False}`; POST to `/cron/autonomous-tick`; assert 200 + `{"ok": True}`; assert `run_autonomous_tick` was awaited once with `_application.bot` as first arg.
    - `test_returns_401_without_bearer`: unset `CRON_DEV_BYPASS`; POST with no auth header; assert 401.
    - `test_returns_500_when_application_is_none`: set `CRON_DEV_BYPASS=true`; patch `_application` to `None`; POST; assert 500.
    - `test_logs_cron_run_ok_true_on_success`: patch `_log_cron_run` to spy; assert called with `("autonomous-tick", ok=True)` after success.
    - `test_logs_cron_run_ok_false_on_exception`: patch `core.autonomous.run_autonomous_tick` to raise; assert `_log_cron_run("autonomous-tick", ok=False)` called AND the exception propagates (HTTP 500 response).

    Tests in `tests/test_heartbeat.py` (extend existing file):
    - `test_autonomous_tick_staleness_threshold_is_one_hour`: `from core.heartbeat import _CRON_MAX_STALENESS_HOURS; assert _CRON_MAX_STALENESS_HOURS["autonomous-tick"] == 1` (int or float, both acceptable).
    - `test_all_cron_jobs_have_staleness_entry`: assert keys include all 9 job-ids: `{"morning-briefing", "proactive-alerts", "ingest-chats", "ingest-chat-exports", "reflect", "autonomous-tick", ...}` — at minimum the new `autonomous-tick` entry is present and is reasonable (<24h).
  </behavior>
  <action>
    Step A — `interfaces/web_server.py`: Append a new route after `cron_reflect` (find line via `grep -n "cron_reflect" interfaces/web_server.py`). Insert the new route block:

    ```python
    @app.post("/cron/autonomous-tick")
    async def cron_autonomous_tick(request: Request) -> JSONResponse:
        """Autonomous tick — judgment-driven proactive outreach.

        Schedule: */20 7-21 * * *  (Asia/Jerusalem)
        Authenticated via OIDC bearer token from Cloud Scheduler.
        Phase 18 — AUTO-06.
        """
        await _verify_cron_request(request)
        if _application is None:
            raise HTTPException(status_code=500, detail={"error": "Not initialised"})
        import core.autonomous as _auto
        try:
            now = datetime.now(ZoneInfo("Asia/Jerusalem"))
            # run_autonomous_tick is async (it internally wraps sync _run_smart_loop in executor).
            await _auto.run_autonomous_tick(_application.bot, now)
            _log_cron_run("autonomous-tick", ok=True)
        except Exception:
            _log_cron_run("autonomous-tick", ok=False)
            raise
        return JSONResponse(content={"ok": True})
    ```

    Verify your edit:
    - `grep -n '@app.post."/cron/autonomous-tick"' interfaces/web_server.py` returns 1 hit.
    - `grep -c '_log_cron_run."autonomous-tick"' interfaces/web_server.py` returns ≥2 (success + failure paths).

    Step B — `core/heartbeat.py`: Find `_CRON_MAX_STALENESS_HOURS` (likely around line 108-114). Add one entry after the `"reflect"` line:

    ```python
        "autonomous-tick": 1,             # Phase 18 — */20 cron; 1h = 3 missed ticks
    ```

    The threshold value `1` (one hour) is calibrated for the 20-minute fire interval — 3 missed ticks is a clear "something's wrong" signal. Comment must include the rationale.

    Verify:
    - `grep -n 'autonomous-tick' core/heartbeat.py` returns ≥1 hit inside `_CRON_MAX_STALENESS_HOURS`.

    Step C — `tests/test_web_server.py`: Append a new test class `TestCronAutonomousTick` with the 5 tests in the behavior block. Use the existing patterns from this file (the tests for `cron_reflect` are the closest analog — find them via `grep -n "cron_reflect" tests/test_web_server.py` to use as scaffolding).

    Step D — `tests/test_heartbeat.py`: Append the 2 tests in the behavior block. The first asserts the new entry; the second is a sanity check over the full dict.

    Step E — Run both files:
    ```bash
    pytest tests/test_web_server.py::TestCronAutonomousTick -x
    pytest tests/test_heartbeat.py -x
    ```

    Full suite sanity:
    ```bash
    pytest tests/test_web_server.py tests/test_heartbeat.py -x
    ```
  </action>
  <verify>
    <automated>grep -c '@app.post."/cron/autonomous-tick"' interfaces/web_server.py && grep -c "autonomous-tick" core/heartbeat.py && pytest tests/test_web_server.py::TestCronAutonomousTick tests/test_heartbeat.py::test_autonomous_tick_staleness_threshold_is_one_hour -x</automated>
  </verify>
  <done>
    - `grep -c '@app.post."/cron/autonomous-tick"' interfaces/web_server.py` >= 1
    - `grep -c 'cron_autonomous_tick' interfaces/web_server.py` >= 1 (function definition + tests reference)
    - `grep -c "_log_cron_run.*autonomous-tick" interfaces/web_server.py` >= 2 (success + failure)
    - `grep -c "autonomous-tick" core/heartbeat.py` >= 1
    - All 5 web_server tests + 2 heartbeat tests pass
    - `python -c "from core.heartbeat import _CRON_MAX_STALENESS_HOURS; assert _CRON_MAX_STALENESS_HOURS.get('autonomous-tick') == 1; print('OK')"` prints OK
  </done>
</task>

</tasks>

<verification>
1. `pytest tests/test_web_server.py tests/test_heartbeat.py -x` — all relevant tests pass
2. Live route smoke (manual, during deploy): `gcloud run services proxy <service> --port 8080` then `curl -X POST -H "Authorization: Bearer ..." http://localhost:8080/cron/autonomous-tick` returns 200 — covered in Plan 09's DEPLOYMENT.md
3. `grep -E "autonomous-tick" interfaces/web_server.py core/heartbeat.py | wc -l` returns ≥4 (route decorator + 2 _log_cron_run calls + heartbeat entry)
</verification>

<success_criteria>
- `/cron/autonomous-tick` route exists, OIDC-protected, calls `run_autonomous_tick(bot, now)`, returns 200/401/500 correctly.
- `_log_cron_run("autonomous-tick", ok=<bool>)` invoked on both success and exception paths.
- `core/heartbeat.py` knows about `autonomous-tick` (threshold 1.0h).
- All tests pass.
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-07-SUMMARY.md` with:
- Line number in `interfaces/web_server.py` where the new route was inserted
- Line number in `core/heartbeat.py` where the staleness entry was added
- Test files extended + test counts
- Note: production deploy needs `gcloud scheduler jobs create http klaus-autonomous-tick` — to be documented in Plan 09 DEPLOYMENT.md
</output>
