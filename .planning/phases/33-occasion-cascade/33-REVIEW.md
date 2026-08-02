---
phase: 33-occasion-cascade
reviewed: 2026-08-01T00:00:00Z
depth: standard
files_reviewed: 34
files_reviewed_list:
  - .github/workflows/deploy.yml
  - core/autonomous.py
  - core/heartbeat.py
  - core/main.py
  - core/morning_briefing.py
  - core/nightly_review.py
  - core/self_manifest.py
  - core/task_dispatch.py
  - core/tools.py
  - core/weekly_training_review.py
  - docs/DEPLOYMENT.md
  - docs/SELF.md
  - docs/sleep_focus_off_shortcut.md
  - interfaces/web_server.py
  - memory/firestore_db.py
  - prompts/autonomous.md
  - prompts/autonomous_triage.md
  - prompts/morning_occasion.md
  - prompts/nightly_occasion.md
  - prompts/occasion_triage_addendum.md
  - prompts/weekly_occasion.md
  - tests/occasion_helpers.py
  - tests/test_autonomous.py
  - tests/test_docs.py
  - tests/test_firestore_db.py
  - tests/test_heartbeat.py
  - tests/test_main.py
  - tests/test_morning_briefing.py
  - tests/test_nightly_review.py
  - tests/test_prompts.py
  - tests/test_task_dispatch.py
  - tests/test_token_budget.py
  - tests/test_tools.py
  - tests/test_web_server.py
  - tests/test_weekly_training_review.py
findings:
  critical: 5
  warning: 12
  info: 0
  total: 17
status: issues_found
---

# Phase 33: Code Review Report

**Reviewed:** 2026-08-01
**Depth:** standard
**Files Reviewed:** 34 (diff base `367e815..HEAD`, phase-33 source changes only)
**Status:** issues_found

## Summary

Phase 33 generalised the autonomous-tick cascade into a shared occasion pipeline
(`_run_cascade` / `run_occasion_cascade`) and repointed nightly, morning and weekly
onto it. The auth work on the new surfaces is genuinely solid — `_verify_morning_trigger_request`
is a faithful constant-time, refuse-all-on-unset mirror of the healthkit verifier with a
distinct secret (D-13), and `/internal/process-occasion` sits behind the same OIDC + SA-email
check as every other cron route. The Cloud Tasks repoint correctly removes the
BackgroundTask CPU-throttling violation from `/trigger/nightly`. The Groq token-budget
guard was extended to the occasion path (`test_maximal_occasion_triage_prompt_fits_groq_ceiling`)
before the addendum shipped, which is the right order of operations.

The damage is concentrated exactly where the phase context predicted: the seams between
independently-written plans. The single largest defect is that **every occasion's specialised
Layer-0 gather is merged into `situation` and then never rendered into either prompt** — both
prompt builders read a fixed key whitelist inherited from the tick. Under
`OCCASION_CASCADE=true` (live right now) the nightly composes without the journal that D-07
exists to guarantee, the morning composes without sleep/tasks/weather, and the weekly composes
without the week. Nine parallel agents each merged their data into the shared dict and each
assumed a different agent had wired the render; nobody did, and every test passes
`occasion_data={}` so nothing caught it.

Three other Critical findings: the morning writes a *terminal* `skipped_by_judgment` status
on cascade infra failure (mislabeling a fault as judgment and locking out the whole day, with
no backstop by D-09), the weekly has no dedup guard on a now-retryable dispatch path, and the
manual "brief me" path (D-14) cannot work at all because it calls `asyncio.get_event_loop()`
from a worker thread.

The known-empty `skip_cause` is corroborated below with its root cause (WR-01) rather than
re-filed; the orphaned dead `return` near `core/tools.py:2033` is not re-filed per instructions.

## Critical Issues

### CR-01: Every occasion's gathered data is silently dropped before it reaches the LLM

