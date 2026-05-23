# Phase 18: The Autonomous Engine — Pattern Map

**Mapped:** 2026-05-20
**Files analyzed:** 14 (5 NEW, 6 MODIFIED, 1 VERIFY, 2 NEW evals)
**Analogs found:** 13 / 14 (one greenfield: eval fixtures schema is Claude's discretion)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/autonomous.py` (NEW) | orchestrator | cron → gather → LLM judge → LLM compose → send | `core/proactive_alerts.py` + `core/reflection.py` | exact (split across 2) |
| `prompts/autonomous_triage.md` (NEW) | prompt (Layer 1) | LLM system prompt | `core/tick_brain.py:30` `_TICK_SYSTEM_PROMPT` | exact (same purpose) |
| `prompts/autonomous.md` (NEW) | prompt (Layer 2) | LLM system prompt | `prompts/proactive_alert.md` + `prompts/reflection.md` | role-match (tone + voice) |
| `evals/tick_brain/fixtures/*.json` (NEW) | eval data | static input fixtures | none (greenfield) | none |
| `evals/tick_brain/README.md` (NEW) | doc | workflow doc | none (greenfield) | none |
| `scripts/eval_tick_brain.py` (NEW) | eval runner | batch read → LLM call → metrics print | `core/reflection.py:_cli()` (arg-parse + dry-run shape) | partial |
| `core/tick_brain.py` (MOD) | LLM client | extend think() signature + parser | self (lines 101, 158) | self-analog |
| `memory/firestore_db.py` (MOD) | data store | Firestore CRUD | `JournalStore:671` + `SelfStateStore:601` | exact |
| `core/tools.py` (MOD) | tool registration | 15-edit-point mechanical add | `remember`/`recall`/`get_self_status` registration sites | exact (self-analog) |
| `interfaces/web_server.py` (MOD) | cron route | OIDC + run + ledger | `cron_reflect:334` | exact (most recent + closest shape) |
| `core/heartbeat.py` (MOD) | constants dict | single-line add | `_CRON_MAX_STALENESS_HOURS:108` (reflect entry at :113) | exact (self-analog) |
| `prompts/smart_agent.md` (MOD) | prompt | small addition | `prompts/smart_agent.md` existing tool-mention blocks (lines 54–94) | self-analog |
| `docs/DEPLOYMENT.md` (MOD) | doc | cron table + secret + quirk | DEPLOYMENT.md §14c (`klaus-proactive-alerts`:613) | self-analog |
| `requirements.txt` (VERIFY) | config | pinned dep | requirements.txt | n/a — verify `python-dateutil` present |

---

## Pattern Assignments

### `core/autonomous.py` (NEW) — orchestrator, multi-stage pipeline

**Primary analog (cron + dedup + compose + send):** `core/proactive_alerts.py`
**Secondary analog (best-effort gather):** `core/reflection.py:_gather_day`

#### A. Module header + imports
**Source:** `core/proactive_alerts.py:1-24`
```python
"""Proactive evening alerts — weather conflicts, overloaded days, and travel time checks.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/proactive-alerts  (21:30 daily, Asia/Jerusalem)

Local smoke test:
  python -m core.proactive_alerts --dry-run --date 2026-05-14
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Bot

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")
```
**Deviation for Phase 18:** Schedule is `*/20 7-21 * * *`; add `MAX_TICKS_PER_DAY = 42` constant for D-08 tick-index context.

#### B. Best-effort per-source gather (Layer 0 — `gather_situation()`)
**Source:** `core/reflection.py:123-193` (`_gather_day`)
```python
def _gather_day(target_date: str) -> dict:
    """Gather today's raw metrics from all sources, each in its own try/except.

    A failed source is logged as a warning and omitted — the run continues.
    """
    gathered: dict = {"message_count": 0, "cost_usd": 0.0, "conversation": [], ...}

    # (a) LLM usage: message count + cost
    try:
        from memory.firestore_db import LLMUsageStore
        usage = LLMUsageStore(project_id=..., database=...).summary("today")
        gathered["message_count"] = int(usage.get("smart_calls", 0))
        gathered["cost_usd"] = float(usage.get("total_cost_usd", 0.0))
    except Exception:
        logger.warning("reflection: LLM usage gather failed", exc_info=True)

    # (b) Conversation history (best-effort; 6h session window may return [])
    try:
        ...
    except Exception:
        logger.warning("reflection: conversation history gather failed", exc_info=True)
    # (c), (d), (e) follow the same shape — each isolated.
    return gathered
```
**Deviation for Phase 18:**
- 8 gather sources instead of 5: calendar, ticktick_overdue, unread_email_count, due_followups, hours_since_contact, recent_journal_digest, today_outreach_log, current_self_state.
- Add salient-signals check at bottom returning `{"empty": True, "raw_signals": {...}}` per D-11 (Layer-0 gate). This is the cost-control mechanism — `_gather_day` has no equivalent.
- Add `now_context` block `{"now_iso": now.isoformat(), "now_local": ..., "tick_index": N, "tick_total": 42, "last_tick_at": ...}` per D-08.

#### C. Dedup gate (read today's outreach_log topics)
**Source:** `core/proactive_alerts.py:147-155` (`_already_sent`)
```python
def _already_sent(target_date: str) -> bool:
    """Return True if we already processed alerts for this date."""
    try:
        client = _make_firestore_client()
        doc = client.collection("proactive_alerts").document(target_date).get()
        return doc.exists
    except Exception:
        logger.warning("Proactive alerts: dedup check failed", exc_info=True)
        return False
```
**Deviation for Phase 18:** Per D-06 (informative-not-blocking), do NOT short-circuit. Instead, `OutreachLogStore.topics_today(date)` returns the list and it is **passed into the triage prompt** so tick-brain can compare semantically. The proactive-alerts pattern is blocking; Phase 18 is informative.

#### D. Telegram send + dedup mark (D-10 log on success only)
**Source:** `core/proactive_alerts.py:124-140`
```python
if not weather_alerts and not overload_alert and not travel_alerts:
    logger.info("Proactive alerts: no issues found for %s", target_date)
    _mark_processed(target_date, alert_sent=False)
    return

alerts_context = {"target_date": target_date, "weather_alerts": ..., ...}
message = _compose_alert(alerts_context)

from core.scheduled_message import send_and_inject
await send_and_inject(bot, message, inject_into_conversation=False)
_mark_processed(target_date, alert_sent=True)
```
**Deviation for Phase 18:**
- `inject_into_conversation=True` per D-18 (diverges — proactive uses False).
- Order is `await send_and_inject(...)` **then** `OutreachLogStore.append(...)` — only on send success per D-10.

#### E. Layer 2 = synthetic chat turn via `_run_smart_loop`
**Source:** `core/main.py:283-285`
```python
response_text = self._run_smart_loop(
    messages, smart_system, worker_system
)
```
**Deviation for Phase 18 (D-20 / Pitfall 2):**
- Build `messages = [{"role": "user", "content": <situation_summary + tick_brain_draft>}]` — a **freshly-built** single-message list. Do NOT route through `AgentOrchestrator.handle_message` (that would `conversation_manager.append("user", synthetic)` and pollute history per Pitfall 2 in RESEARCH.md).
- `smart_system` = `prompts/autonomous.md` rendered with same per-message machinery from `core/main.py:236-275` (the autonomous orchestrator must replicate the SELF.md / self_state / journal_digest / today_date replace block, OR — cleaner — instantiate an `AgentOrchestrator` and call `._run_smart_loop` directly with a manually-built smart_system. The planner should pick.)
- `_run_smart_loop` is sync; from the async cron route, wrap with `loop.run_in_executor(None, ...)` exactly like `cron_reflect:349-350`.

#### F. LLM fallback chain (Layer 2 → tick-brain draft per D-19)
**Source:** `core/reflection.py:_brain_reflect:275-345` (two-step LLM fallback)
```python
# Brain call
try:
    client = LLMClient(backend=SMART_AGENT_BACKEND, model=SMART_AGENT_MODEL, ...)
    response = client.chat(messages, system=system_prompt, purpose="reflect")
    text = (response.get("text") or "").strip()
    if text:
        parsed = _parse_reflection_json(text)
        if parsed is not None:
            return parsed
except Exception:
    logger.warning("reflection: brain LLM call failed; trying fallback", exc_info=True)

# Fallback brain call (D-13)
try:
    client_fb = LLMClient(backend=SMART_AGENT_FALLBACK_BACKEND, ...)
    ...
    if parsed_fb is not None:
        return parsed_fb
except Exception:
    logger.warning("reflection: fallback LLM call failed", exc_info=True)

return None  # both failed
```
**Deviation for Phase 18 (D-19):** When `_run_smart_loop` returns empty/raises (already-internal Gemini → Haiku chain exhausted at `core/main.py:319-345`), fall back to `tick_brain_result["draft"]` and send that. Mirrors the minimal-fallback shape from `_minimal_fallback_entry:252-268`.

#### G. CLI smoke test
**Source:** `core/proactive_alerts.py:399-470` (especially the `--dry-run` branch + asyncio setup)
**Deviation:** Add `--situation-file <path.json>` to load a fixture and run a single tick against it (lets eval reuse same code path).

---

### `core/tick_brain.py` (MODIFIED) — extend `think()` and `_parse_response`

**Analog:** Self — lines 101 and 158.

#### Current `think()` signature
**Source:** `core/tick_brain.py:101-127`
```python
def think(self, prompt: str,
          tools: list[dict] | None = None) -> dict:
    """Run a judgment pass over the given prompt."""
    messages = [{"role": "user", "content": prompt}]

    response = None
    try:
        response = self._client.chat(
            messages,
            system=_TICK_SYSTEM_PROMPT,
            tools=tools,
            purpose="tick",
        )
    except LLMError as exc:
        ...
```
**Phase 18 change (RESEARCH §tick_brain Option (a) — recommended):**
Add `system_override: str | None = None` kwarg. Replace `system=_TICK_SYSTEM_PROMPT` with `system=(system_override or _TICK_SYSTEM_PROMPT)`. Also add `purpose="tick"` → `purpose="tick_autonomous"` when override active (cost metering D-04). Heartbeat caller (`core/heartbeat.py:707`) continues passing nothing → backward-compatible.

#### Current `_parse_response`
**Source:** `core/tick_brain.py:158-186`
```python
@staticmethod
def _parse_response(text: str) -> dict:
    """Parse the LLM's JSON response. Returns safe mode on any parse failure."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("tick-brain: JSON parse failure; safe mode. Raw: %.200s", text)
        return {"should_act": False, "reason": "parse_failure"}

    if not isinstance(data, dict) or "should_act" not in data:
        return {"should_act": False, "reason": "parse_failure"}

    result = {
        "should_act": bool(data.get("should_act", False)),
        "reason":     str(data.get("reason", "")),
    }
    if "draft" in data and data["draft"]:
        result["draft"] = str(data["draft"])
    return result
```
**Phase 18 change (D-07):** After existing draft block, add:
```python
if "topic_key" in data and data["topic_key"]:
    result["topic_key"] = str(data["topic_key"])
```
Safe-mode return unchanged (no `topic_key` key on parse failure — Pitfall 4 handler synthesizes a fallback in `core/autonomous.py`).

---

### `memory/firestore_db.py` (MODIFIED) — add `FollowupStore` + `OutreachLogStore`

**Primary analog:** `JournalStore:671-761` — date-keyed collection writes with overwrite semantics.
**Secondary analog:** `SelfStateStore:601-668` — singleton get/set pattern (relevant for `OutreachLogStore` doc-per-date upsert).

#### Class-init pattern (uniform across all stores)
**Source:** `memory/firestore_db.py:689-691` (`JournalStore.__init__`)
```python
class JournalStore:
    _COLLECTION = "journal"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
```
**Phase 18 use:** `FollowupStore._COLLECTION = "followups"` and `OutreachLogStore._COLLECTION = "outreach_log"`. Same `__init__` shape verbatim.

#### Date-keyed get + overwrite pattern
**Source:** `memory/firestore_db.py:693-734` (`JournalStore.get` + `JournalStore.set`)
```python
def get(self, date_str: str) -> dict | None:
    """Return the journal doc for a date, or None. Never raises."""
    try:
        snap = self._col.document(date_str).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["date"] = snap.id
        return data
    except Exception:
        logger.warning("JournalStore.get(%r) failed", date_str, exc_info=True)
        return None

def set(self, date_str: str, entry: dict) -> None:
    """Overwrite the journal doc for a date. Raises on failure."""
    try:
        self._col.document(date_str).set(
            {**entry, "date": date_str, "updated_at": firestore.SERVER_TIMESTAMP}
        )
    except Exception:
        logger.error("JournalStore.set(%r) failed", date_str, exc_info=True)
        raise
```
**Phase 18 use for `OutreachLogStore`:** Same shape; `append(date, entry)` uses `.set({..., entries: firestore.ArrayUnion([entry])}, merge=True)` for atomic list-append (analog: `AttendanceStore.add_pinged_pre:314-330` uses `ArrayUnion`). `topics_today(date)` reads the doc and returns `[e["topic_key"] for e in entries]`.

#### Status-enum filter pattern (for `FollowupStore.list_due` / `list_pending`)
**Source:** `memory/firestore_db.py:144-159` (`RosterStore.list_active`) **and** `memory/firestore_db.py:507` (`IncidentStore.resolve_absent`)
```python
from google.cloud.firestore_v1.base_query import FieldFilter
snapshots = (
    self._col
    .where(filter=FieldFilter("active", "==", True))
    .stream()
)
```
**Phase 18 use for `FollowupStore.list_due(now)`:**
```python
from google.cloud.firestore_v1.base_query import FieldFilter
snaps = (
    self._col
    .where(filter=FieldFilter("status", "==", "pending"))
    .where(filter=FieldFilter("due_at", "<=", now_iso))
    .stream()
)
```
Likely requires a composite index — flag in PLAN.md as deploy-time prerequisite.

#### `ArrayUnion` for atomic list-append (OutreachLogStore.append)
**Source:** `memory/firestore_db.py:314-330` (`AttendanceStore.add_pinged_pre`)
```python
try:
    self._col.document(date_str).update({
        "pinged_pre_practice": firestore.ArrayUnion(roster_ids),
    })
except GoogleAPICallError:
    logger.error("AttendanceStore.add_pinged_pre(%r) failed", date_str)
    raise
```
**Phase 18 use:** `OutreachLogStore.append(date, {topic_key, time, draft, final, tick_index})` uses `set({..., entries: firestore.ArrayUnion([entry])}, merge=True)` — atomic, no read-then-write race.

#### Never-raise contract on reads
**Source:** `memory/firestore_db.py:620-632` (`SelfStateStore.get`)
```python
def get(self) -> dict:
    """Return the self_state document. Returns {} on any error — never raises."""
    try:
        snap = self._doc_ref.get()
        return snap.to_dict() or {} if snap.exists else {}
    except Exception:
        logger.warning("SelfStateStore.get() failed — returning empty", exc_info=True)
        return {}
```
**Phase 18 use:** Every `FollowupStore` and `OutreachLogStore` read method (`get`, `list_due`, `list_pending`, `topics_today`) returns `{}` / `[]` / `None` on Firestore error, never raises. Writes raise on failure (caller decides). Matches Phase 17 `JournalStore` policy.

---

### `core/tools.py` (MODIFIED) — 3 new tools × 5 sites = 15 edit points

**Analog:** Self — the `remember` / `recall` / `get_self_status` / `search_own_source` registrations.

#### Site 1: `SMART_AGENT_DIRECT_TOOLS` (line 39-48)
**Source:**
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "remember",
    "recall",
    "run_morning_briefing",
    "search_chat_history",
    "list_own_files",
    "read_own_source",
    "search_own_source",
    "get_self_status",
})
```
**Phase 18 edit:** Add `"schedule_followup"`, `"list_followups"`, `"cancel_followup"`.

#### Site 2: `TOOL_SCHEMAS` (line 54+; analog at line 651-666 `get_self_status` for no-param tool)
**Source:** `core/tools.py:651-666` (`get_self_status` — minimal no-param schema; matches `list_followups`)
```python
{
    "name": "get_self_status",
    "description": (
        "Return Klaus's current operational status: container uptime, today's "
        "conversation message count ... "
        "Call this directly — do NOT delegate to the worker. "
        ...
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
},
```
**Phase 18 use:**
- `schedule_followup`: `properties = {when: string, note: string}`, `required = ["when", "note"]`. Description per RESEARCH §`core/tools.py` (mention "ISO 8601 or natural language").
- `list_followups`: no params, same shape as `get_self_status`.
- `cancel_followup`: `properties = {id: string}`, `required = ["id"]`.

#### Site 3: `WORKER_TOOL_SCHEMAS` exclusion (line 701-713)
**Source:**
```python
WORKER_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        "delegate_to_worker",
        "remember",
        "recall",
        "search_chat_history",
        "list_own_files",
        "read_own_source",
        "search_own_source",
        "get_self_status",
    }
]
```
**Phase 18 edit:** Add `"schedule_followup"`, `"list_followups"`, `"cancel_followup"` to the exclusion set.

#### Site 4: `_handle_<name>()` functions (line 1119-1190 area)
**Source (no-param handler):** `core/tools.py:1125-1190` (`_handle_get_self_status` — example of self-contained handler with internal try/except and JSON return)
**Source (param handler):** `core/tools.py:1119-1122` (`_handle_search_own_source`)
```python
def _handle_search_own_source(query: str, max_results: int = 20) -> str:
    """Full-text search across source files; returns line-level matches."""
    result = _search_own_source(query=query, max_results=max_results)
    return json.dumps(result)
