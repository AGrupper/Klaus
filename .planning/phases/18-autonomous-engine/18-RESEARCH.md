# Phase 18: Autonomous Engine — Research

**Researched:** 2026-05-20
**Domain:** Cloud Run cron-driven 3-layer autonomous reasoning + judgment eval
**Confidence:** HIGH (CONTEXT.md is exhaustive; spot-checks confirmed `_run_smart_loop`, `_parse_response`, and cron route shapes)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01 through D-22)

**Outreach latitude:**
- D-01: Trigger types = overdue TickTick tasks, calendar gaps/overload (mid-day), long silence, due follow-ups. NOT same-day event prep (Phase 17 covers it).
- D-02: No cadence cap. Judgment over throttle.
- D-03: Mixed-register voice — action when one exists, observation otherwise. Both triage `draft` and Layer-2 compose follow this.
- D-04: Triage sees self-state — last ~3 journal entries (Phase 17 D-14 digest) + `current_focus` + `mood` from `SelfStateStore`.
- D-05: No hard floor on `hours_since_contact`; pass raw to triage.

**Repeat-suppression (informative, not blocking):**
- D-06: Per-topic dedup is default, but suppression is informative (triage is *told* what was raised today), not blocking.
- D-07: Klaus generates `topic_key` as the 4th field in the tick-brain JSON output. `_parse_response` must accept and pass through. `outreach_log/{date}` records `{topic_key, time, draft}`; next triage receives the list.
- D-08: Triage prompt receives current time + window position (`"now: 19:40 Asia/Jerusalem, tick 39 of ~42, last tick at 20:40"`).
- D-09: Daily reset — `outreach_log` keyed by date. Cross-day continuity via `journal_digest`.
- D-10: Log on success only — write to `outreach_log/{date}` after Telegram send succeeds.
- D-11: Layer 0 gate — if `gather_situation()` produces no salient signals, skip tick-brain entirely. Primary cost control.

**Follow-up behavior:**
- D-12: `when` accepts ISO 8601 preferred, natural-language as fallback. Try `datetime.fromisoformat()` first; on failure `dateutil.parser.parse()`. Stored as ISO-8601 UTC.
- D-13: Hybrid fire — every tick checks `FollowupStore` for `due_at <= now AND status != 'done'`. Each due follow-up triggers a **dedicated Layer-2 compose** (skips tick-brain).
- D-14: Defer mechanism — Layer-2 may return `{"action": "defer"}`; handler sets `due_at += 1h`, increments `defer_count`. After `defer_count >= 3`, force-fire on next due tick.
- D-15: Three direct tools (15 total edit points in `core/tools.py`):
  - `schedule_followup(when: str, note: str) -> {id, due_at}`
  - `list_followups() -> [{id, due_at, note, defer_count}]`
  - `cancel_followup(id: str) -> {ok: bool}`