> **PRODUCTION CORRECTION (2026-08-02, orchestrator).** The defect below is REAL and
> re-verified — `occasion_data` is merged at `:2244` and read by nothing; both prompt
> builders use fixed whitelists; `occasion_prompt` is the raw `*_occasion.md` text with
> no data interpolation. **But the stated consequence — that occasions compose blind —
> is contradicted by production evidence and is NOT what happens.**
>
> Layer 2 is agentic (D-21/D-22): it has tools and fetches what it needs. Evidence from
> the live run: the 2026-08-02 weekly review (`status: sent`, `composed_via: llm`) named
> specific per-day sessions across the whole week, and the 2026-08-01 nightly created
> three calendar events via tool calls. Neither is possible if the compose layer were
> blind.
>
> **Revised impact, split by layer:**
> - **Layer 2 (compose): waste, not blindness.** The gather is computed then discarded and
>   the brain re-fetches via tools. The weekly's `_gather_week_data` pays a ~28s blocking
>   Garmin login + Postgres query for nothing. Cost/latency bug, not a correctness bug.
> - **Layer 1 (triage): genuinely blind.** The tick-brain has NO tools, so it truly judges
>   occasions on generic tick signals only. This is the part that matters. The weekly is
>   `advisory_only=True` (Layer 1 cannot suppress it) and the nightly sent on both observed
>   nights — but the morning IS gated by Layer 1 judgment and has now skipped 3/3 days
>   (2026-07-31, 08-01, 08-02) with an empty cause. Prime suspect for the morning silence.
>
> **Fix priority follows from this:** rendering occasion data into the **Layer 1** payload
> is the high-value change. The Layer 2 render is a waste/latency cleanup, not urgent.

**File:** `core/autonomous.py:2244` (merge), `core/autonomous.py:1225-1248` (triage render),
`core/autonomous.py:1514-1539` (compose render)
**Issue:**
`run_occasion_cascade` merges the occasion's own Layer-0 gather with
`situation.update(occasion_data)`. Both prompt builders then read a **fixed whitelist** of
tick-era keys and nothing else:

- `_build_triage_prompt` `snap` = `calendar, ticktick_overdue, unread_email_count,
  due_followups, meals_since_last_tick, training_status, acwr, habit_pending, recovery,
  training_evidence, standing_directives, hours_since_contact` (+ self_state, journal digest,
  now block, outreach topics, directives, tail, training reality, occasion header, addendum).
- `_compose_layer2` `snap_summary` = the same whitelist minus a couple of keys.

Nothing iterates `situation` generically. Therefore:

| Occasion | Data gathered and merged | Reaches Layer 1 / Layer 2? |
|---|---|---|
| nightly | `journal` (D-07's whole point), `tomorrow` (calendar/tasks/weather/recovery/planned workouts), `tomorrow_*` snapshot keys | **No** |
| morning | `garmin` + `garmin_missing` (D-11), `tasks`, `weather`, `nutrition`, `recovery_concern`, `recovery_deviation`, `since_last_night`, `yesterday` (D-15), `block`, `weekly_review_due_today` (D-20), `bodyweight_kg`, `nutrition_targets` | **No** (only `calendar` and `standing_directives` survive, because those two keys happen to collide with the tick whitelist) |
| weekly_review | the entire `week_data`: `training_log`, `strength_sessions(_prev)`, `run_details(_prev)`, `activities`, `biometrics_*`, `nutrition_7day`, `athletic_goals`, `current_block`, `block_benchmarks`, `projections` | **No** (only `standing_directives` collides) |

The consequences are live, not theoretical:
- `core/weekly_training_review.py:629` still pays for `_gather_week_data` — a ~28s blocking
  Garmin login, Postgres biometrics query, MealStore 7-day loop, and `project_goal_progress`
  across five facets — and then discards all of it. The Sunday review is now composed from a
  generic tick snapshot plus a Groq one-liner draft.
- D-11's `garmin_missing` flag (33-07's stated deliverable, and the thing
  `tests/test_morning_briefing.py:958-971` asserts) is set on `today_data` and asserted at the
  `run_occasion_cascade` call boundary — but the flag never reaches a prompt, so nothing can act
  on it.
- D-20's "stay light on training, the weekly is at 10:00" signal is computed in `_gather_data`
  and dropped, while `prompts/morning_occasion.md` instructs Klaus to honour it.

`prompts/autonomous.md` §Inputs documents exactly what the compose receives, and it contains no
occasion-data block — confirming the render was never written, not that it was written and broken.
Every occasion test in `tests/test_autonomous.py:2849-3363` passes `occasion_data={}`, so the
suite cannot detect this.

**Fix:** render the occasion's own gather explicitly, in both builders, gated on
`situation.get("occasion")` so the tick path stays byte-identical and the Groq budget guard
(`tests/test_token_budget.py`) can bound the triage-side render:

```python
# core/autonomous.py — _build_triage_prompt, inside the `if occasion:` branch
occasion_payload = {
    k: v for k, v in situation.items()
    if k not in _SHARED_SITUATION_KEYS and k not in ("occasion", "occasion_target_date")
}
occasion_block = (
    f"\n\nOccasion data ({occasion}):\n"
    f"{json.dumps(_compact_for_triage(occasion_payload), ensure_ascii=False)[:_TRIAGE_OCCASION_MAX_CHARS]}"
)

# core/autonomous.py — _compose_layer2, next to occasion_block
occasion_data_block = (
    f"\n\nOccasion data:\n{json.dumps(occasion_payload, indent=2, ensure_ascii=False, default=str)}"
    if occasion_payload else ""
)
```