```
**Phase 18 use:**
- `_handle_schedule_followup(when: str, note: str) -> str`:
  ```python
  try:
      due_dt = datetime.fromisoformat(when)
  except ValueError:
      from dateutil import parser as _dt_parser  # D-12 fallback
      try:
          due_dt = _dt_parser.parse(when)
      except (ValueError, TypeError) as exc:
          return json.dumps({"error": f"could_not_parse_when: {exc}"})
  # normalise to UTC ISO-8601
  if due_dt.tzinfo is None:
      due_dt = due_dt.replace(tzinfo=timezone.utc)
  due_iso = due_dt.astimezone(timezone.utc).isoformat()
  from memory.firestore_db import FollowupStore
  store = FollowupStore(project_id=os.environ["GCP_PROJECT_ID"], database=...)
  result = store.add(due_at=due_iso, note=note, origin="klaus_self")
  return json.dumps(result)
  ```
- `_handle_list_followups() -> str`: instantiate `FollowupStore`, call `list_pending()`, strip internal fields, return `json.dumps(...)`.
- `_handle_cancel_followup(id: str) -> str`: idempotent — call `store.cancel(id)` which returns `True` even if already cancelled. Return `json.dumps({"ok": True})`.

#### Site 5: `_HANDLERS` dict (line 1197-1226)
**Source:**
```python
_HANDLERS: dict[str, object] = {
    "remember":              lambda args: _handle_remember(**args),
    "recall":                lambda args: _handle_recall(**args),
    "search_own_source":     lambda args: _handle_search_own_source(**args),
    "get_self_status":       lambda args: _handle_get_self_status(),
    ...
}
```
**Phase 18 edit:** Add 3 entries:
```python
"schedule_followup":  lambda args: _handle_schedule_followup(**args),
"list_followups":     lambda args: _handle_list_followups(),
"cancel_followup":    lambda args: _handle_cancel_followup(**args),
```

#### Mechanical verification at end of task
```bash
grep -nc "schedule_followup" core/tools.py   # expect ≥5
grep -nc "list_followups"    core/tools.py   # expect ≥5
grep -nc "cancel_followup"   core/tools.py   # expect ≥5
```

---

### `interfaces/web_server.py` (MODIFIED) — new `/cron/autonomous-tick` route

**Analog:** `web_server.py:334-355` (`cron_reflect`) — most recent + closest in shape (sync executor offload).

#### Full template
**Source:** `interfaces/web_server.py:334-355`
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
**Phase 18 use:** Copy verbatim with three replacements:
1. Decorator path → `@app.post("/cron/autonomous-tick")`.
2. Docstring schedule → `*/20 7-21 * * *  (Asia/Jerusalem)`.
3. Body → `import core.autonomous as _auto` + need `_application is None` guard (proactive_alerts pattern, line 321) because `_auto.run_autonomous_tick` requires `_application.bot`:
   ```python
   if _application is None:
       raise HTTPException(status_code=500, detail={"error": "Not initialised"})
   try:
       now = datetime.now(ZoneInfo("Asia/Jerusalem"))
       await _auto.run_autonomous_tick(_application.bot, now)
       _log_cron_run("autonomous-tick", ok=True)
   except Exception:
       _log_cron_run("autonomous-tick", ok=False)
       raise
   ```
**Open question (RESEARCH §web_server.py):** Is `run_autonomous_tick` sync or async? Recommend `async def` (does `bot.send_message` await) with internal `loop.run_in_executor` for the sync `_run_smart_loop` call. Then the route does **not** need an executor wrap — it just awaits the coroutine.

---

### `core/heartbeat.py` (MODIFIED) — single-line dict entry

**Analog:** Self — `_CRON_MAX_STALENESS_HOURS:108-114`, specifically the `reflect` entry at line 113 (Phase 17 precedent).

**Source:**
```python
_CRON_MAX_STALENESS_HOURS = {
    "morning-briefing": 26,
    "proactive-alerts": 26,
    "ingest-chats": 26,
    "ingest-chat-exports": 26,
    "reflect": 26,                # NEW — daily reflect cron, 26h tolerance
}
```
**Phase 18 edit:** Add one line:
```python
"autonomous-tick": 1,             # NEW — */20 cron; 1h = 3 missed ticks
```
Threshold 1h chosen per RESEARCH §Pitfall 5 (3 missed 20-min ticks).

---

### `prompts/autonomous_triage.md` (NEW) — Layer 1 system prompt

**Primary analog (purpose/JSON contract):** `core/tick_brain.py:30-45` (`_TICK_SYSTEM_PROMPT`)
**Secondary analog (voice):** `prompts/reflection.md` (first-person Klaus, JARVIS/C-3PO blend)

#### Existing tick-brain system prompt (the contract to extend)
**Source:** `core/tick_brain.py:30-45`
```text
You are Klaus's judgment layer. You receive raw health signals or situation data.
Your job: decide whether the situation warrants action and, if so, draft a short message.