**Escalation & compose:**
- D-16: Layer 2 sees situation_snapshot + tick-brain draft + journal_digest + self_state (auto-injected via `_run_smart_loop`'s render step).
- D-17: No second veto. Tick-brain is the gate. Follow-up polish-or-defer is the only documented exception (and that path has no tick-brain in front of it).
- D-18: Proactive messages inject into conversation history — `send_and_inject(bot, msg, inject_into_conversation=True)`. Diverges from `proactive_alerts` (which uses `False`).
- D-19: On Layer-2 failure (LLM error or unparseable output even after Gemini → Claude-Haiku fallback), fall back to tick-brain's `draft` text and send as-is. `outreach_log` records normally.
- D-20: Layer 2 runs the **full smart_agent tool-loop** via `_run_smart_loop` (`core/main.py:241`) — synthetic user message = `situation_snapshot + tick-brain draft`; `smart_system` = `prompts/autonomous.md` rendered with SELF.md / self_state / journal_digest. Bounded by `MAX_TOOL_ITERATIONS = 8`.

**Judgment eval:**
- D-21: Fixtures captured from live ticks. Ship Phase 18 with ~5 hand-written seeds; every live tick logs `situation_snapshot` to `tick_logs/{date}/{tick_time}`; retroactively label ~25 over a week to reach AUTO-08's 20–30 target.
- D-22: `scripts/eval_tick_brain.py` prints **overall precision/recall/F1** for `should_speak` **plus a per-trigger-type breakdown table** (overdue, gap, silence, followup).

### Claude's Discretion
- Exact Firestore schemas: `outreach_log/{date}` shape, `followups` collection shape, `tick_logs/{date}/{tick_time}` TTL.
- `topic_key` length cap / validation regex.
- Eval fixture JSON schema (single file with array vs file-per-fixture).
- `prompts/autonomous_triage.md` and `prompts/autonomous.md` exact wording (persona via `docs/AGENT.md`, wide-latitude framing per AUTO-07, structured JSON output enforcement on triage).
- Layer-2 model fallback chain — use `SMART_AGENT_*` → `SMART_AGENT_FALLBACK_*` pattern from `core/main.py:260–291`.
- INFRA-01: documenting all 9 crons + Groq secret + Five Fingers job-id quirk.
- Whether `list_followups` includes cancelled (probably not). Whether `cancel_followup` is idempotent (it should be).
- Whether to surface today's running cost from `LLMUsageStore.summary` to the triage prompt.

### Deferred Ideas (OUT OF SCOPE)
- Per-trigger inject-into-conversation logic.
- Layer-2 second veto on self_state.
- Layer-2 deferral for non-follow-up sends.
- Cancel-via-natural-language pipeline.
- Cost-aware judgment (data available; surfacing is discretionary).
- `tick_logs` retention TTL.
- Web/Notion UI for managing follow-ups.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUTO-01 | `run_autonomous_tick()` implements 3-layer design | `core/autonomous.py` design below; `gather_situation()` (Layer 0), `TickBrain.think()` extended (Layer 1), `_run_smart_loop` synthetic-message integration (Layer 2) |
| AUTO-02 | `gather_situation()` fetches calendar, TickTick, unread email, follow-ups, hours_since_contact, recent journal, today's outreach log | Mirrors `core/reflection.py:_gather_day` best-effort-per-source pattern |
| AUTO-03 | Repeat-suppression: `outreach_log/{date}` records every send; tick-brain informed of today's raised topics | `OutreachLogStore` (new), informative-not-blocking per D-06; `topic_key` per D-07 |
| AUTO-04 | `FollowupStore` stores scheduled follow-ups with `{due_at, note, created_at, done}` | `JournalStore` is the closest analog in `memory/firestore_db.py`; schema extension below |
| AUTO-05 | `schedule_followup(when, note)` direct tool | 3 tools total per D-15; 15-edit-point pattern (Phase 15) |
| AUTO-06 | `/cron/autonomous-tick` route fires `*/20 7-21 * * *` Jerusalem | `cron_reflect` (`web_server.py:334–355`) is the closest template |
| AUTO-07 | `prompts/autonomous_triage.md` (tick-brain) and `prompts/autonomous.md` (main-brain) created with wide-latitude framing | D-02/D-03/D-05/D-17 inform wording; `prompts/proactive_alert.md` is the tone reference |
| AUTO-08 | Judgment eval harness with ~20–30 labeled `SituationSnapshot` fixtures | Bootstrap with ~5 seeds; grow from `tick_logs/{date}` (D-21) |
| AUTO-09 | `scripts/eval_tick_brain.py` scores precision/recall on "should speak" | Plus per-trigger-type breakdown (D-22) |
| INFRA-01 | `docs/DEPLOYMENT.md` documents all 9 Cloud Scheduler jobs + Groq secret + Five Fingers job-id quirk | New cron count = existing 7 + reflect (Phase 17) + autonomous-tick (Phase 18) |
</phase_requirements>

## Summary

- **Phase 18 is mostly composition.** Every primitive Klaus needs (`LLMClient` cost metering, `TickBrain`, `SelfStateStore`, `JournalStore`, `_run_smart_loop`, `send_and_inject`, cron OIDC + ledger, 5-site direct-tool pattern) ships from Phases 14–17. The novelty is the 3-layer orchestration in `core/autonomous.py` and the judgment-eval harness.
- **Layer 2 = synthetic chat turn.** D-20 unlocks the elegant payoff: by feeding `situation_snapshot + draft` as a `user` message into `_run_smart_loop` with `prompts/autonomous.md` as `smart_system`, all SELF.md / self_state / journal_digest injection comes free from the per-message render step at `core/main.py:236–275`. **No new injection machinery.**
- **The 15-edit-point tool registration is the highest-mechanical-risk task.** With 3 new follow-up tools × 5 sites in `core/tools.py` (TOOL_SCHEMAS, SMART_AGENT_DIRECT_TOOLS, WORKER_TOOL_SCHEMAS exclusion, `_HANDLERS`, `_handle_<name>()` function), Wave 1 should treat it as a single atomic task with a verification checklist.

**Primary recommendation:** Sequence as Wave 1 = data/tools/prompts/eval-seed (parallel-safe), Wave 2 = orchestration + cron + `tick_brain.topic_key` extension (sequential — depends on Wave 1), Wave 3 = eval runner + INFRA-01 docs. Treat INFRA-01 as floating; can land anywhere.

## Implementation Approach

### `core/autonomous.py` (NEW) — orchestration entry point

Three top-level functions plus one Telegram-send helper:

1. **`gather_situation(now: datetime) -> dict`** (Layer 0)
   - Returns the `situation_snapshot`. Best-effort per source — copy the `core/reflection.py:_gather_day` pattern verbatim: each block (calendar, ticktick_overdue, unread_email_count, due_followups, hours_since_contact, recent_journal_digest, today_outreach_log, current_self_state) lives in its own `try/except` that logs and returns `None`/`[]`/`""` on failure.
   - Compose `now` context: `{"now_iso": now.isoformat(), "now_local": now.strftime("%H:%M %Z"), "tick_index": <N>, "tick_total": ~42, "last_tick_at": <prev>}` per D-08.
   - **Salient-signals check** at the bottom of the function: returns `{"empty": True, "raw_signals": {...}}` if (no overdue tasks AND no due follow-ups AND no calendar gap/overload AND no `topic_key`s in today's outreach_log worth re-raising). This drives the D-11 / SC-3 Layer-0 gate.

2. **`run_autonomous_tick(bot, now=None) -> dict`** (top-level orchestrator)
   - Steps:
     - `situation = gather_situation(now)`
     - If `situation["empty"]`: log `tick_logs/{date}/{tick_time}` with `decision="skipped_empty"`, return `{"sent": False, "skipped": "empty"}`.
     - **Follow-up fire path (D-13/D-14):** `due = FollowupStore.list_due(now)`. For each due item: call `_compose_followup(bot, item, situation)` which runs a dedicated Layer-2 (no tick-brain), parses the JSON action (`{"action": "send"|"defer"}`), either sends via `send_and_inject(..., inject_into_conversation=True)` and `FollowupStore.mark_done(id)`, or defers `due_at += 1h` + `defer_count++` (force-fire on next tick once `defer_count >= 3`).
     - **Triage path (Layer 1):** Build the triage prompt by rendering `prompts/autonomous_triage.md` with `situation`, `self_state`, `journal_digest`, `now/tick_index`, and today's `outreach_log`. Call `TickBrain.think(prompt)`. Expect `{should_act, reason, draft, topic_key}`.
     - If `should_act=False`: log decision to `tick_logs`, return.
     - **Compose path (Layer 2):** Build a synthetic messages list of length 1: `[{"role": "user", "content": <situation_summary + tick-brain draft>}]`. Call `_run_smart_loop(messages, smart_system=<rendered autonomous.md>, worker_system=<same as main>)`. On any exception or empty return, fall back to `tick_brain_result["draft"]` per D-19.
     - Send via `send_and_inject(bot, final_text, inject_into_conversation=True)`.
     - **On send success only** (D-10): `OutreachLogStore.append(date, {topic_key, time, draft_or_final})`. Log `tick_logs/{date}/{tick_time}` with full snapshot + decision trail.
   - Cost metering: every LLM call already gets a `purpose=` (Phase 14). Use `"tick_autonomous"` for Layer 1 and `"autonomous_compose"` / `"autonomous_compose_fallback"` for Layer 2.

3. **`_compose_followup(bot, followup_item, situation)`** — helper for D-13. Runs Layer 2 with a per-followup prompt variant (or a header inside `autonomous.md`) instructing Klaus to either polish-and-send or defer with structured output.

**Module shape (file outline only — file size target ~250–300 LOC):**
```python
def gather_situation(now): ...
def run_autonomous_tick(bot, now=None): ...
def _compose_layer2(situation, draft, smart_system, ...): ...
def _compose_followup(bot, followup, situation): ...
def _build_triage_prompt(situation, self_state, journal_digest, outreach_today): ...
```

### `core/tick_brain.py` — `topic_key` schema extension (D-07)

Minimal surgical change. **Two edits:**

1. **`_TICK_SYSTEM_PROMPT`** (lines 30–45): Replace with the autonomous-aware variant. **However**, the autonomous prompt should override via the `system=` arg path. Cleanest approach: extend the **schema doc** in `_TICK_SYSTEM_PROMPT` to mention `topic_key` (so heartbeat callers also tolerate it as an optional field), but make `topic_key` **optional** in `_parse_response`.
2. **`_parse_response`** (lines 158–179): After validating `should_act`, harvest `data.get("topic_key", "")` and `data.get("draft", "")` and include them in the returned dict. Keep safe-mode return unchanged (no `topic_key` key).

**Critical:** The autonomous tick passes its **own** system prompt via the `system=` kwarg? — check: `TickBrain.think()` does not currently expose a `system_override` param; it hardcodes `_TICK_SYSTEM_PROMPT`. Two viable approaches for the planner:
- **(a) Add `system_override: str | None = None` param to `TickBrain.think()`** — clean and reusable. Heartbeat continues passing nothing, autonomous passes its autonomous_triage prompt.
- **(b) Render the full triage instruction (including JSON schema) as the user-message prompt** and leave `_TICK_SYSTEM_PROMPT` unchanged — works because Qwen3 follows instructions in the user message reliably, but the JSON contract is now duplicated across two prompt files.

**Recommend (a).** Single additional kwarg with default `None`. Phase 17 D-08 set the precedent for "extend an existing function with a new optional param."

### `memory/firestore_db.py` — two new stores

Pattern reference: `JournalStore` (Phase 17) for date-keyed collections; `SelfStateStore` (`memory/firestore_db.py:601`) for singletons. **Never raise** — all errors return `{}`, `[]`, or `None`.

**`FollowupStore`** (AUTO-04 + D-12/D-13/D-14/D-15):
```
Collection: followups/{id}
Doc shape: {
  id: str (auto: ULID or uuid4),
  due_at: str (ISO-8601 UTC),
  note: str,
  created_at: str (ISO-8601 UTC),
  status: "pending" | "done" | "cancelled",   # enum (D-15 spirit; map "done"-bool from AUTO-04 literal)
  defer_count: int (default 0),
  origin: str ("user_chat" | "klaus_self"),    # optional but useful in eval
}
```
- Methods: `add(due_at, note, origin) -> {id, due_at}`, `list_due(now) -> [item, ...]` (returns where `due_at <= now AND status == "pending"`), `list_pending() -> [...]` (status == "pending"), `mark_done(id)`, `cancel(id) -> bool` (idempotent — returns `True` even if already cancelled), `defer(id, new_due_at)` (increments `defer_count`).
- **Note on AUTO-04 literal:** the spec says `done` field; the implementation should use `status` enum (richer — supports cancelled, supports defer tracking). Document the deviation in the task; it preserves the *intent* (was-it-sent gate).

**`OutreachLogStore`** (AUTO-03 + D-07/D-09/D-10):
```
Collection: outreach_log/{date} (YYYY-MM-DD doc, single doc per day)
Doc shape: {
  date: "YYYY-MM-DD",
  entries: [
    {topic_key: str, time: str (HH:MM Asia/Jerusalem), draft: str, final: str, tick_index: int},
    ...
  ],
}
```
- Methods: `append(date, entry)`, `get_today(date) -> [entry, ...]`, `topics_today(date) -> [topic_key, ...]` (used to feed the triage prompt).
- **Daily reset is free** — the new date key creates a fresh doc.

**Tick logs (D-21 / Claude's discretion):**
- Suggest a third lightweight store `TickLogStore.write(date, tick_time, snapshot, decision_trail)` writing to `tick_logs/{date}/ticks/{tick_time}`.
- TTL: defer — Firestore has no built-in TTL by default, so retention is a future cleanup script. Document as a known future task; ≈42 docs/day × 365 ≈ 15k/year is acceptable for the eval bootstrap window.

### `core/tools.py` — 15-edit-point pattern

The mechanical risk task. **Single atomic task in Wave 1.** Provide an inline checklist in the task body and require a `grep`-based verification at the end.

For each of `schedule_followup`, `list_followups`, `cancel_followup`:

1. **`TOOL_SCHEMAS`** (`core/tools.py:45+`) — append a JSON schema entry.
   - `schedule_followup`: `{when: string, note: string}` both required. Description = "Schedule a check-back from yourself. `when` accepts ISO 8601 or natural language ('tomorrow 3pm')."
   - `list_followups`: no params. Description = "List your pending self-scheduled check-backs."
   - `cancel_followup`: `{id: string}` required. Description = "Cancel a previously scheduled follow-up by ID."

2. **`SMART_AGENT_DIRECT_TOOLS` frozenset** (`core/tools.py:39`) — add all 3 names.

3. **`WORKER_TOOL_SCHEMAS`** (`core/tools.py:600–603`) — ensure all 3 are excluded from worker (worker doesn't manage Klaus's own check-backs).

4. **`_HANDLERS` dict** (`core/tools.py:995+`) — add 3 lambda entries: `lambda args: _handle_schedule_followup(**args)` etc.

5. **`_handle_<name>()` functions** — implement each:
   - `_handle_schedule_followup(when, note)`: try `datetime.fromisoformat(when)`; on failure, `from dateutil import parser; parser.parse(when)`. Convert to UTC ISO-8601 string. Call `FollowupStore.add(due_at, note, origin="klaus_self")`. Return `{"id": id, "due_at": due_at}`.
   - `_handle_list_followups()`: `FollowupStore.list_pending()` → strip internal fields (return only `id`, `due_at`, `note`, `defer_count`). Empty list if none.
   - `_handle_cancel_followup(id)`: `FollowupStore.cancel(id)` → idempotent. Return `{"ok": True}` (even if already cancelled — error-free UX per Claude's discretion).

**Verification at end of task:**
```bash
grep -n "schedule_followup\|list_followups\|cancel_followup" core/tools.py | wc -l
# Expect: at least 15 hits (some entries may register multiple times like in handler dict + function definition)
```

**Also update `prompts/smart_agent.md`** with a one-liner mentioning these three tools (per `canonical_refs` and Phase 15 D-07 pattern).

### `interfaces/web_server.py` — `/cron/autonomous-tick` route

**Copy `cron_reflect` (`web_server.py:334–355`) verbatim** as the template — it's the most recent and matches the shape best. Differences:

```python
@app.post("/cron/autonomous-tick")
async def cron_autonomous_tick(request: Request) -> JSONResponse:
    """Run one autonomous tick. Schedule: */20 7-21 * * * Asia/Jerusalem."""
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.autonomous as _auto
    try:
        now = datetime.now(ZoneInfo("Asia/Jerusalem"))
        # autonomous tick is async-friendly (Telegram bot send), but run blocking gather in executor.
        await _auto.run_autonomous_tick(_application.bot, now)
        _log_cron_run("autonomous-tick", ok=True)
    except Exception:
        _log_cron_run("autonomous-tick", ok=False)
        raise
    return JSONResponse(content={"ok": True})
```

**Open implementation question for planner:** is `run_autonomous_tick` sync or async? `_run_smart_loop` is **sync** (`core/main.py:283` calls it directly without await). `send_and_inject` is async (calls `bot.send_message`). Cleanest shape: `run_autonomous_tick` is `async def` and does `await loop.run_in_executor(None, ...)` for the sync `_run_smart_loop` call (mirrors `cron_reflect`'s executor offload for `run_reflection`).

Also: add `_CRON_MAX_STALENESS_HOURS["autonomous-tick"] = 1.0` in `core/heartbeat.py` per `canonical_refs`.

### `prompts/autonomous_triage.md` (NEW) — Layer 1 prompt

Key directives for the planner-side wording (final wording is Claude's discretion):

- **Voice:** First-person Klaus (informed by `docs/AGENT.md`). Mixed-register (D-03) — actionable if there's a concrete action, observational otherwise.
- **Latitude framing (D-02 / D-05 / AUTO-07):** Tell Klaus there is **no cadence limit**, **no `hours_since_contact` floor**, and that he should use judgment with knowledge of his own evolving self.
- **Self-state injection:** Render `current_focus`, `mood`, `journal_digest` (last 3 entries) inline. Critical per D-04.
- **Situation injection:** Render the situation_snapshot as bullet sections (calendar, overdue, unread, follow-ups, hours_since_contact, recent_journal already in self-state block, today's outreach_log topics).
- **Repeat-suppression as info, not block (D-06):** Phrase today's outreach log as "Topics I've already raised today: [...]. You can re-raise if a deadline brings it back, or for an EOD check-in."
- **Tick context (D-08):** `now: 19:40 Asia/Jerusalem, tick 39 of ~42, last tick at 19:20`.
- **JSON schema enforcement:** Klaus MUST output `{"should_act": bool, "reason": str, "draft": str (if should_act), "topic_key": str}`. State: "Output valid JSON and nothing else. Wrap in ```json fences only if required by the model."
- **Topic_key guidance:** Klaus picks the slug. Provide 4–5 example slugs (`overdue:reply-to-maya`, `silence:afternoon`, `gap:lunch-window`, `followup:<id>`, `pattern:eod-check`). Validation regex: `^[a-z]+(:[a-z0-9-]+)?$` — keep this in Claude's discretion but strongly recommend a slug-style.

### `prompts/autonomous.md` (NEW) — Layer 2 prompt

- **Voice & values:** Same persona as `prompts/smart_agent.md` and `prompts/proactive_alert.md`. SELF.md and self_state are auto-injected by `_run_smart_loop`'s render step — **do not duplicate** in this prompt.
- **Mode signal:** Tell Klaus he's composing an autonomous outreach: "You decided this needs to be said. Polish the draft to the moment, or refine it using your tools (recall, calendar lookup, get_self_status) if needed."
- **Brevity:** Mirror `prompts/proactive_alert.md`'s short-message bias.
- **Follow-up fire variant:** Include a "When called for a due follow-up" section explaining the `{"action": "send"|"defer"}` structured output. The followup item (`{id, due_at, note, defer_count}`) appears in the synthetic user message. If `defer_count >= 3`, instruct Klaus he MUST send (force-fire per D-14).
- **No second veto on triage-escalated sends (D-17):** Klaus does not get to refuse a triage-approved outreach. He polishes and sends. The follow-up defer is the only structured-output exception.

### `evals/tick_brain/` + `scripts/eval_tick_brain.py` (NEW)

**Fixture schema** (Claude's discretion; recommend single-file-per-fixture for diff-friendliness):

```
evals/tick_brain/
├── README.md            # how to label, how to add fixtures from tick_logs
├── fixtures/
│   ├── 0001-overdue-task.json
│   ├── 0002-quiet-evening.json
│   ├── 0003-due-followup.json
│   ├── 0004-long-silence.json
│   └── 0005-calendar-gap.json
```

Each fixture:
```json
{
  "id": "0001-overdue-task",
  "captured_at": "2026-05-21T14:20:00+03:00",
  "situation_snapshot": { "calendar": [...], "ticktick_overdue": [...], "unread_email_count": 3, "due_followups": [], "hours_since_contact": 4.5, "recent_journal": [...], "self_state": {...}, "today_outreach_log": [], "now_context": {...} },
  "trigger_type": "overdue" | "gap" | "silence" | "followup" | "quiet",
  "ground_truth": {"should_speak": true, "topic_key_pattern": "^overdue:.*"}
}
```

**`scripts/eval_tick_brain.py` shape:**
- CLI: `python scripts/eval_tick_brain.py [--model groq] [--fixtures evals/tick_brain/fixtures/]`
- For each fixture: render the autonomous_triage prompt against the snapshot, call `TickBrain.think()` (or directly via `LLMClient` to allow model substitution), compare predicted `should_act` to `ground_truth.should_speak`.
- Output table:
  ```
  === Overall ===
  Precision: 0.83 (10/12)   # predicted true that were correct
  Recall:    0.71 (10/14)   # ground-truth true that we caught
  F1:        0.77

  === Per-trigger-type ===
  | Trigger  | TP | FP | FN | Precision | Recall |
  |----------|----|----|----|-----------|--------|
  | overdue  |  4 |  0 |  1 |    1.00   |  0.80  |
  | gap      |  2 |  1 |  1 |    0.67   |  0.67  |
  | silence  |  1 |  1 |  1 |    0.50   |  0.50  |
  | followup |  3 |  0 |  0 |    1.00   |  1.00  |
  | quiet    |  N/A (ground_truth=False fixtures count toward Precision denominator) |
  ```
- Exit code: 0 if eval runs successfully (it's a measurement tool, not a gate).

**Seed 5 fixtures shipped with Phase 18:** plant one obvious-positive per trigger type (overdue, gap, silence, followup) and one obvious-negative (quiet evening, recent contact, no overdue, no due follow-ups).

### `docs/DEPLOYMENT.md` (INFRA-01)

Document **all 9 Cloud Scheduler jobs** in a single table:

| # | Job ID | Schedule (Asia/Jerusalem) | Endpoint | Phase |
|---|--------|---------------------------|----------|-------|
| 1 | five-fingers-morning | `30 10 * * 0,1,3,4` | `/cron/five-fingers-morning` | Earlier |
| 2 | five-fingers-evening | `<schedule>` | `/cron/five-fingers-evening` | Earlier |
| 3 | morning-briefing | `<schedule>` | `/cron/morning-briefing` | Earlier |
| 4 | morning-summary | `<schedule>` | `/cron/morning-summary` | Earlier |
| 5 | proactive-alerts | `30 21 * * *` | `/cron/proactive-alerts` | Earlier |
| 6 | heartbeat | `<schedule>` | `/cron/heartbeat` | Earlier |
| 7 | chat-ingest | `<schedule>` | `/cron/chat-ingest` | Phase 12/13 |
| 8 | reflect | `0 22 * * *` | `/cron/reflect` | Phase 17 |
| 9 | **autonomous-tick** | `*/20 7-21 * * *` | `/cron/autonomous-tick` | **Phase 18** |

Plus:
- **Groq secret** — `TICK_BRAIN_API_KEY` in GCP Secret Manager (already in from Phase 14 per INFRA-02), but document the access path and how to rotate.
- **Five Fingers job-id quirk** (from STATE.md) — note that morning + evening Five Fingers jobs share infrastructure and historically there's been a duplicate-job-id confusion. Document the canonical IDs.
- **`gcloud scheduler jobs create http` template** for the new autonomous-tick job (mirror Phase 17's reflect-job template).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cron triggering | Cloud Scheduler (GCP) | Cloud Run endpoint | Established pattern — all 8 existing crons live here |
| Request auth | Cloud Run endpoint (OIDC) | — | `_verify_cron_request` exists; copy |
| Situation gathering | `core/autonomous.py` (Layer 0) | Various data clients (calendar, ticktick, gmail) | Layer 0 is pure aggregation, no LLM |
| Judgment | `core/tick_brain.py` (Groq/Qwen3 + Gemini fallback) | — | Free model, already wired |
| Composition | `core/main.py:_run_smart_loop` (Gemini brain + Haiku fallback) | `core/tools.py` (full tool-loop) | D-20: synthetic chat turn = reuses persona/state injection |
| Persistence | Firestore (`followups`, `outreach_log`, `tick_logs`) | — | Matches `JournalStore`/`SelfStateStore` patterns |
| Outbound | Telegram via `send_and_inject(..., inject_into_conversation=True)` | Conversation history (Firestore) | D-18: inject=True for natural follow-up |
| Eval | Local script + JSON fixtures | Firestore `tick_logs` (source for retroactive labeling) | D-21: bootstrap from real data |

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `google-cloud-firestore` | (pinned, Phase 1) | Persistence | All other stores use it |
| `python-telegram-bot` | (pinned) | Telegram send | `send_and_inject` already wraps it |
| `fastapi` + `uvicorn` | (pinned) | Cron endpoints | All `/cron/*` routes |
| `dateutil` | already in `requirements.txt` | Natural-language datetime parse (D-12) | `[VERIFIED: spot-check of requirements.txt during this research is not done — planner should grep]` |

**Verification ask for the planner:** confirm `python-dateutil` is in `requirements.txt`. If not, add it (it's the most stable NL date parser in Python). `dateparser` is heavier and not needed for D-12's narrow "ISO first, NL fallback" pattern.

### Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NL datetime parsing | Regex + manual day-of-week logic | `dateutil.parser.parse()` | D-12 — handles "tomorrow 3pm", "next monday", ISO, etc. |
| JSON parse robustness | Custom code-fence stripping | Reuse `TickBrain._parse_response` shape | Already strips ```json fences; safe-mode return on parse failure |
| Cron auth | Custom token check | `_verify_cron_request` | OIDC + bearer validation already in place |
| LLM cost tracking | Manual usage calc | `LLMClient.chat(..., purpose=...)` | Phase 14's `LLMUsageStore` writes automatically |
| Telegram send + history | `bot.send_message(...)` + manual history append | `send_and_inject(bot, msg, inject_into_conversation=True)` | D-18 |
| Per-source error isolation | `try/except` around the whole gather | Per-source `try/except` like `_gather_day` | D-11 needs empty-signals detection; can't have one failure mask others |
| LLM fallback chain | Custom retry | Existing `LLMClient` Gemini → Haiku via `core/main.py:260–291` | Layer 2 inherits through `_run_smart_loop` |

## Common Pitfalls

### Pitfall 1: 15-edit-point tool registration with a missed site
**What goes wrong:** Klaus calls `schedule_followup` but gets "tool not found" because `SMART_AGENT_DIRECT_TOOLS` was missed (or worker handles it because `WORKER_TOOL_SCHEMAS` exclusion was missed).
**Why it happens:** 5 separate locations in `core/tools.py` × 3 new tools = 15 edits. Mechanical; high miss rate.
**How to avoid:** Treat as a single atomic task with an explicit per-site checklist. End the task with `grep -n "schedule_followup" core/tools.py` (expect 5+ hits) and equivalent for the other two.
**Warning signs:** A direct tool that "doesn't exist" at chat time, or worker invoking a tool it shouldn't have.

### Pitfall 2: Layer 2 synthetic-message integration breaking conversation history
**What goes wrong:** Layer 2's synthetic user message gets appended to the **real** user's conversation history, polluting it with Layer-1-generated text the user never sent.
**Why it happens:** `_run_smart_loop` callers in `core/main.py:283` append to history via `self.conversation_manager.append(user_id, "user", user_message)` (line 279). The autonomous path must **NOT** append the synthetic message.
**How to avoid:** Do NOT route through `AgentOrchestrator.handle_message`. Call `_run_smart_loop` **directly** with a freshly-built messages list `[{"role": "user", "content": <synthetic>}]`. Only the **final assistant text** goes into history (via `send_and_inject(..., inject_into_conversation=True)` per D-18). Verify by reading `core/main.py:278–289` before implementing.
**Warning signs:** User sees their own conversation history showing user-role turns they didn't write.

### Pitfall 3: `outreach_log` write before send-success leads to false-positive dedup
**What goes wrong:** Layer 2 composes, write to `outreach_log` happens, then `send_and_inject` raises (Telegram rate limit, network blip). Next tick sees the topic as "already raised" and suppresses correctly.
**Why it happens:** Natural temptation to write-then-send for atomicity.
**How to avoid:** D-10 is explicit: log on success only. Order: `final = ...` → `await send_and_inject(...)` → on success `OutreachLogStore.append(...)`. Mirror `proactive_alerts._mark_processed(alert_sent=True)`.
**Warning signs:** A topic the user expected to see proactively didn't surface, and `outreach_log` has it.

### Pitfall 4: Tick-brain JSON parse failure cascading to compose
**What goes wrong:** Qwen3 returns valid-looking text but no `topic_key` field. `_parse_response` doesn't validate `topic_key`. Compose runs, sends, then `OutreachLogStore.append({topic_key: ""})` writes a blank key, defeating dedup.
**How to avoid:** If `topic_key` is empty/missing after parse, **synthesize a fallback** in `core/autonomous.py` based on the trigger type detected at Layer 0 (`overdue:auto-<idx>`, `silence:tick-<N>`, etc.). Never let an empty `topic_key` reach the outreach log.
**Warning signs:** Multiple sends with `topic_key=""` in `outreach_log/{date}`.

### Pitfall 5: Cron staleness check missing the new job
**What goes wrong:** Cloud Scheduler stops firing `/cron/autonomous-tick` (deploy break, Scheduler quota exceeded), but `core/heartbeat.py` doesn't know to flag it.
**How to avoid:** Add `"autonomous-tick": 1.0` to `_CRON_MAX_STALENESS_HOURS` per `canonical_refs`. Threshold = 1.0 hours (since the job fires every 20 minutes, an hour-old last-run means 3 missed ticks — clear alert signal).
**Warning signs:** Quiet Klaus + no heartbeat alert = staleness check is wrong.

### Pitfall 6: Defer infinite loop on a follow-up with `defer_count >= 3`
**What goes wrong:** Layer 2 ignores the "force-fire" instruction (D-14) and returns `{"action": "defer"}` repeatedly for a follow-up at `defer_count=3, 4, 5...`.
**How to avoid:** The **handler**, not the prompt, enforces this. After parsing Layer 2's structured output, if `action == "defer"` AND `defer_count >= 3`, override to send. Prompt's instruction is belt-and-suspenders; handler is the truth.
**Warning signs:** A follow-up with `defer_count=7` still in `pending`.

### Pitfall 7: Five Fingers job-id collision quirk (INFRA-01)
**What goes wrong:** Creating a new scheduler job named `five-fingers` collides with the existing one or vice-versa; new `autonomous-tick` job name must NOT conflict with any historical/staging job in the project.
**How to avoid:** Document in `DEPLOYMENT.md` per INFRA-01. Recommend prefixing with environment if needed, but the production naming convention is plain (`autonomous-tick`).
**Warning signs:** `gcloud scheduler jobs create` fails with "already exists" on first deploy.

### Pitfall 8: Eval scoring against an unreliable model
**What goes wrong:** `eval_tick_brain.py` runs against Groq/Qwen3 but Qwen3 occasionally returns parse-failures; precision/recall numbers include parse-failures as "predicted False," skewing recall downward.
**How to avoid:** In the eval scorer, treat `parse_failure` and `llm_error` (the safe-mode returns) as a third bucket "errored" and report them separately. They are NOT predicted-false. Eval output:
```
Precision: 0.83  Recall: 0.71  F1: 0.77  (Errored: 2/16 fixtures)
```
**Warning signs:** Recall mysteriously drops when changing models that have different parse-failure rates.

## Runtime State Inventory

This is a greenfield-additive phase (new files + extension of an existing function). Not a rename/refactor. Nothing existing to migrate. Skip per Step 2.5 guidance — **None — verified by:** all new collections (`followups`, `outreach_log`, `tick_logs`) and all new files (`core/autonomous.py`, two prompts, two evals, three handlers). Existing collections and code remain compatible.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Cloud Run | All cron endpoints | ✓ (Phase 1) | — | — |
| Cloud Scheduler | `/cron/autonomous-tick` trigger | ✓ (Phase 1) | — | manual `curl` for dev testing |
| Firestore | All 3 stores | ✓ (Phase 1) | — | — |
| Groq API (TICK_BRAIN_API_KEY) | Layer 1 | ✓ (Phase 14 / INFRA-02) | — | Gemini fallback in `TickBrain` |
| Gemini API (SMART_AGENT) | Layer 2 primary | ✓ (Phase 14) | — | Claude Haiku via `SMART_AGENT_FALLBACK_*` |
| Claude Haiku (SMART_AGENT_FALLBACK) | Layer 2 fallback | ✓ (Phase 17) | — | tick-brain `draft` per D-19 |
| Telegram Bot API | Outbound | ✓ (Phase 1) | — | — |
| `python-dateutil` | NL datetime parse | **NEEDS VERIFICATION** | — | ISO-only acceptance + reject NL with clear error |

**Action for planner:** `grep -i dateutil requirements.txt` in Wave 1 Task 1. If absent, add to `requirements.txt`.

## Validation Architecture

Test framework verification:

| Property | Value |
|----------|-------|
| Framework | pytest (existing, Phase 14 established) |
| Config file | `pyproject.toml` or `pytest.ini` (check existing — Phase 17 used pytest) |
| Quick run command | `pytest tests/test_autonomous.py -x` |
| Full suite command | `pytest tests/` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| AUTO-01 | 3-layer pipeline returns correct decision trail for: empty-signal skip, triage-no, triage-yes-compose-yes, triage-yes-compose-fail-fallback | unit (Layer 0 + orchestrator with mocked TickBrain + mocked `_run_smart_loop`) | `pytest tests/test_autonomous.py::test_run_autonomous_tick_decision_trail -x` | ❌ Wave 0 |
| AUTO-02 | `gather_situation()` aggregates from all 8 sources with per-source error isolation (one failure → others still populate) | unit (each gather sub-call mocked, raise on one, assert others present) | `pytest tests/test_autonomous.py::test_gather_situation_isolation -x` | ❌ Wave 0 |
| AUTO-03 | After successful send, `OutreachLogStore.append` called with `{topic_key, time, draft, final}`; tick-brain prompt for the next tick includes the topic in "raised today" list | unit (mock store + assert append called only on send-success path) | `pytest tests/test_autonomous.py::test_outreach_log_on_success_only -x` | ❌ Wave 0 |
| AUTO-04 | `FollowupStore.add` writes the doc; `list_due(now)` returns only `due_at <= now AND status=='pending'`; `mark_done`, `cancel`, `defer` transition status/defer_count correctly | unit (in-memory Firestore emulator or mock) | `pytest tests/test_firestore_db.py::test_followup_store -x` | ❌ Wave 0 (extends existing file) |
| AUTO-05 | All 3 follow-up tools registered in TOOL_SCHEMAS, SMART_AGENT_DIRECT_TOOLS, NOT in WORKER_TOOL_SCHEMAS, dispatch correctly through `_HANDLERS`; `_handle_schedule_followup` parses ISO and NL `when`; `_handle_cancel_followup` is idempotent | unit (existing tools test patterns from Phase 15) | `pytest tests/test_tools.py::test_followup_tools -x` | ❌ Wave 0 (extends existing file) |
| AUTO-06 | `/cron/autonomous-tick` returns 200 on auth-valid OIDC + invokes `run_autonomous_tick`; returns 401 on missing/bad bearer; `_log_cron_run("autonomous-tick", ok=<bool>)` called | integration (FastAPI TestClient + auth header mock) | `pytest tests/test_web_server.py::test_cron_autonomous_tick -x` | ❌ Wave 0 (extends existing file) |
| AUTO-07 | Both prompt files exist; contain wide-latitude language; JSON-output spec on triage; topic_key example slugs present | unit (load file, assert key phrases) | `pytest tests/test_prompts.py::test_autonomous_prompts -x` | ❌ Wave 0 |
| AUTO-08 | `evals/tick_brain/fixtures/` contains ≥5 fixture JSON files; each has `situation_snapshot`, `trigger_type`, `ground_truth.should_speak` | unit (load fixtures, schema validate) | `pytest tests/test_evals.py::test_fixture_schema -x` | ❌ Wave 0 |
| AUTO-09 | `scripts/eval_tick_brain.py` exits 0 on a 5-fixture run, outputs precision/recall/F1 line + per-trigger-type table; treats safe-mode returns as "errored" not "predicted False" | integration (subprocess invoke, parse stdout) | `pytest tests/test_eval_script.py::test_eval_runs -x` | ❌ Wave 0 |
| INFRA-01 | `docs/DEPLOYMENT.md` lists all 9 cron jobs with schedules and endpoints; documents Groq secret; documents Five Fingers job-id quirk | docs-grep (assert key strings in DEPLOYMENT.md) | `pytest tests/test_docs.py::test_deployment_completeness -x` | ❌ Wave 0 |
| SC-1 | Plant overdue TickTick task → `/cron/autonomous-tick` → Klaus sends Telegram | live-tick smoke (manual or scripted against staging) | manual smoke procedure documented in PR description | n/a |
| SC-2 | Trigger immediately again → Klaus stays silent | live-tick smoke | manual smoke procedure documented in PR description | n/a |
| SC-3 | Quiet situation → silent + near-zero cost (Layer-0 gate prevents tick-brain call) | unit + live smoke | `pytest tests/test_autonomous.py::test_quiet_situation_skips_tick_brain -x` AND `LLMUsageStore.get(today).cost` increment check in live smoke | partial (unit covers Layer-0 gate logic; live smoke checks cost) |
| SC-4 | `schedule_followup` in chat → tick after due time → follow-up fires | live-tick smoke | manual smoke documented; also `pytest tests/test_autonomous.py::test_followup_fire_path -x` for the unit | partial |
| SC-5 | `python scripts/eval_tick_brain.py` runs, scores, prints report | integration (covered in AUTO-09) | (same as AUTO-09) | covered |

### State Transitions

- **followups doc lifecycle:** `add()` → `status="pending", defer_count=0` → `defer()` → `due_at += 1h, defer_count++` (loop until 3) → `mark_done()` → `status="done"`. Alternate terminal: `cancel()` → `status="cancelled"`.
- **outreach_log doc lifecycle:** doc-per-date; `entries[]` appended only on send-success. New day = new doc (D-09 daily reset).
- **tick_logs doc lifecycle:** one doc per tick; written before decision is final (snapshot recorded even on empty-signal skip).
- **`defer_count >= 3` force-fire:** handler-enforced (Pitfall 6).

### Boundary Conditions

- **Empty Layer-0 signals:** `gather_situation()` returns `empty=True` → tick-brain not called → `tick_logs` written with `decision="skipped_empty"` → no Telegram, no `outreach_log` write. (SC-3)
- **`defer_count` exactly 3:** next due tick force-fires (>=, not >).
- **Tick-brain `topic_key=""`:** handler synthesizes fallback from trigger type (Pitfall 4).
- **Same `topic_key` already in today's `outreach_log`:** triage receives it as info — judgment may still re-raise per D-06.
- **Different `topic_key`, same underlying issue:** no dedup (informative-not-blocking accepts this). Eval over time tells us if this is acceptable.
- **Layer 2 LLM total failure (both Gemini + Claude Haiku):** fall back to tick-brain's `draft` per D-19, send it, log normally.
- **Cron fires but bot is down:** `_log_cron_run("autonomous-tick", ok=False)` writes; heartbeat staleness check picks it up.
- **`when` parameter unparseable in `schedule_followup`:** tool returns `{"error": "could_not_parse_when"}` (or raises a structured tool error) — Klaus can retry with a different format.

### Sampling Rate
- **Per task commit:** `pytest tests/test_autonomous.py tests/test_firestore_db.py tests/test_tools.py -x` (~5s)
- **Per wave merge:** `pytest tests/` (full suite)
- **Phase gate:** Full suite green + live smoke SC-1..SC-5 manually verified before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `tests/test_autonomous.py` — new file for AUTO-01, AUTO-02, AUTO-03, SC-3-unit, SC-4-unit, Pitfall-2 (synthetic message doesn't pollute history), Pitfall-3 (outreach-log-on-success-only), Pitfall-4 (topic_key fallback), Pitfall-6 (force-fire at defer_count=3)
- [ ] `tests/test_firestore_db.py` — extend with `FollowupStore` + `OutreachLogStore` test classes (AUTO-04)
- [ ] `tests/test_tools.py` — extend with follow-up-tools test class (AUTO-05) including ISO/NL `when` parsing and idempotent cancel
- [ ] `tests/test_web_server.py` — extend with `/cron/autonomous-tick` route tests (AUTO-06)
- [ ] `tests/test_prompts.py` — new file or extend existing prompt tests (AUTO-07)
- [ ] `tests/test_evals.py` — new file for fixture schema validation (AUTO-08)
- [ ] `tests/test_eval_script.py` — new file for eval runner subprocess test (AUTO-09)
- [ ] `tests/test_docs.py` — extend with DEPLOYMENT.md completeness assertion (INFRA-01)
- [ ] Shared fixture: in-memory `FollowupStore` mock that mirrors the real interface

## Wave Suggestion

**Wave 1 — Data, tools, prompts, eval-seed (mostly parallel-safe):**
- Task 1.A: `FollowupStore` + `OutreachLogStore` in `memory/firestore_db.py` + tests (`tests/test_firestore_db.py` extension).
- Task 1.B: 3 follow-up tools — 15 edit points in `core/tools.py` + tests (`tests/test_tools.py` extension) + smart_agent.md one-liner. **Atomic, single task.** Depends on Task 1.A (handlers call FollowupStore).
- Task 1.C: `prompts/autonomous_triage.md` + `prompts/autonomous.md` + prompt-presence tests.
- Task 1.D: 5 seed fixtures in `evals/tick_brain/fixtures/` + `evals/tick_brain/README.md` + schema-validation test.
- Task 1.E (optional, can defer to Wave 3): add `python-dateutil` to `requirements.txt` if missing.

**Wave 2 — Orchestration, cron, tick-brain extension (sequential — Wave 1 dependency):**
- Task 2.A: `core/tick_brain.py` — add `system_override` kwarg to `think()`; extend `_parse_response` to pass through `topic_key`. Unit tests.
- Task 2.B: `core/autonomous.py` — full module (`gather_situation`, `run_autonomous_tick`, `_compose_layer2`, `_compose_followup`). Heavy test coverage per the Validation Architecture table.
- Task 2.C: `interfaces/web_server.py` — new `/cron/autonomous-tick` route + heartbeat staleness entry. Route test.

**Wave 3 — Eval runner + docs:**
- Task 3.A: `scripts/eval_tick_brain.py` — full runner with overall + per-trigger-type output. Subprocess test.
- Task 3.B: `docs/DEPLOYMENT.md` — INFRA-01 nine-cron table + Groq secret + Five Fingers job-id quirk. Docs-grep test.
- Task 3.C (validation): live-tick smoke against staging (SC-1..SC-5). Manual; documented as PR-description checklist.

**INFRA-01 floats** — purely docs; can land in any wave but Wave 3 is natural because the route doesn't exist until Wave 2.

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | **15-edit-point tool registration miss** (a site forgotten) | HIGH (mechanical) | MEDIUM (tool unusable for one path) | Atomic single task with end-of-task `grep` verification; Wave 1 Task 1.B's tests assert presence in each of the 5 sites |
| R2 | **Layer-2 synthetic message pollutes user conversation history** | MEDIUM (easy mistake) | HIGH (UX bug, user confusion) | Pitfall-2 documented; test asserts `conversation_manager.append("user", <synthetic>)` is NOT called on autonomous path. Direct `_run_smart_loop` call required, not via `handle_message` |
| R3 | **`_run_smart_loop` synthetic-message integration risk** (sync/async mismatch) | MEDIUM | MEDIUM (route hangs or errors) | Verify shape during Task 2.B; run `_run_smart_loop` in executor (mirrors `cron_reflect`). Spot-check during research confirmed signature `(messages, smart_system, worker_system)` is sync |
| R4 | **Cron staleness threshold value too aggressive** | LOW | LOW (false-positive heartbeat alert) | 1.0h is conservative (3 missed 20-min ticks). Tune if alert-noise. Document choice in code comment |
| R5 | **`tick_logs` collection grows unboundedly** | HIGH over time | LOW within 1 year | Document as known future cleanup. ~15k docs/year is acceptable for Firestore. TTL deferred per Claude's discretion |
| R6 | **Five Fingers job-id collision on `gcloud scheduler jobs create autonomous-tick`** | LOW (different name) | MEDIUM (deploy blocked) | INFRA-01 documents canonical names; pre-flight `gcloud scheduler jobs list` in deployment doc |
| R7 | **Repeat-suppression too lax (D-06 informative-not-blocking)** → Klaus spams a topic | LOW–MEDIUM | LOW (UX annoyance) | Eval surfaces this over weeks. If observed, tighten triage-prompt language toward "raise rarely once raised today" without making code-level a hard block |
| R8 | **Eval bootstrap insufficient** (5 seeds → 20+ over a week assumes consistent live use) | MEDIUM | MEDIUM (AUTO-08 stays "pending" longer than expected) | Document the labeling workflow in `evals/tick_brain/README.md`; provide a tiny labeling helper script if time allows; explicitly call out in the PR that 5 seeds is the Phase-18 ship bar and 20–30 is a follow-up over the next two weeks |
| R9 | **Defer infinite loop** (Pitfall 6) | LOW | MEDIUM (a single follow-up never fires) | Handler enforces force-fire at `defer_count >= 3`; covered in Validation table |
| R10 | **`outreach_log` write before send-success** (Pitfall 3) → false-positive dedup | MEDIUM | MEDIUM (silent failure mode) | D-10 explicit; test asserts append only after `send_and_inject` returns successfully |

## Sources

### Primary (HIGH confidence)
- `.planning/phases/18-autonomous-engine/18-CONTEXT.md` — exhaustive D-01..D-22 with file:line references
- `.planning/REQUIREMENTS.md` — AUTO-01..09, INFRA-01 acceptance criteria
- `.planning/ROADMAP.md` Phase 18 section — key files + 5 success criteria
- Spot-checked: `core/main.py:236–289` (`_run_smart_loop` signature + render step shape confirmed)
- Spot-checked: `core/tick_brain.py:30–179` (`_TICK_SYSTEM_PROMPT`, `think()`, `_parse_response` shapes confirmed)
- Spot-checked: `interfaces/web_server.py:273–355` (`_log_cron_run`, `cron_reflect` template confirmed)

### Secondary (MEDIUM confidence, derived from prior-phase context references)
- Phase 15 D-07 — 5-site direct-tool registration pattern (`canonical_refs`)
- Phase 16 D-04 — per-message smart-only injection pattern
- Phase 17 D-13 — minimal-fallback pattern (analog for D-19)
- Phase 17 D-14 — journal_digest auto-injection (Layer 2 gets it free)

### Tertiary (LOW confidence — planner should verify in Wave 1)
- `python-dateutil` presence in `requirements.txt` — spot-check not performed in this research
- `_CRON_MAX_STALENESS_HOURS` exact dict shape in `core/heartbeat.py` — assumed dict-of-job-id→hours

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `python-dateutil` is available in the project | Standard Stack | LOW — Wave 1 grep-check; if absent, add to `requirements.txt` |
| A2 | `_CRON_MAX_STALENESS_HOURS` is the correct constant name in `core/heartbeat.py` (from `canonical_refs`) | Implementation Approach (cron) | LOW — `canonical_refs` is from CONTEXT.md which is authoritative |
| A3 | Firestore has no built-in TTL config in our setup (tick_logs retention deferred) | Don't Hand-Roll / Risks | LOW — confirmable in Wave 1; Firestore TTL policies exist but aren't currently used in this project |
| A4 | `TickBrain.think()` can be extended with `system_override` kwarg without breaking heartbeat caller | tick_brain.py change | LOW — default `None` preserves heartbeat's current behavior; spot-check of `core/heartbeat.py:679` would confirm |
| A5 | Layer-2 follow-up structured output `{"action": "send"|"defer"}` can be JSON-parsed from the smart_agent loop's final text | core/autonomous.py | MEDIUM — the smart_agent normally returns natural language; planner may need to add a directive in `prompts/autonomous.md` for the follow-up branch to wrap structured output in a fenced JSON block, then parse that. Alternate: terminate Layer 2 early with a structured-output-only call. **Flag for discussion during planning if a cleaner path emerges.** |

## Open Questions

1. **Should the autonomous tick also write to Pinecone for long-term memory?**
   - What we know: Phase 17 reflection upserts journal entries with `kind="self"`. Autonomous sends are also Klaus's "self" actions.
   - What's unclear: do we want a `kind="outreach"` upsert per send? Pro: searchable history. Con: adds cost, expands scope.
   - Recommendation: **Out of scope for Phase 18.** Outreach is in conversation history (via `inject=True`) and in `outreach_log` — sufficient for the eval and the headline behavior. Pinecone outreach indexing is a future enhancement.

2. **Should `eval_tick_brain.py` support a `--model` flag for A/B testing tick-brain models?**
   - What we know: D-22 calls for precision/recall/F1 + per-trigger breakdown. Future work will compare models.
   - What's unclear: scope of `--model`; does it accept just Groq-model-name strings, or does it route to different backends?
   - Recommendation: Ship Phase 18 with the default model. Add `--model <name>` (Groq backend only — same env-var-config path as `TickBrain`) if time permits in Wave 3. Otherwise defer.

3. **Does Klaus's chat persona need a sentence about "I may speak to you spontaneously"?**
   - What we know: `prompts/smart_agent.md` is updated per the `canonical_refs` list to mention `schedule_followup`/`list_followups`/`cancel_followup`.
   - What's unclear: should it also tell the user-facing chat persona that proactive outreach exists? Or is the conversation-history inject (D-18) enough context?
   - Recommendation: One-liner addition: "You may also reach out proactively when judgment warrants it; your proactive messages appear in this conversation." Helps Klaus self-consistency when the user follows up on a proactive send.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libs already in project
- Architecture: HIGH — CONTEXT.md D-20 spot-confirmed; pattern is composition of existing parts
- Pitfalls: HIGH — derived directly from D-10/D-14/D-18 and prior-phase patterns
- Eval design: MEDIUM — fixture schema is Claude's discretion; sketched but not battle-tested

**Research date:** 2026-05-20
**Valid until:** 2026-06-20 (30 days — phase intends to start within days)