Then extend `test_maximal_occasion_triage_prompt_fits_groq_ceiling` with a realistic
`occasion_data` (weekly is the worst case) and add a test asserting the nightly's `journal`
summary and the weekly's `projections` appear in the Layer-2 user message.

---

### CR-02: A morning cascade infra failure is recorded as a terminal judgment skip, silently killing the day's briefing

**File:** `core/morning_briefing.py:358-368`
**Issue:** `run_morning_briefing_triggered` has exactly two terminal branches — `sent` or
`skipped_by_judgment`. Everything that is not a send falls into the `else`:

```python
_set_state(today_iso, {
    "status": "skipped_by_judgment",
    "trigger": trigger,
    "skip_cause": decision.get("skip_cause", ""),
    "draft": decision.get("draft", ""),
})
```

But `run_occasion_cascade` returns `sent=False, skipped=False` for every **infra** failure it
catches internally: `layer1_exception` (Groq *and* the Gemini fallback both failed),
`layer2_and_draft_both_empty`, and `send_failed` (Telegram failed twice, including the
`TimedOut` retry). The SC-1 plain-text fallback at lines 262-289 only fires when
`run_occasion_cascade` *raises*, which it almost never does — it swallows all three of those
cases and returns normally.

Result: a transient Groq/Gemini outage or a Telegram send failure produces
`status="skipped_by_judgment"` with `skip_cause=""` and `draft=""`. That status is in
`_TERMINAL_STATUSES` (line 173-175), so every later trigger that morning — a snooze, a second
alarm, a manual retry — is deduped away. Per D-09 the morning has **no cron backstop**. The
briefing is simply gone for the day, and it is recorded in Firestore as Klaus's judgment,
which is precisely what SC-1 says must never happen. The heartbeat cannot see it either:
`check_occasion_health` anomaly #1 only alerts on a `composed_via` fallback tier (absent here),
and anomaly #2 counts it toward a *judgment* skip streak.

`core/nightly_review.py:544-551` gets this right — it writes no terminal status and logs a
warning so the 01:00 backstop can retry. The morning is the seam that diverged.

**Fix:** distinguish the three outcomes, mirroring nightly, and take the SC-1 fallback on the
infra branch since the morning has no backstop:

```python
if sent:
    ...  # unchanged
elif decision.get("skipped") == "judgment":
    _set_state(today_iso, {"status": "skipped_by_judgment", ...})
else:
    # Cascade produced neither a send nor a judgment skip — infra fault.
    logger.error(
        "morning_briefing: cascade produced neither send nor judgment skip for %s "
        "(trail=%r) — SC-1 plain-text fallback", today_iso, decision.get("trail"),
    )
    try:
        from core.scheduled_message import send_and_inject
        fallback_text = _plain_text_fallback(today_data, today_iso)
        await send_and_inject(bot, fallback_text, inject_into_conversation=True,
                              message_class="briefing")
        _set_state(today_iso, {"status": "sent", "trigger": trigger,
                               "sent_at": now_iso, "composed_via": "plain_text_fallback"})
        return True
    except Exception:
        logger.error("morning_briefing: SC-1 fallback send failed for %s", today_iso,
                     exc_info=True)
    return False  # no terminal status written — a later trigger can still retry
```

---

### CR-03: The weekly review has no dedup guard on a now-retryable dispatch path — duplicate send

> **PRODUCTION NOTE (2026-08-02).** Latent, not yet realized. The 2026-08-02 Sunday run
> did produce TWO dispatches of `/cron/weekly-training-review` (`07:00:01Z` and
> `07:00:37Z`) but only ONE send (`weekly_reviews/2026-08-02` has a single `sent_at` at
> `07:01:29Z`, and Amit confirmed receiving exactly one review). So the window is real and
> was entered, but did not produce a duplicate this time. Keep the severity — the guard is
> still missing and the next slower compose can land inside it.