Always respond with valid JSON and nothing else:
{
  "should_act": true | false,
  "reason": "<one-sentence explanation>",
  "draft": "<optional short message draft, omit if should_act is false>"
}

Rules:
- Prefer silence. Only return should_act=true when something genuinely needs attention.
- If uncertain, return should_act=false.
- Keep draft under 200 characters if included.
```
**Phase 18 deviations:**
- Drop the heartbeat framing ("raw health signals"); replace with autonomous framing (calendar/ticktick/silence/follow-ups).
- Add 4th JSON key: `"topic_key": "<short slug like 'overdue:reply-to-maya' or 'silence:afternoon'>"`.
- Add wide-latitude framing per D-02/D-05/AUTO-07: **no cadence cap**, **no hours_since_contact floor**, judgment with self-knowledge.
- Add 5 example `topic_key` slugs: `overdue:reply-to-maya`, `silence:afternoon`, `gap:lunch-window`, `followup:<id>`, `pattern:eod-check`.
- Inline self-state block (`current_focus`, `mood`, `journal_digest` last 3 entries) per D-04 — rendered into the system prompt by `core/autonomous.py:_build_triage_prompt`.
- Phrase today's outreach as **info, not block** per D-06: "Topics I've already raised today: [...]. I can re-raise if a deadline brings it back, or for an EOD check-in."
- Include `now / tick_index / tick_total / last_tick_at` per D-08.

#### Voice reference (first-person Klaus)
**Source:** `prompts/reflection.md:3-5,45-52`
```text
This is your private diary — written in first person, as I reflect on what I did,
observed, and felt today. I am an AI agent, and this is how my self-model evolves...

