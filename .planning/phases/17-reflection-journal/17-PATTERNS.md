# Phase 17: Reflection & Journal - Pattern Map

**Mapped:** 2026-05-19
**Files analyzed:** 8 (1 new module, 1 new prompt, 6 modified)
**Analogs found:** 8 / 8 (all have a verified in-codebase analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/reflection.py` (NEW) | service / orchestrator | batch (cron-triggered gather → LLM → multi-write) | `core/proactive_alerts.py` | exact (cron-context orchestrator) |
| `prompts/reflection.md` (NEW) | config / prompt | transform (JSON input → structured output) | `prompts/proactive_alert.md` + `prompts/morning_briefing.md` | role-match |
| `memory/firestore_db.py` (MOD — add `JournalStore`) | model / store | CRUD (date-keyed Firestore docs) | `AttendanceStore` (date-keyed) + `SelfStateStore` (get/set shape) | exact (composite) |
| `memory/pinecone_db.py` (MOD — `"self"` kind + `remember_self()`) | model / store | transform + CRUD (embed → deterministic-ID upsert) | `MemoryStore.remember` (`pinecone_db.py:55`) | exact (same class, adapt) |
| `interfaces/web_server.py` (MOD — `/cron/reflect` route) | route / controller | request-response (OIDC → run → ledger) | `cron_proactive_alerts` (`:310`) + `cron_ingest_chats` executor (`:381`) | exact |
| `core/main.py` (MOD — `{journal_digest}` injection) | service / orchestrator | transform (store read → prompt string assembly) | `{self_state}` snippet at `core/main.py:239-256` | exact (sibling snippet) |
| `core/tools.py` (MOD — `recall` `kind` param + `get_self_status` journal) | utility / tool dispatch | request-response (tool call → handler) | `recall` schema/`_handle_recall`/`search_chat_history` | exact (same tool family) |
| `mcp_tools/memory.py` (MOD — `MemoryTool.recall` gains `kinds`) | utility / tool wrapper | request-response (wrapper → store) | `MemoryTool.search_chat_history` (`:68`, already forwards `kinds`) | exact (sibling method) |

---

## Pattern Assignments

### `core/reflection.py` (NEW — service / orchestrator)

**Analog:** `core/proactive_alerts.py` (entire file is the structural template). Secondary: `core/morning_briefing.py` `_compose_briefing` for the LLM-call-with-fallback shape.

**Module header + imports pattern** (`proactive_alerts.py:1-24`):
```python
"""Daily reflection — gather the day, write a journal entry, evolve self_state.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/reflect  (22:00 daily, Asia/Jerusalem)

Local smoke test:
  python -m core.reflection --dry-run --date 2026-05-19
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")
```

**Firestore client helper — copy verbatim** (`proactive_alerts.py:80-84`):
```python
def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _mfc(project_id, database)
```

**Owner-ID sourcing (cron has no request context)** — copy from `core/scheduled_message.py:17-19`:
```python
def _telegram_user_id() -> int:
    raw = os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip()
    return int(raw)
```
Use this for `remember_self(user_id=...)` Pinecone scoping (D-07) and any conversation lookup. Resolves CONTEXT.md "Claude's Discretion" item 4.

**Public entry point signature** — adapt `run_proactive_alerts(bot, target_date)` (`proactive_alerts.py:91`). Phase 17 sends no Telegram message, so DROP the `bot` arg:
```python
def run_reflection(target_date: str) -> None:
    """Gather the day, produce a journal entry, write 3 targets, evolve self_state.

    Args:
        target_date: YYYY-MM-DD (Asia/Jerusalem). Document key for journal/{date}.
    """
```
Note: synchronous (not `async`) — D-13/RESEARCH A2 recommends running it in a thread-pool executor from the route (see web_server pattern below). `run_proactive_alerts` is `async` only because it `await`s `bot.send_message`; reflection has no such call.

**Per-source best-effort gather pattern** — D-01 mandates per-source try/except. `proactive_alerts.py:111-117` is the reference (weather fetch isolated so a failure does not abort the run):
```python
weather: dict | None = None
try:
    from mcp_tools.weather_tool import fetch_weather
    weather = fetch_weather("Tel Aviv")
except Exception:
    logger.warning("Proactive alerts: weather fetch failed", exc_info=True)
```
Apply the SAME shape to each of D-01's five gather sources (LLM usage, conversation summary, calendar, TickTick, heartbeat). A failed source is omitted; the reflection still runs and writes an entry.

**Cron-context LLM call + fallback** — the core pattern, from `proactive_alerts.py:_compose_alert` (`:334-366`). The reflection makes TWO such calls per D-02:

```python
# Source: proactive_alerts.py:336-366 — adapt for worker (summary) and brain (reflect).
prompt_path = Path(__file__).parent.parent / "prompts" / "reflection.md"
try:
    system_prompt = prompt_path.read_text(encoding="utf-8").replace("{today_date}", today_str)
except OSError:
    system_prompt = "You are Klaus, writing your daily reflection journal."

user_message = json.dumps(gathered_day, ensure_ascii=False, indent=2)

try:
    from core.llm_client import LLMClient
    client = LLMClient(
        backend=os.environ["SMART_AGENT_BACKEND"],   # brain — for the reflection call
        model=os.environ["SMART_AGENT_MODEL"],
        api_key=os.environ["SMART_AGENT_API_KEY"],
    )
    response = client.chat(
        messages=[{"role": "user", "content": user_message}],
        system=system_prompt,
        purpose="reflect",                            # NEW purpose label — metered free
    )
    text = (response.get("text") or "").strip()
    ...
except Exception:
    logger.warning("Reflection: LLM call failed", exc_info=True)
```
- **Worker summarization call (D-02):** identical shape but use `WORKER_AGENT_BACKEND` / `WORKER_AGENT_MODEL` / `WORKER_AGENT_API_KEY` (`.env.example:18-20` — `gemini` / `gemini-2.5-flash`) and `purpose="reflect_summary"`.
- **Brain reflection call (D-02):** `SMART_AGENT_*` env vars as shown.
- **Brain → fallback chain (D-13):** RESEARCH cites the inline brain→Haiku fallback at `core/main.py:260-291` as the reference. On brain failure, retry with the fallback model env vars; if BOTH fail, write the minimal fallback journal doc (placeholder summary `"reflection unavailable"` + raw metrics).
- `LLMClient.chat` auto-meters cost (`llm_client.py:105-125`) — no manual accounting; just pass `purpose=`.

**JSON-parse hardening (Pitfall 3 — genuinely new code, no analog):** write a `_parse_reflection_json(text)` helper — strip ```json fences, slice first `{` to last `}`, `json.loads`, validate all 5 D-03 keys (`summary`, `mood`, `current_focus`, `recent_context`, `highlights`) present with correct types, default missing fields. Parse failure → D-13 minimal fallback.

**Plain-text/minimal fallback** — `proactive_alerts.py:_plain_text_fallback` (`:369-392`) is the deterministic-fallback shape. For Phase 17 this becomes the D-13 minimal `journal/{date}` doc: raw metrics + `summary="reflection unavailable"`.

**CLI smoke test** — `proactive_alerts.py:_cli` (`:399-470`) with `--dry-run` / `--date` flags is the reusable template; mirror it for `python -m core.reflection`.

---

### `prompts/reflection.md` (NEW — config / prompt)

**Analog:** `prompts/proactive_alert.md` and `prompts/morning_briefing.md` (both are cron-context system prompts loaded by `_compose_*` via `Path(...).read_text()` with a `{today_date}` placeholder).

**Pattern to copy:**
- Single-string system prompt file in `prompts/`.
- Supports the `{today_date}` placeholder substituted by `.replace()` at load time (`proactive_alerts.py:340-342`).
- Reflection-specific (D-17): written in **first person as Klaus** ("Today I helped Amit…") — a diary, not a system log. Tone aligned with `docs/AGENT.md` persona (JARVIS + C-3PO; addresses Amit as "Sir").
- Must instruct the brain to emit **strict JSON** with the 5 D-03 fields. Pair this with the `_parse_reflection_json` helper since `LLMClient.chat()` enforces no JSON mode (Pitfall 3). Unlike `proactive_alert.md`/`morning_briefing.md` which ask for prose, this prompt is the first asking for structured output.
- D-18 continuity: the prompt receives yesterday's journal `summary` + `current_focus` as input; the continuity section must be conditionally omitted on the first ever run (Pitfall 6).

---

### `memory/firestore_db.py` — add `JournalStore` class (MOD — model / store, CRUD)

**Analog:** `AttendanceStore` (`firestore_db.py:226-330`) for the date-keyed collection pattern; `SelfStateStore` (`:601-668`) for the `get`/`set` error-handling shape.

**Imports/helpers already present** — reuse `_make_firestore_client` (`:24`), the module `logger` (`:21`), and `from google.cloud import firestore` (`:18`). No new imports needed.

**Constructor pattern** — copy `AttendanceStore.__init__` (`:234-247`):
```python
def __init__(self, project_id: str, database: str = "(default)") -> None:
    self._client = _make_firestore_client(project_id, database)
    self._col = self._client.collection(self._COLLECTION)
```

**`get(date_str)` — reads return `None` on error, never raise** — adapt `AttendanceStore.get_practice` (`:249-270`) but use the broader `except Exception` from `SelfStateStore.get` (`:627-632`) since the journal feeds `get_self_status` and the digest (a failure must not crash a conversation):
```python
def get(self, date_str: str) -> dict | None:
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
```

**`set(date_str, entry)` — IMPORTANT divergence from the analogs.** `AttendanceStore.upsert_practice` (`:284`) and `SelfStateStore.set` (`:640`) both use `merge=True` because they *patch*. D-12 says reflection **overwrites** the whole `journal/{date}` doc — use `.set()` **WITHOUT `merge=True`** so a re-run with fewer fields leaves no stale keys. Append `firestore.SERVER_TIMESTAMP` (the `SelfStateStore.set` convention, `:641`):
```python
def set(self, date_str: str, entry: dict) -> None:
    try:
        self._col.document(date_str).set(
            {**entry, "date": date_str, "updated_at": firestore.SERVER_TIMESTAMP}
        )
    except Exception:
        logger.error("JournalStore.set(%r) failed", date_str, exc_info=True)
        raise
```

**`get_recent(n)` — newest-first** — `AttendanceStore` has `recent_practices(n)`-style queries as the conceptual analog. For a single-user, low-volume collection use `stream()` + Python `sort` (no composite index needed):
```python
def get_recent(self, n: int) -> list[dict]:
    try:
        snaps = list(self._col.stream())
    except Exception:
        logger.warning("JournalStore.get_recent failed", exc_info=True)
        return []
    results = []
    for snap in snaps:
        data = snap.to_dict() or {}
        data["date"] = snap.id
        results.append(data)
    results.sort(key=lambda d: d.get("date", ""), reverse=True)
    return results[:n]
```
(`LLMUsageStore.summary("month")` at `:579-592` shows the `stream()` + aggregate pattern already in this file.)

**Class-constant convention** — `_COLLECTION = "journal"` mirrors `LLMUsageStore._COLLECTION` (`:536`) / `SelfStateStore._COLLECTION` (`:613`).

---

### `memory/pinecone_db.py` — `"self"` kind + `remember_self()` (MOD — model / store)

**Analog:** `MemoryStore.remember` (`pinecone_db.py:55-94`) — same class, adapt for a deterministic vector ID.

**`_VALID_KINDS` change (D-06)** — `pinecone_db.py:29`:
```python
_VALID_KINDS = frozenset({"fact", "chunk", "chat", "self"})   # add "self"
```
Also update the module docstring (`:6-13`) which enumerates the three kinds.

**`remember_self()` — new path.** `remember()` (`:79-92`) hard-codes `vector_id = str(uuid.uuid4())` (`:80`) — it CANNOT produce the deterministic `self-{date}` ID D-07 needs. Copy the embed+upsert body of `remember()` but substitute the ID and enforce truncation (Pitfall 2 — `remember()` *raises* on overflow at `:73-77`; the new path should *truncate* per CONTEXT discretion):
```python
def remember_self(self, user_id: int, date_str: str, content: str) -> str:
    """Upsert a journal entry with a deterministic vector ID (self-{date}).

    A re-run for the same date overwrites the existing vector — no duplicates.
    """
    if len(content) > CONTENT_MAX_CHARS:
        content = content[:CONTENT_MAX_CHARS]          # truncate, do not raise
    vector = self._embed(content)
    vector_id = f"self-{date_str}"
    ts = datetime.now(tz=timezone.utc).isoformat()
    self._get_index().upsert(vectors=[{
        "id": vector_id,
        "values": vector,
        "metadata": {
            "user_id": str(user_id),                   # same $eq-scoped key as remember()
            "kind": "self",
            "content": content,
            "ts": ts,
        },
    }])
    return vector_id
```
The `metadata.user_id` key MUST match `remember()`'s format (`str(user_id)`, `:87`) so `recall()`'s `$eq` user filter (`:117-119`) isolates journal vectors correctly.

**Recall already supports it** — `recall()` (`:96-130`) already accepts `kinds` and applies `{"kind": {"$in": _kinds}}` (`:119`). With `"self"` in `_VALID_KINDS`, `recall(kinds=["self"])` works with no further change to this method.

---

### `interfaces/web_server.py` — `/cron/reflect` route (MOD — route / controller)

**Analog:** `cron_proactive_alerts` (`web_server.py:310-331`) for the OIDC + `_log_cron_run` shape; `cron_ingest_chats` (`:381-404`) for the **executor pattern** (synchronous blocking work off the event loop).

**Shared cron infrastructure — reuse as-is:** `_verify_cron_request` (`:227`, OIDC + `CRON_DEV_BYPASS`), `_log_cron_run` (`:273`, liveness ledger). No changes to these.

**Route pattern** — combine the `cron_proactive_alerts` skeleton with the `cron_ingest_chats` executor (RESEARCH A2: `run_reflection` is synchronous Firestore + LLM work, so run it in an executor rather than making every gather helper `async`; reflection sends no Telegram message so the `if _application is None` guard is unnecessary):
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
- `_log_cron_run("reflect", ...)` job-id matches the Cloud Scheduler job name (D-11).
- Israel-time "today": `datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()` — the pattern in every existing cron route (`:301`, `:325`, `:349`).
- `datetime`, `timedelta`, `ZoneInfo` are already imported at the top of `web_server.py` (used by sibling routes).

**Companion one-line change (Pitfall 5)** — `core/heartbeat.py:108-113` `_CRON_MAX_STALENESS_HOURS` is a hard-coded allow-list. Add `"reflect": 26` so a stalled reflect cron is monitored:
```python
_CRON_MAX_STALENESS_HOURS = {
    "morning-briefing": 26,
    "proactive-alerts": 26,
    "ingest-chats": 26,
    "ingest-chat-exports": 26,
    "reflect": 26,                # NEW — daily job, 26h tolerance
}
```

---

### `core/main.py` — `{journal_digest}` injection (MOD — service / orchestrator)

**Analog:** the `{self_state}` snippet, built and `.replace()`d in the same method. `AgentOrchestrator.handle_message` (`core/main.py:239-256`) and `_build_self_state_store` (`:553-563`).

**Store builder** — copy `_build_self_state_store` (`:553-563`) verbatim, swapping the class:
```python
def _build_journal_store() -> JournalStore | None:
    project_id = os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        logger.warning("GCP_PROJECT_ID not set — JournalStore disabled")
        return None
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    return JournalStore(project_id=project_id, database=database)
```
Call it in `__init__` next to `self._self_state_store = _build_self_state_store()` (`:212`): `self._journal_store = _build_journal_store()`.

**Digest snippet assembly** — modeled on the `self_state_snippet` block (`:239-249`). Build it in `handle_message` right after that block:
```python
journal_digest = ""
if self._journal_store is not None:
    entries = self._journal_store.get_recent(3)          # newest-first
    if entries:
        lines = ["**Recent journal:**"]
        for e in entries:
            line = f"- {e.get('date','')} (mood: {e.get('mood','')}): {e.get('summary','')}"
            highlights = e.get("highlights") or []
            if highlights:
                line += f" | {highlights[0]}"
            lines.append(line)
        journal_digest = "\n".join(lines)
    # else: leave "" — empty-state rule omits the block entirely
```

**Render step `.replace()` — D-15 ordering** (`:251-256`). Insert `{journal_digest}` AFTER `{self_state}`, BEFORE `{today_date}`. `worker_system` (`:257`) is UNCHANGED — smart-only:
```python
smart_system = (
    self._smart_prompt_template
    .replace("{self_md}", self._self_md_content)
    .replace("{self_state}", self_state_snippet)
    .replace("{journal_digest}", journal_digest)         # NEW — after self_state
    .replace("{today_date}", today_label)
)
worker_system = self._worker_prompt_template.replace("{today_date}", today_label)  # untouched
```

**Companion change — `prompts/smart_agent.md`.** Current file: `{self_md}` line 1, blank line 2, `{self_state}` line 3, blank line 4, `---` line 5. Insert `{journal_digest}` on its own line after `{self_state}` (e.g. new line 4) so the placeholder ordering matches D-15. The worker prompt (`prompts/worker_agent.md`) must NOT gain the placeholder.

---

### `core/tools.py` — `recall` `kind` param + `get_self_status` journal (MOD — utility / tool dispatch)

**Analog:** the `recall` tool's own three registration sites; `search_chat_history` (`_handle_search_chat_history` at `:910`) which already passes a `kinds`-style filter through; `get_self_status`'s existing LLMUsage block (`:1134-1153`) for the journal field.

**1. Schema — `recall` `input_schema.properties` (`tools.py:246-259`).** Add an optional `kind` property alongside `query`/`k`. Do NOT add it to `required` (`:258`) — default fact+chunk behavior unchanged (D-08):
```python
"kind": {
    "type": "string",
    "enum": ["fact", "chunk", "self"],
    "description": ("Optional. Restrict recall to one memory kind. "
                    "'self' searches Klaus's own journal entries. "
                    "Omit for the default fact+chunk search."),
}
```

**2. `_handle_recall` (`tools.py:904-907`)** — add the `kind` param, translate to `kinds`:
```python
def _handle_recall(query: str, k: int = 5, kind: str | None = None) -> str:
    """Delegate to MemoryTool.recall and serialise the result."""
    kinds = [kind] if kind else None        # None → recall() default ["fact","chunk"]
    result = _get_memory_tool().recall(_get_current_user_id(), query, k, kinds=kinds)
    return json.dumps(result)
```

**3. `_HANDLERS` dispatch (`tools.py:1180`)** — `"recall": lambda args: _handle_recall(**args)` already splats kwargs; no change needed (the new `kind` flows through automatically).

**4. Worker exclusion — NO CHANGE NEEDED.** `recall` is already in `SMART_AGENT_DIRECT_TOOLS` (`tools.py:39-48`) and already excluded from `WORKER_TOOL_SCHEMAS` (`tools.py:692-704`). Extending its schema does not touch either list. (The CONTEXT.md "worker-exclusion list" reference at `:697` is the existing exclusion — confirm it stays, no edit.)

**5. `get_self_status` journal field (D-16, `tools.py:1158-1159`)** — replace `result["journal"] = None`. Model on the LLMUsage block directly above it (`:1134-1153`) — env-var guard + `try/except` writing an `_error` key on failure:
```python
# --- Journal (Phase 17) ---
try:
    project_id = _os.environ.get("GCP_PROJECT_ID")
    if project_id:
        database = _os.environ.get("FIRESTORE_DATABASE", "(default)")
        from memory.firestore_db import JournalStore
        recent = JournalStore(project_id=project_id, database=database).get_recent(1)
        if recent:
            j = recent[0]
            result["journal"] = {"date": j.get("date"), "summary": j.get("summary"),
                                 "mood": j.get("mood")}
        else:
            result["journal"] = None
    else:
        result["journal"] = None
except Exception as exc:
    result["journal"] = None
    result["journal_error"] = str(exc)
```

---

### `mcp_tools/memory.py` — `MemoryTool.recall` forwards `kinds` (MOD — utility / tool wrapper)

**Analog:** `MemoryTool.search_chat_history` (`mcp_tools/memory.py:68-87`) — the SIBLING method that ALREADY forwards a `kinds` filter to the underlying store: `self._store.recall(user_id, query, k, kinds=["chat"])` (`:81`).

**The gap (RESEARCH Open Question 2):** D-08's wording ("`recall()` already accepts a `kinds` param") is true only for the lower-level `MemoryStore.recall` (`pinecone_db.py:96`). The agent-facing wrapper `MemoryTool.recall` (`:49-66`) currently has signature `recall(self, user_id, query, k=5)` and does NOT forward `kinds`. The plan MUST touch this file.

**Change** — add an optional `kinds` param mirroring `search_chat_history`'s usage:
```python
def recall(self, user_id: int, query: str, k: int = 5,
           kinds: list[str] | None = None) -> dict:
    """Search long-term memory and return matches."""
    try:
        matches = self._store.recall(user_id, query, k, kinds=kinds)
    except Exception as exc:
        logger.error("MemoryTool.recall failed: %s", exc)
        return {"error": str(exc), "query": query}
    return {"matches": matches, "count": len(matches)}
```
`MemoryStore.recall` treats `kinds=None` as the default `["fact","chunk"]` (`pinecone_db.py:112`) — passing `None` is safe and preserves current behavior.

---

## Shared Patterns

### Cron-context owner-ID sourcing
**Source:** `core/scheduled_message.py:17-19`
**Apply to:** `core/reflection.py` (Pinecone `remember_self` scoping, conversation lookup)
```python
def _telegram_user_id() -> int:
    raw = os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip()
    return int(raw)
```
A cron has no Telegram request `user_id`; this is the established cron-context pattern and matches the scoping that fact/chunk Pinecone memories already use.

### Firestore client construction
**Source:** `memory/firestore_db.py:24-40` (`_make_firestore_client`); cron-context wrapper at `proactive_alerts.py:80-84`
**Apply to:** `core/reflection.py` and the new `JournalStore`
Never hand-roll credential logic — `_make_firestore_client` handles `FIRESTORE_CREDENTIALS` vs ADC. `JournalStore.__init__` calls it directly (like `AttendanceStore`/`SelfStateStore`); `core/reflection.py` re-imports it via the `proactive_alerts` wrapper shape.

### Firestore Store error discipline
**Source:** `SelfStateStore` (`firestore_db.py:620-646`)
**Apply to:** `JournalStore`
Reads (`get`, `get_recent`) catch `Exception`, log a warning, return `{}`/`None`/`[]` — never raise (these feed prompt assembly). Writes (`set`) log an error and re-raise (the caller decides). One divergence: `JournalStore.set` uses `.set()` WITHOUT `merge=True` (D-12 overwrite), unlike `SelfStateStore.set`/`AttendanceStore.upsert_practice` which patch.

### Cron-context LLM call + deterministic fallback
**Source:** `core/proactive_alerts.py:334-392` (`_compose_alert` + `_plain_text_fallback`); `core/morning_briefing.py:240-267`
**Apply to:** `core/reflection.py` (worker summary call, brain reflection call)
Construct a fresh `LLMClient` inline from env vars — NEVER import `AgentOrchestrator` to reach its clients. `LLMClient.chat()` auto-meters cost (`llm_client.py:105-125`); pass `purpose="reflect"` / `"reflect_summary"`. On total LLM failure, fall through to a deterministic non-LLM path (D-13 minimal journal doc).

### Cron route shape (OIDC → run → ledger)
**Source:** `cron_proactive_alerts` (`web_server.py:310-331`); executor variant `cron_ingest_chats` (`:381-404`)
**Apply to:** `/cron/reflect`
`await _verify_cron_request(request)` first → `try:` run logic + `_log_cron_run(job_id, ok=True)` → `except:` `_log_cron_run(job_id, ok=False); raise`. For synchronous work, `await loop.run_in_executor(None, fn, arg)`.

### Prompt-template placeholder substitution
**Source:** `core/main.py:251-256` render step; `proactive_alerts.py:340-342` file-load `.replace`
**Apply to:** `core/main.py` (`{journal_digest}`), `core/reflection.py` (`reflection.md` `{today_date}`)
Plain `.replace("{placeholder}", value)`. Placeholder ordering matters for Gemini prompt caching: stable content first, dynamic (`{today_date}`) last. New `{journal_digest}` sits between `{self_state}` and `{today_date}`.

---

## No Analog Found

No new file is fully analog-less, but two pieces of logic are genuinely new and have no copy-from source — the planner should treat them as net-new code guided by RESEARCH.md:

| Logic | Location | Reason |
|-------|----------|--------|
| `_parse_reflection_json(text)` JSON-hardening helper | `core/reflection.py` | First cron needing structured LLM output. `proactive_alert.md`/`morning_briefing.md` prompts ask for prose — no parse helper exists. See RESEARCH Pitfall 3 for the required shape (strip ```json fences, slice `{`…`}`, validate 5 keys/types, default missing). |
| 3-day rolling `recent_context` window (D-05) | `core/reflection.py` (writes to `SelfStateStore.set`) | `SelfStateStore.set` (`firestore_db.py:634`) is a generic merge-patch — no append-and-trim list logic exists anywhere. New code: read current `recent_context`, append latest, trim to 3 entries. |

---

## Metadata

**Analog search scope:** `core/` (`proactive_alerts.py`, `morning_briefing.py`, `scheduled_message.py`, `main.py`, `tools.py`, `llm_client.py`, `heartbeat.py`), `memory/` (`firestore_db.py`, `pinecone_db.py`), `interfaces/web_server.py`, `mcp_tools/memory.py`, `prompts/`
**Files scanned:** 12 source files + `prompts/` listing + `.env.example`
**Line numbers verified against live code on:** 2026-05-19 (matches RESEARCH.md citations; RESEARCH-noted corrections confirmed — Pinecone class is `MemoryStore` not `PineconeStore`; `recall()` at `pinecone_db.py:96`, `kinds` default at `:112`)
**Pattern extraction date:** 2026-05-19