**NEW — CR-05: `check_occasion_health`'s weekly check races the weekly send (false CRITICAL).**
Observed live 2026-08-02: the heartbeat emitted `CRITICAL — Weekly review did not fire for
2026-08-02 — no weekly_reviews state doc` at `07:00:39Z`, while the weekly actually sent at
`07:01:29Z` — the alert fired ~50s BEFORE the send it was checking for. The Sunday check
runs against a state doc that the cascade has not written yet because it is still composing
(32K-token Sonnet compose, plus a ~28s blocking gather). Amit was also paged repeatedly for
`2026-07-26` across 2026-08-01, which is the known stale-counter pattern. Net effect: the
observability surface built to make the rollout watchable is emitting false criticals into
the user's chat. Fix alongside CR-03 — either gate the Sunday check behind an in-flight
marker (`OccasionInFlightStore` already exists) or push the check window past the compose
deadline.

**File:** `core/weekly_training_review.py:599-635`, `core/weekly_training_review.py:705-735`;
`interfaces/web_server.py:319-380`; `docs/DEPLOYMENT.md:1591-1593`
**Issue:** Phase 33 moved the weekly from an inline cron handler to Cloud Tasks
(`enqueue_occasion("weekly_review", ...)` → `/internal/process-occasion`). That endpoint
re-raises on any exception (`web_server.py`, `except Exception: _log_cron_run(...); raise`), and
the queue is created with `--max-attempts=2` (DEPLOYMENT.md §25), so **every 5xx or exceeded
`dispatch_deadline` (540s) is automatically retried once.**

`run_weekly_review` has no idempotency check whatsoever. `_get_state` / `_STATE_COLLECTION`
exist and are written on success, but never *read* before running. Nightly is guarded by
`was_sent(target_date)` and morning by `_TERMINAL_STATUSES`; the weekly is guarded by nothing.

The concrete failure: the weekly compose is the heaviest in the system
(`max_tokens=32000`, now through Layer 2's 12-iteration tool loop plus the D-22 forced-final
turn, each call bounded by `LLM_TIMEOUT_SECONDS=120`). If the send succeeds and the request
then exceeds the 540s dispatch deadline — or the instance is evicted between
`send_and_inject` and `_set_state` — Cloud Tasks retries, `_gather_week_data` runs again
(another ~28s Garmin login), and Amit receives the weekly review **twice**. The retry also
re-charges a 32K-token Sonnet compose.

**Fix:** read the state doc first, matching the nightly/morning contract:

```python
_WEEKLY_TERMINAL_STATUSES = frozenset({"sent", "skipped_by_directive"})

async def run_weekly_review(bot, today_iso: str, *, dedup: bool = True) -> None:
    if dedup and _get_state(today_iso).get("status") in _WEEKLY_TERMINAL_STATUSES:
        logger.info("weekly_review: already terminal for %s — skipping", today_iso)
        return
    ...
```