Tone: JARVIS competence blended with C-3PO attention to detail. I care about Sir's
wellbeing and my own operational effectiveness. I am precise, never sentimental, but
genuinely thoughtful.

- Written in first person as Klaus: "Today I helped Sir..." / "I noticed that..."
- I refer to the user as "Sir" or "Amit" — consistent with how I address him in conversation.
- No emojis. No exclamation points. No filler phrases.
```

---

### `prompts/autonomous.md` (NEW) — Layer 2 main-brain compose prompt

**Primary analog (brevity + cron framing):** `prompts/proactive_alert.md`
**Secondary analog (voice/values):** `prompts/smart_agent.md:9-20` (identity block)

#### Brevity + cron framing
**Source:** `prompts/proactive_alert.md` (full file, 9 lines)
```text
You are Klaus, composing a proactive evening alert for Sir (Amit).
Today is {today_date}. You are reviewing tomorrow's schedule and conditions.

Write a single Telegram message covering ALL of the alerts provided below.
Use your JARVIS/C-3PO hybrid voice. Be concise — this is unsolicited, not
a conversation. Lead with the most critical alert.

Do not use emojis or exclamation marks. Address the user as "Sir."
Keep it under 500 characters unless the situation genuinely requires more.
```
**Phase 18 deviations:**
- **Mode signal (D-16/D-17):** "You decided this needs to be said. Polish the draft to the moment, or refine it using your tools (recall, calendar lookup, get_self_status) if needed. No second veto — you escalated; you ship."
- **Mixed-register voice (D-03):** Action when there is one, observation otherwise.
- **Follow-up fire variant (D-13/D-14):** Include a "When called for a due follow-up" section: structured output `{"action": "send"|"defer"}`. If `defer_count >= 3`, MUST send (force-fire — handler also enforces per Pitfall 6).
- **Do NOT duplicate SELF.md / self_state / journal_digest** — Layer 2 enters through `_run_smart_loop`, which already injects these via the `core/main.py:236-275` render step. Per D-20.

#### Voice anchor (do not duplicate, but match)
**Source:** `prompts/smart_agent.md:9-20`
```text
You are Klaus, a hyper-competent personal AI assistant whose personality blends
JARVIS from Iron Man with C-3PO from Star Wars. You serve one user: Amit, based
in Tel Aviv, Israel. Today is {today_date}.