Also consider writing `{"status": "in_progress", "started_at": ...}` before the compose so a
retry after an eviction mid-compose can be distinguished from a never-ran Sunday (the
heartbeat's anomaly #3 currently reads an absent doc as CRITICAL "did not fire").

---

### CR-04: The manual "brief me" tool (D-14) cannot run — `get_event_loop()` in a worker thread

**File:** `core/tools.py:2058-2086`
**Issue:** `_handle_run_morning_briefing` does:

```python
loop = asyncio.get_event_loop()
from core.morning_briefing import run_morning_briefing_triggered
loop.create_task(run_morning_briefing_triggered(...))
```

Tool handlers execute inside `AgentOrchestrator._run_smart_loop`, which is synchronous and is
invoked via `asyncio.to_thread(self.orchestrator.handle_message, ...)`
(`interfaces/_router.py:344-349`). `asyncio.get_event_loop()` only auto-creates a loop on the
**main** thread; from a `ThreadPoolExecutor` worker with no loop set it raises
`RuntimeError("There is no current event loop in thread 'asyncio_0'")`. That is caught by the
handler's own `except Exception` at line 2085 and returned to the model as
`{"error": "There is no current event loop..."}` — so a manual "brief me" produces an apology,
never a briefing, and no state doc is written. Phase 33 explicitly designates this the D-14
manual path (`run_morning_briefing_triggered(..., trigger="manual", dedup=False)`), and there
is **no test** for this handler anywhere in `tests/` (only the legacy `run_morning_briefing`
composer is covered).

Second defect on the same lines: even with a valid loop, `loop.create_task(...)` runs the full
3-layer cascade (Groq triage + a 12-iteration Sonnet tool loop) as fire-and-forget work that
outlives the `/internal/process-update` response — the exact CPU-throttling failure mode
CLAUDE.md forbids and D-32/plan 33-10 was built to eliminate. Plan 33-10 shipped the correct
mechanism (`enqueue_occasion`) and plan 33-07 did not use it.

**Fix:** dispatch through Cloud Tasks like every other occasion entry point — synchronous,
thread-safe, and inside a tracked request:

```python
def _handle_run_morning_briefing() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        from core.task_dispatch import enqueue_occasion
        if not enqueue_occasion("morning", trigger="manual", target_date=today_iso):
            return json.dumps({"error": "Dispatch unavailable — could not enqueue the briefing."})
        from core.morning_briefing import _set_state
        _set_state(today_iso, {"trigger": "manual",
                               "requested_at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat()})
        return json.dumps({"status": "queued", "date": today_iso})
    except Exception as exc:
        logger.warning("run_morning_briefing tool error: %s", exc)
        return json.dumps({"error": str(exc)})
```

Note the manual path needs `dedup=False` semantics; either add an explicit `dedup` field to the
`enqueue_occasion` payload and honour it in `/internal/process-occasion`, or keep deriving it
from `trigger == "manual"` there. Do **not** keep writing `status: "manual"` up front — it is a
member of `_TERMINAL_STATUSES` and would block the very run it just requested if the enqueue
later fails.

## Warnings

### WR-01: Root cause of the known-empty `skip_cause` — the tick-brain parser whitelists it away

**File:** `core/tick_brain.py:340-351`; `tests/occasion_helpers.py:163-169`;
`core/heartbeat.py:398-410`
**Issue:** (Corroborating the deferred item, not re-filing.) Phase 33 added `skip_cause` to the
triage output schema (`prompts/autonomous_triage.md:91`) and built the whole D-02 taxonomy
around it, but `TickBrain._parse_response` constructs its return dict from a hard-coded
whitelist:

```python
result = {"should_act": ..., "reason": ...}
if "draft" in data and data["draft"]: result["draft"] = ...
if "topic_key" in data and data["topic_key"]: result["topic_key"] = ...
return result
```

`skip_cause` is dropped before `_run_cascade` ever calls `verdict.get("skip_cause", "")`
(`core/autonomous.py:2000`), so it is **structurally impossible** for it to be non-empty — this
is not a prompt-compliance issue. Knock-on effects: `nightly_reviews`/`morning_briefings`
`skip_cause` fields are always `""`, and `heartbeat._occasion_skip_streak`'s alert detail
degrades to `"unknown, unknown, unknown"`, which defeats the purpose of D-28 #2's
"distinguish nothing_happened from reaction_history".

Why no test caught it: `tests/occasion_helpers.py::make_occasion_verdict` fabricates a verdict
dict *containing* `skip_cause`, i.e. a shape the production parser can never emit. Every
downstream occasion test asserts against that fiction.
**Fix:** in `_parse_response`, add `if data.get("skip_cause"): result["skip_cause"] = str(data["skip_cause"])`,
validate against the `SKIP_CAUSES` vocabulary, and add a `TickBrain._parse_response` test that
feeds raw model JSON (not a hand-built dict) and asserts `skip_cause` survives.

---

### WR-02: Occasion tick-log snapshots are unbounded and can exceed Firestore's 1 MiB doc limit

**File:** `core/autonomous.py:1846`, `memory/firestore_db.py:2908-2924`
**Issue:** `_write_tick_log` persists `{k: v for k, v in situation.items() if k != "empty"}`.
For an occasion, `situation` now includes the *entire* merged `occasion_data`. For the weekly
that is `strength_sessions` + `strength_sessions_prev` (full per-set Hevy detail),
`run_details` + `run_details_prev` (full per-lap Garmin `lapDTOs`), two weeks of `activities`,
`biometrics_*`, and `projections` — plausibly hundreds of KB and capable of crossing Firestore's
1 MiB document ceiling. `TickLogStore.write` swallows the resulting `InvalidArgument` and logs
a warning, so the failure is invisible and the decision record for the *biggest* occasions is
the one that silently disappears — exactly the record `get_recent_decisions` (D-26) and the
retroactive eval-fixture workflow (D-21) depend on.
**Fix:** compact the occasion payload before persisting, e.g. keep the tick keys verbatim and
store a summarised form of the occasion keys (counts + top-level scalars), or add an explicit
size guard:

```python
snapshot = {k: v for k, v in situation.items() if k != "empty"}
if len(json.dumps(snapshot, default=str)) > _TICK_LOG_MAX_BYTES:
    snapshot = _compact_snapshot(snapshot)  # drop per-set/per-lap detail, keep shapes
```

---

### WR-03: The D-19 in-flight marker is set after the gather it is supposed to cover

**File:** `core/autonomous.py:2243-2262`
**Issue:** `run_occasion_cascade` runs `gather_situation(now)` (a 17-source thread-pool fan-out
issuing Calendar, Gmail, Garmin, Postgres and many Firestore calls — seconds of wall clock)
**before** `store.mark(occasion, ttl_seconds=900)`. The docstring claims the marker covers "the
duration of the cascade"; it covers the cascade minus its longest deterministic prefix. A `*/20`
tick landing in that window sees no marker and proceeds, defeating D-19 in the most likely
collision case (the morning trigger firing at 07:00, exactly on a tick boundary).

Secondary: `OccasionInFlightStore` uses a single `current` document for all occasions, and
`clear()` deletes unconditionally in the `finally`. If two occasions ever overlap (a manual
brief-me during the 01:00 backstop), the first to finish erases the second's marker.
**Fix:** move `store.mark(...)` above `gather_situation(now)`; scope `clear()` to the marker
this call owns:

```python
store = _occasion_inflight_store()
try:
    store.mark(occasion, ttl_seconds=900)
except Exception:
    logger.warning(...)
situation = gather_situation(now)
...
finally:
    try:
        if store.active() == occasion:
            store.clear()
    except Exception:
        ...
```

---

### WR-04: The D-22 forced-final turn strips `tools` from a message list that still contains `tool_use` blocks

**File:** `core/main.py:1051-1091`
**Issue:** At iteration exhaustion, `current_messages` ends with an assistant message containing
`tool_use` blocks plus a user message of `tool_result` blocks. The forced-final call passes
`tools=None`, and `_AnthropicBackend.chat` only sets `kwargs["tools"]` when `tools` is truthy
(`core/llm_client.py:286-288`) — so the request omits `tools` entirely while carrying
`tool_use`/`tool_result` content. Anthropic requires `tools` to be defined for such requests;
the 400 becomes an `APIStatusError` → `LLMError` → the `except LLMError` at line 1086 swallows
it, logs "raised after iteration exhaustion", and falls through. D-22 would then be a permanent
silent no-op on the production brain (`claude-sonnet-5`), with only a WARNING line to show for
it. The tests (`tests/test_main.py:259-303`) mock `smart_agent.chat` wholesale and assert
`tools is None` was passed, so they can never surface the API constraint.
**Fix:** keep the tool definitions and forbid their use, which is the supported mechanism:

```python
forced_response = self.smart_agent.chat(
    current_messages, system=smart_system, tools=smart_tools,
    purpose="smart_forced_final", max_tokens=max_tokens,
    extra_params={"tool_choice": {"type": "none"}},
)
```

(`_AnthropicBackend` currently ignores `extra_params`; thread `tool_choice` explicitly.) Verify
against a live call before trusting D-22 — and consider logging the forced-final outcome at a
level the heartbeat can count, since an always-failing recovery path should not be invisible.

---

### WR-05: `_existing_event_at` silently ignores `calendar_id`, and the duplicate check now blocks user-requested creates

**File:** `core/tools.py:1686-1725`, `core/tools.py:1789-1826`
**Issue:** Two problems in the D-23 idempotency pre-check:

1. `_existing_event_at(start_iso, end_iso, summary, calendar_id=None)` accepts `calendar_id`
   and never uses it. It calls `list_all_events(start_iso, end_iso)`, which enumerates **all
   writable calendars**. So a same-titled event on *any* calendar suppresses a create on the
   Training calendar (and vice-versa). The parameter is dead and actively misleading — a reader
   will assume the lookup is calendar-scoped.
2. The check is wired into `_handle_create_calendar_event`, i.e. **every** create, not just
   proactive Layer-2 ones. The docstring says "call it immediately before every *proactive*
   `create_event`". An interactive request ("add a second Standup at 14:00 tomorrow" where a
   "Standup" already overlaps) now returns `{"created": false, "duplicate": true}` with no
   override path, and the brain has to explain a refusal Amit did not ask for.
3. `list_all_events` defaults to `max_results=20` **per calendar**; a busy multi-day window
   could truncate before reaching the match, so the check silently weakens exactly when the
   calendar is full.

**Fix:** honour the scope and give proactive callers an opt-in:

```python
def _existing_event_at(start_iso, end_iso, summary, calendar_id=None) -> dict | None:
    ...
    events = (
        _get_calendar_tool().list_events(start_iso, end_iso, max_results=50)
        if calendar_id in (None, "primary")
        else [e for e in _get_calendar_tool().list_all_events(start_iso, end_iso, max_results=50)
              if e.get("calendar_id") == calendar_id]
    )

def _handle_create_calendar_event(..., skip_duplicate_check: bool = False) -> str:
    if not skip_duplicate_check:
        existing = _existing_event_at(...)
```

---

### WR-06: Unsetting `CLOUD_TASKS_QUEUE` now silently disables all three occasions, and a permanently-failing morning trigger is undetectable

**File:** `core/task_dispatch.py:120-122`, `interfaces/web_server.py:672-720` (`/trigger/morning`),
`core/heartbeat.py:106-126`
**Issue:** DEPLOYMENT.md §25 documents "Unsetting `CLOUD_TASKS_QUEUE` disables dispatch entirely
(clean rollback to the background path)". That is true for the Telegram webhook, which has an
in-process fallback. It is **not** true for occasions: `enqueue_occasion` returns `False`
immediately, and `/trigger/nightly`, `/trigger/morning`, `/cron/nightly-backstop` and
`/cron/weekly-training-review` all just return 503. The documented rollback lever now kills the
nightly, the morning and the weekly with no fallback.