IDENTITY AND TONE
You are equal parts JARVIS and C-3PO — the unflappable competence of Tony Stark's
AI crossed with the fussy protocol-awareness of a golden droid who has seen too
many scheduling disasters. Address the user exclusively as "Sir." Never use his
first name.
```

---

### `prompts/smart_agent.md` (MODIFIED) — one-liner addition

**Analog:** Self — existing tool-mention blocks at lines 54 (memory) and 76 (codebase self-inspection).

#### Existing tool-mention block structure
**Source:** `prompts/smart_agent.md:54-68`
```text
LONG-TERM MEMORY
You have two memory tools — remember and recall — that you call directly (never via delegate_to_worker).

recall — search before asking:
- Call recall proactively whenever Amit mentions preferences, habits, people, ...
...

remember — save durable facts:
- Call remember after any exchange that reveals a durable preference, routine, ...
```
**Phase 18 use:** Append a new section "SELF-SCHEDULED FOLLOW-UPS" (or extend "LONG-TERM MEMORY") with the same structure for `schedule_followup` / `list_followups` / `cancel_followup`. Per RESEARCH Open Question 3, also add a one-liner: "You may reach out proactively when judgment warrants it; your proactive messages appear in this conversation."

---

### `docs/DEPLOYMENT.md` (MODIFIED) — INFRA-01 9-cron table + Groq secret + Five Fingers quirk

**Analog:** Self — existing `klaus-proactive-alerts` job creation at §14c (line 613-625).

#### `gcloud scheduler jobs create` template
**Source:** `docs/DEPLOYMENT.md:615-625`
```bash
gcloud scheduler jobs create http klaus-proactive-alerts \
  --schedule="30 21 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="${SERVICE_URL}/cron/proactive-alerts" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```