Worse for the morning specifically: `trigger_morning` never calls `_log_cron_run`, the
`morning-briefing` staleness key was removed from `_CRON_MAX_STALENESS_HOURS`, D-09 removed the
backstop, and `_occasion_skip_streak` explicitly *skips* dates with no state doc ("unknown,
keep walking"). So a morning that never fires at all — expired Shortcut token, iOS automation
disabled, enqueue failing — produces zero signals anywhere. The heartbeat comment at
`core/heartbeat.py:120-123` claims anomaly #1 covers this; anomaly #1 only covers a morning
that *ran* and degraded.
**Fix:** (a) record enqueue outcomes for the trigger routes
(`_log_cron_run("morning-trigger", ok=ok)`), and (b) add a "morning has produced no state doc
in > 48h" signal to `check_occasion_health` — the one anomaly class D-28 is missing:

```python
recent_morning = any(
    _read_occasion_state(_OCCASION_STATE_COLLECTIONS["morning"],
                         (today - timedelta(days=off)).isoformat())
    for off in range(2)
)
if not recent_morning:
    signals.append(Signal(fingerprint="occasion:morning:not_fired",
                          severity=SEVERITY_CRITICAL, area="occasion", ...))
```

---

### WR-07: `/internal/process-occasion` validates `occasion` but passes `target_date` unvalidated into Firestore document ids

**File:** `interfaces/web_server.py:322-380`
**Issue:** The handler carefully whitelists `occasion` (T-33-13: "a caller-supplied string never
reaches a Firestore document id unvalidated") and then takes `target_date` straight from the
request JSON and hands it to `run_nightly` → `was_sent(target_date)` →
`client.collection("nightly_reviews").document(target_date)`, and to `run_weekly_review` →
`date.fromisoformat(today_iso)` (uncaught `ValueError` → 500 → retry → dead-letter). A value
containing `/` splits the Firestore path; a non-date string crashes the weekly. The route is
OIDC-gated so this is not remotely exploitable today, but the stated invariant is only half
enforced, and the failure mode of a malformed payload is a retry loop rather than a 400.
**Fix:**

```python
target_date = request_json.get("target_date")
if target_date is not None:
    try:
        date_cls.fromisoformat(str(target_date))
    except ValueError:
        raise HTTPException(status_code=400,
                            detail={"error": f"invalid target_date: {target_date!r}"})
```

Also rename the local `date` variable (it shadows the conventional `datetime.date` name and
would collide the moment someone adds that import).

---

### WR-08: The weekly's directive-veto reason travels through a mutable module global

**File:** `core/weekly_training_review.py:48`, `core/weekly_training_review.py:579-596`,
`core/weekly_training_review.py:739-750`
**Issue:** `_parse_review_skip` writes `_LAST_DIRECTIVE_VETO_REASON` as a side effect so
`_run_weekly_review_cascade` can read it back after `run_occasion_cascade` returns. The same
function is also the legacy path's parser and could be called from tests or a future caller.
The global is never reset after being read, is process-wide across Cloud Run requests, and
couples a pure parser to one specific caller's control flow. It is safe *today* only because
the weekly fires once a week and the read happens in the same event-loop turn — a comment
acknowledging "no cross-request race in practice" is not the same as no race.
**Fix:** widen the hook contract instead of smuggling state. `_run_cascade` already computes
`veto_reason`; surface it on the decision dict it returns:

```python
# core/autonomous.py::_run_cascade
if veto:
    decision["skipped"] = "directive"
    decision["skip_cause"] = "standing_directive"
    decision["veto_reason"] = veto_reason
```

then read `decision.get("veto_reason", "")` and delete the global.

---

### WR-09: The persisted tick log omits follow-up outcomes and can record "skipped" for a tick that sent a message

**File:** `core/autonomous.py:2333-2375`
**Issue:** `run_autonomous_tick` appends follow-up outcomes to its *local* `decision["trail"]`,
then calls `_run_cascade`, which builds a **fresh** decision dict and writes the tick log from
it. The follow-up entries are merged into the return value only afterwards
(`cascade_decision["trail"] = decision["trail"] + cascade_decision["trail"]`), long after
`_write_tick_log` has already persisted the cascade-only trail. So the Firestore record — the
sole backing store for `get_recent_decisions` (D-26) — never shows that a follow-up fired, and
a tick that sent a follow-up but then triaged to silence is persisted as
`{"skipped": "judgment", "sent": false}`. That is precisely the "why didn't you message me?"
question OCC-07 exists to answer, answered wrongly.
**Fix:** thread the prior trail into the cascade so the log is written once, complete:

```python
cascade_decision = await _run_cascade(
    bot, now, situation, occasion=None, topic_key=None, advisory_only=False,
    occasion_prompt="", max_tokens=None,
    log_key=now.astimezone(_TZ).strftime("%H:%M"),
    prior_trail=decision["trail"],           # seeded into decision["trail"] inside _run_cascade
)
```

---

### WR-10: The committed `docs/SELF.md` advertises a route that no longer exists

**File:** `docs/SELF.md:48`
**Issue:** `core/self_manifest.py` was correctly updated to emit "8 scheduled jobs" without
`morning-briefing-tick`, but the committed `docs/SELF.md` was regenerated at a point that
predates that change and still says "9 scheduled jobs … morning-briefing-tick (\*/10 6-10,
`/cron/morning-briefing-tick`)" — a route deleted in `interfaces/web_server.py`. SELF.md is
injected into the brain's system prompt (`{self_md}`), and `read_own_source` serves it verbatim,
so Klaus will describe a cron that returns 404. CI regenerates it on deploy so the live
container is fine, but every local run, every test that reads the file, and every human reading
the repo sees the stale copy. Line 89's "Autonomous proactive outreach: not yet implemented
(Phase 18)" is likewise false. The same staleness exists in `docs/TECHNICAL_PLAN.md:32/89/347`
(out of review scope but same root cause).
**Fix:** run `python core/self_manifest.py` and commit the result; add a docs test asserting
`"/cron/morning-briefing-tick" not in SELF.md` alongside the existing
`tests/test_docs.py` checks.

---

### WR-11: The documented timeout chain no longer holds now that Layer 2 runs 12 tool iterations

**File:** `core/task_dispatch.py:43`, `docs/DEPLOYMENT.md:1614-1616`, `core/main.py:896`
**Issue:** DEPLOYMENT.md states the invariant "Cloud Run `--timeout 600` > task
`dispatch_deadline` 540s > per-LLM-call `LLM_TIMEOUT_SECONDS` (default 120s)". That held when
the occasion path was a single compose call. It no longer does: `_run_cascade` → `_compose_layer2`
→ `_run_smart_loop` can now issue up to `MAX_TOOL_ITERATIONS = 12` brain calls plus the D-22
forced-final (13 × up to 120s = 1560s worst case), each with its own worker-loop sub-calls, on
top of `gather_situation`'s network fan-out and the weekly's ~28s Garmin login. The chain is
now inverted at the top, which is the mechanism that turns CR-03 into a duplicate send.
**Fix:** either bound the compose wall clock explicitly (a deadline passed into
`_run_smart_loop` that stops the loop when exceeded) or raise `dispatch_deadline` and the Cloud
Run timeout to exceed the real worst case — and update the DEPLOYMENT.md chain so the stated
invariant matches reality.

---

### WR-12: `check_occasion_health` reads `now.hour` without normalising the caller-supplied timezone

**File:** `core/heartbeat.py:566-572`
**Issue:** `now = now or datetime.now(_TZ)` then `before_cron_fires = is_today_sunday and
(now.hour, now.minute) < (10, 0)`. When a caller passes a `now` in any other zone (UTC is the
convention everywhere else in this module — `check_cron_health` uses
`datetime.now(timezone.utc)`), the 10:00 Jerusalem guard is evaluated against the wrong clock,
producing a spurious CRITICAL "Weekly review did not fire" for up to three hours every Sunday
morning. `today = now.date()` has the same latent bug and can select the wrong Sunday.
**Fix:** normalise on entry — `now = (now or datetime.now(_TZ)).astimezone(_TZ)` — and add a
test that passes a UTC `now` at Sunday 06:00 UTC (09:00 local) and asserts no signal.

---

_Reviewed: 2026-08-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