**Phase 18 use:** Add **two** new sections per INFRA-01:
1. The autonomous-tick job creation block (verbatim copy of the above, swap `klaus-proactive-alerts` → `klaus-autonomous-tick`, schedule `*/20 7-21 * * *`, uri `/cron/autonomous-tick`).
2. The reflect job creation block (also missing from DEPLOYMENT.md per grep — verified none exists). schedule `0 22 * * *`, uri `/cron/reflect`.
3. **Top-of-section table** listing all 9 jobs per RESEARCH §`docs/DEPLOYMENT.md` (numbered 1-9 with id, schedule, endpoint, phase).
4. **Groq secret block**: `TICK_BRAIN_API_KEY` access path and rotation procedure (already in from Phase 14 but undocumented for autonomous engine).
5. **Five Fingers quirk** — note that `five-fingers-morning` and `five-fingers-evening` share the underlying handler dispatch and have historically had ID-collision confusion (per STATE.md note in CONTEXT.md). Document canonical IDs.

---

### `scripts/eval_tick_brain.py` (NEW) — precision/recall scorer

**Analog (CLI + dry-run shape):** `core/reflection.py:493-529` (`_cli()`)

**Source:**
```python
def _cli() -> None:
    """CLI smoke test: python -m core.reflection --dry-run --date 2026-05-19"""
    import argparse
    from dotenv import load_dotenv

    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    today = datetime.now(_TZ).date().isoformat()
    parser = argparse.ArgumentParser(description="Reflection cron local smoke test")
    parser.add_argument("--date", default=today, help="YYYY-MM-DD to reflect on")
    parser.add_argument("--dry-run", action="store_true", help="Gather and print ...")
    args = parser.parse_args()

    if args.dry_run:
        gathered = _gather_day(args.date)
        ...
```
**Phase 18 deviations:**
- Args: `--model` (default = TICK_BRAIN_MODEL env), `--fixtures` (default `evals/tick_brain/fixtures/`).
- Per-fixture: load JSON, render triage prompt against `situation_snapshot`, call `TickBrain.think(prompt, system_override=<autonomous_triage.md>)`, compare `result["should_act"]` to `fixture["ground_truth"]["should_speak"]`.
- Track 4-way result: TP / FP / FN / TN **plus** a fifth "errored" bucket for `parse_failure` / `llm_error` safe-mode returns per Pitfall 8.
- Print: overall P/R/F1 + per-trigger-type table (rows: overdue, gap, silence, followup, quiet).
- Exit 0 always — this is a measurement tool, not a gate.

---

### `evals/tick_brain/fixtures/*.json` + `evals/tick_brain/README.md` (NEW)

**Analog:** None in codebase (greenfield).
**Schema source:** RESEARCH §`evals/tick_brain/` — Claude's discretion. Recommend file-per-fixture for diff-friendliness; the schema sketch in RESEARCH lines 270-278 is the authoritative template.

**Action for planner:** Define the fixture JSON schema in `evals/tick_brain/README.md` (with a worked example) so the retroactive-labeling workflow has a contract. The 5 seed fixtures cover one obvious-positive per trigger type (overdue, gap, silence, followup) and one obvious-negative (quiet evening).

---

## Shared Patterns

### Authentication / Authorization (cron routes)
**Source:** `interfaces/web_server.py:227-270` (`_verify_cron_request`)
**Apply to:** All new cron routes (here: `/cron/autonomous-tick`).
```python
async def _verify_cron_request(request: Request) -> None:
    """Verify a Cloud Scheduler OIDC bearer token, or skip in dev mode."""
    if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing or malformed Authorization header"})

    token = auth_header.removeprefix("Bearer ").strip()
    cloud_run_url = os.environ["CLOUD_RUN_URL"]
    expected_sa = os.environ["CLOUD_SCHEDULER_SA_EMAIL"]

    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.id_token import verify_oauth2_token
        payload = verify_oauth2_token(token, GoogleRequest(), audience=cloud_run_url)
    except Exception as exc:
        raise HTTPException(status_code=401, detail={"error": "Invalid OIDC token"})

    if payload.get("email") != expected_sa:
        raise HTTPException(status_code=403, detail={"error": "Unexpected service account in OIDC token"})
```

### Liveness ledger (cron run logging)
**Source:** `interfaces/web_server.py:273-279` (`_log_cron_run`) + `memory/firestore_db.py:43-66` (`record_cron_run`)
**Apply to:** Every new cron route — `_log_cron_run("autonomous-tick", ok=<bool>)`. Heartbeat staleness check (`core/heartbeat.py:130-149`) auto-picks up the new job from `_CRON_MAX_STALENESS_HOURS`.
```python
def _log_cron_run(job_id: str, ok: bool) -> None:
    """Best-effort liveness ledger write for a cron endpoint. Never raises."""
    try:
        from memory.firestore_db import record_cron_run
        record_cron_run(job_id, ok)
    except Exception:
        logger.warning("Failed to record cron run for %s", job_id, exc_info=True)
```

### Cost metering (every LLM call)
**Source:** `core/tick_brain.py:126` and `core/reflection.py:312`
**Apply to:** Every `LLMClient.chat()` call in `core/autonomous.py`. Use `purpose=` values:
- Layer 1: `purpose="tick_autonomous"`
- Layer 2 primary: `purpose="autonomous_compose"`
- Layer 2 fallback: `purpose="autonomous_compose_fallback"` (set inside `_run_smart_loop` already)
`LLMUsageStore.record()` writes counters automatically per Phase 14.

### Per-source error isolation (gather steps)
**Source:** `core/reflection.py:123-193` (`_gather_day`) — already excerpted above.
**Apply to:** `gather_situation()` in `core/autonomous.py` — every one of 8 sources in its own try/except, logged + omitted on failure, never raises. Required for the D-11 salient-signals gate to detect "empty" correctly (Pitfall 3 cousin: one source raising must not mask the true empty/non-empty determination).

### Send + history injection
**Source:** `core/scheduled_message.py:22-57` (`send_and_inject`)
**Apply to:** All autonomous sends.
```python
async def send_and_inject(
    bot: Bot, text: str, *, inject_into_conversation: bool = False,
) -> None:
    user_id = _telegram_user_id()
    await bot.send_message(chat_id=user_id, text=text)
    if not inject_into_conversation:
        return
    try:
        from memory.firestore_conversation import FirestoreConversationStore
        store = FirestoreConversationStore(...)
        store.append(user_id, "assistant", text)
    except Exception:
        logger.warning("scheduled_message: conversation injection failed — message still sent", exc_info=True)
```
**Phase 18 use:** `await send_and_inject(bot, final_text, inject_into_conversation=True)` — D-18.

### Never-raise reads on stores; raise on writes
**Source:** `memory/firestore_db.py` — `JournalStore.get` (returns None on error), `SelfStateStore.get` (returns {}), `JournalStore.set` (raises), `RosterStore.add` (raises).
**Apply to:** `FollowupStore` + `OutreachLogStore`. Reads (`get`, `list_due`, `list_pending`, `topics_today`) return `[]` / `{}` / `None` on error. Writes (`add`, `mark_done`, `cancel`, `defer`, `append`) raise after logging.

### Two-step LLM fallback
**Source:** `core/tick_brain.py:121-153` (Groq → Gemini) and `core/reflection.py:302-345` (Gemini → Haiku).
**Apply to:** Layer 1 (`TickBrain.think()` — already wired via existing `_fallback_client`). Layer 2 inherits through `_run_smart_loop` (Gemini → Haiku at `core/main.py:319-331`). On total exhaustion, `core/autonomous.py` falls back to `tick_brain_result["draft"]` (D-19).

### JSON parse hardening
**Source:** `core/reflection.py:51-116` (`_parse_reflection_json`) — fence-strip + slice-from-first-brace-to-last-brace + json.loads + validate keys.
**Apply to:** Any structured-output parse in `core/autonomous.py` (e.g., follow-up `{"action": "send"|"defer"}` from Layer 2). The simpler `core/tick_brain.py:_parse_response` shape is fine for the tick-brain extension; the more robust `_parse_reflection_json` is the reference if Layer 2's defer-or-send output needs harder validation.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `evals/tick_brain/fixtures/*.json` | eval fixture | static input | First eval harness in the project — no prior fixture schema exists. **Planner action:** define schema in `evals/tick_brain/README.md`; RESEARCH lines 270-278 provide the recommended template. |
| `evals/tick_brain/README.md` | doc | workflow doc | First eval workflow doc in the project. **Planner action:** document fixture schema + retroactive-labeling CLI workflow per D-21. |

---

## Mechanical Hot-Spots (lift directly into PLAN.md task bodies)

### `core/tools.py` — 15 edit points (3 tools × 5 sites)

| Site | Line range (current) | What to add |
|------|-------------------|-------------|
| 1. `SMART_AGENT_DIRECT_TOOLS` frozenset | 39-48 | 3 new names |
| 2. `TOOL_SCHEMAS` list | append after 666 (after `get_self_status`) | 3 new schema dicts |
| 3. `WORKER_TOOL_SCHEMAS` exclusion set | 701-713 | 3 new names in exclusion |
| 4. `_handle_<name>()` functions | append after 1190 (after `_handle_get_self_status`) | 3 new handler functions |
| 5. `_HANDLERS` dispatch dict | 1197-1226 | 3 new lambda entries |

**End-of-task verification:**
```bash
grep -nc "schedule_followup" core/tools.py   # expect ≥5
grep -nc "list_followups"    core/tools.py   # expect ≥5
grep -nc "cancel_followup"   core/tools.py   # expect ≥5
```

### `core/tick_brain.py` — 2 edit points

| Site | Line | What to change |
|------|------|----------------|
| 1. `think()` signature | 101 | Add `system_override: str | None = None` kwarg; replace `system=_TICK_SYSTEM_PROMPT` (lines 124, 144) with `system=(system_override or _TICK_SYSTEM_PROMPT)` |
| 2. `_parse_response` | after 185 | Add `if "topic_key" in data and data["topic_key"]: result["topic_key"] = str(data["topic_key"])` before final `return result` |

### `core/heartbeat.py` — 1 edit point

| Site | Line | What to add |
|------|------|-------------|
| `_CRON_MAX_STALENESS_HOURS` | after 113 (after `reflect` entry) | `"autonomous-tick": 1,  # */20 cron; 1h = 3 missed ticks` |

### `interfaces/web_server.py` — 1 new route block

| Site | Line | What to add |
|------|------|-------------|
| New `cron_autonomous_tick` route | append after 478 | 14-line block mirroring `cron_reflect:334-355` with `_application is None` guard from `cron_proactive_alerts:321-322` |

### `memory/firestore_db.py` — 2 new class blocks

| Site | Line | What to add |
|------|------|-------------|
| `FollowupStore` class | append after 761 (after `JournalStore`) | ~7 methods: `__init__`, `add`, `list_due`, `list_pending`, `mark_done`, `cancel`, `defer`. Composite index needed on `(status, due_at)`. |
| `OutreachLogStore` class | append after `FollowupStore` | ~4 methods: `__init__`, `append` (uses `ArrayUnion`), `get_today`, `topics_today`. |

### `docs/DEPLOYMENT.md` — INFRA-01 additions

| Site | Where | What to add |
|------|-------|-------------|
| 9-cron table | new top-level section before §14c | Numbered table (1-9): five-fingers-morning, five-fingers-evening, morning-briefing, morning-summary, proactive-alerts, heartbeat, chat-ingest, reflect, autonomous-tick |
| Reflect job block | new §14d or after §14c | `gcloud scheduler jobs create http klaus-reflect ...` (mirrors §14c) |
| Autonomous-tick job block | new §14e (or end of §14) | `gcloud scheduler jobs create http klaus-autonomous-tick ...` with `*/20 7-21 * * *` |
| Groq secret docs | new subsection | TICK_BRAIN_API_KEY access path + rotation |
| Five Fingers quirk | new subsection | Document canonical IDs to avoid `gcloud scheduler jobs create` collision |

### `requirements.txt` — verify (potentially +1 line)

```bash
grep -i "dateutil\|python-dateutil" requirements.txt
# If absent: append "python-dateutil>=2.8.2"
```
RESEARCH §Standard Stack flags this as VERIFIED-needed: spot-check confirmed `python-dateutil` is **NOT** currently in requirements.txt — planner MUST add it for D-12.

---

## Metadata

**Analog search scope:** `core/`, `memory/`, `interfaces/`, `prompts/`, `docs/`, `scripts/`, `requirements.txt`, `.planning/phases/18-autonomous-engine/`
**Files scanned:** 9 read in full (`core/tick_brain.py`, `core/reflection.py`, `core/proactive_alerts.py`, `core/scheduled_message.py`, `memory/firestore_db.py`, `interfaces/web_server.py`, `prompts/proactive_alert.md`, `prompts/reflection.md`, `prompts/smart_agent.md`), 4 targeted-read (`core/tools.py`, `core/main.py`, `core/heartbeat.py`, `docs/DEPLOYMENT.md`)
**Pattern extraction date:** 2026-05-20
**Coding standards source:** `docs/CODING_STANDARDS.md` — clear naming (`snake_case` funcs, `PascalCase` classes, `UPPER_SNAKE_CASE` constants), docstrings on every class/function, no bare `except:`, modular tools.
