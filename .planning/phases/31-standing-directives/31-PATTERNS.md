# Phase 31: Standing Directives - Pattern Map

**Mapped:** 2026-07-19
**Files analyzed:** 17 (11 source/prompt files + 6 test files)
**Analogs found:** 17 / 17

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `memory/firestore_db.py` (+`StandingDirectiveStore`) | model/store | CRUD | `FollowupStore` (same file, lines 1656-1815) | exact |
| `memory/firestore_conversation.py` (+`get_recent_window`, +`ts`) | model/store | CRUD / batch-read | `FirestoreConversationStore.get`/`get_full` (same file, lines 120-166) | exact |
| `core/tools.py` (+3 tool schemas/handlers, +`render_standing_directives_block`) | controller (tool dispatch) | request-response | `schedule_followup`/`list_followups`/`cancel_followup` (lines 826-861, 1998-2079, 2852-2854) | exact |
| `core/main.py` (`render_smart_system` +placeholder) | service (template render) | transform | Existing `.replace()` chain (lines 519-528) | exact |
| `core/autonomous.py` (+`_gather_standing_directives`, wiring) | service (gather + compose) | event-driven / batch | `_gather_due_followups` (lines 320-328) + `_format_now_block` (lines 669-683) | exact |
| `core/nightly_review.py` (`_gather_tomorrow` + `_compose_nightly` veto) | service (cron compose) | batch / request-response | Existing `_gather_tomorrow`/`_compose_nightly` (lines 165-291) | role-match |
| `core/morning_briefing.py` (`_gather_data` + skip-verdict) | service (cron compose) | batch / request-response | Existing `_gather_data`/`run_morning_briefing`/`_compose_briefing` (lines 122-330) + `_parse_followup_action` (autonomous.py:799-831) | role-match |
| `core/reflection.py` (`_gather_day` swap + reaction pairing) | service (nightly batch) | batch / transform | Existing `_gather_day`/`_brain_reflect`/`_parse_reflection_json` (lines 51-350) | exact |
| `prompts/smart_agent.md` (+capture rule, +placeholder) | config (prompt) | — | "SELF-SCHEDULED FOLLOW-UPS" section (lines 334-349) | exact |
| `prompts/autonomous_triage.md` (+Step-0 veto, +inputs line) | config (prompt) | — | "Decision procedure" Step 1 header (lines 163-168) + Inputs block (lines 43-60) | exact |
| `prompts/reflection.md` (+3 optional JSON keys) | config (prompt) | — | Existing "Output Format" 5-key schema (lines 23-41) | exact |
| `tests/test_firestore_db.py` (+`TestStandingDirectiveStore`) | test | CRUD | `TestFollowupStore` (lines 189-278+) | exact |
| `tests/test_tools.py` (+3 handler tests) | test | request-response | `TestFollowupTools` + `_FakeFollowupStore`/`fake_store` fixture (lines 1-135+) | exact |
| `tests/test_firestore_conversation.py` (+`get_recent_window` tests) | test | CRUD | Existing 3 tests + `_install_firestore_mock`/`_store_with_doc` helpers (lines 1-93) | exact |
| `tests/test_autonomous.py` (+gather/empty-signal/injection tests) | test | event-driven | `_is_empty_signals`/`due_followups` fixtures (lines 341-445) | exact |
| `tests/test_main_render_smart_system.py` (+`{standing_directives}` placeholder tests) | test | transform | `TestTrainingProfileRendering` class (lines 245-306) | exact — **note: this is the real file, not `tests/test_main.py`** |
| `tests/test_reflection.py` (+reaction-pairing / proposal / veto tests) | test | batch | Existing reflection test structure (802 lines; not re-read in full — extend per `_gather_day`/`_brain_reflect` shape above) | role-match |

## Pattern Assignments

### `memory/firestore_db.py` — add `StandingDirectiveStore`

**Analog:** `FollowupStore` (same file, lines 1656-1815)

**Class + schema docstring pattern** (lines 1656-1685):
```python
class FollowupStore:
    """Persists scheduled follow-ups for Klaus's self-managed check-backs.

    Schema (collection: ``followups/{id}``):
        id: str                # doc-id (uuid4 hex)
        due_at: str            # ISO-8601 UTC — when the follow-up fires
        note: str              # human-readable reminder text
        created_at: str        # ISO-8601 UTC — when scheduled
        status: str            # 'pending' | 'done' | 'cancelled'
        defer_count: int       # incremented each time Klaus defers; force-fire at >=3
        origin: str            # 'user_chat' (user asked) | 'klaus_self' (Klaus scheduled himself)

    Reads (`list_due`, `list_pending`) never raise — they return `[]` on
    Firestore error so the autonomous tick (Plan 06) can keep running even
    when Firestore is briefly unreachable. Writes (`add`, `mark_done`,
    `cancel`, `defer`) re-raise after logging so the caller can decide.

    Phase 18 — AUTO-04, D-12/D-13/D-14/D-15.
    """

    _COLLECTION = "followups"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
```
Copy this shape 1:1 for `StandingDirectiveStore`, collection `standing_directives`, doc schema per RESEARCH.md's Code Examples section (`id`, `text`, `origin`, `context_quote`, `created_at`, `status`, `expires_at`, `condition_text`, `superseded_by`).

**Write pattern (`add`, re-raise after logging)** (lines 1687-1725):
```python
def add(self, due_at: str, note: str, origin: str = "user_chat") -> dict:
    import uuid
    from datetime import datetime, timezone

    fid = uuid.uuid4().hex
    doc = {
        "id": fid, "due_at": due_at, "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "defer_count": 0, "origin": origin,
    }
    try:
        self._col.document(fid).set(doc)
    except Exception:
        logger.error("FollowupStore.add failed (note=%r)", note, exc_info=True)
        raise
    return {"id": fid, "due_at": due_at}
```
For `StandingDirectiveStore.add`, follow the same shape but call `_cache_invalidate_prefix(("standing_directives",))` after the write (see the `_READ_CACHE` pattern below) — `FollowupStore` predates `_READ_CACHE` and does not need this, but the directives store is read on every chat turn + every tick, so it must.

**Read pattern (never-raise, `[]` sentinel)** (lines 1727-1756, `list_due`):
```python
def list_due(self, now_iso: str) -> list[dict]:
    from google.cloud.firestore_v1.base_query import FieldFilter
    try:
        snaps = (
            self._col
            .where(filter=FieldFilter("status", "==", "pending"))
            .where(filter=FieldFilter("due_at", "<=", now_iso))
            .stream()
        )
        return [s.to_dict() for s in snaps]
    except Exception:
        logger.warning("FollowupStore.list_due failed", exc_info=True)
        return []
```
`StandingDirectiveStore.list_active()` follows this exactly, filtering `status == "active"`, but wraps the read in `_cache_get`/`_cache_put` per the `_READ_CACHE` pattern below.

**Status-transition pattern (never hard-delete)** (lines 1792-1814, `cancel`):
```python
def cancel(self, fid: str) -> bool:
    try:
        snap = self._col.document(fid).get()
        if not snap.exists:
            return False
        self._col.document(fid).update({"status": "cancelled"})
        return True
    except Exception:
        logger.error("FollowupStore.cancel(%r) failed", fid, exc_info=True)
        raise
```
Copy for `cancel_standing_directive`; also need `supersede(old_id, new_doc)` (writes `superseded_by` on the old doc — D-16) and `expire(id)` (D-05/D-08) using the identical get-then-update shape. Remember `_cache_invalidate_prefix` after every write.

**`_READ_CACHE` pattern (module-level, already exists — reuse, do not reinvent)** (lines 61-86):
```python
_READ_CACHE: dict[tuple, tuple[float, object]] = {}
_READ_CACHE_TTL_SEC = 600  # 10 minutes

def _cache_get(key: tuple):
    hit = _READ_CACHE.get(key)
    if hit is None:
        return None
    stored_at, value = hit
    if time.monotonic() - stored_at > _READ_CACHE_TTL_SEC:
        _READ_CACHE.pop(key, None)
        return None
    return value

def _cache_put(key: tuple, value) -> None:
    _READ_CACHE[key] = (time.monotonic(), value)

def _cache_invalidate_prefix(prefix: tuple) -> None:
    for key in [k for k in _READ_CACHE if k[: len(prefix)] == prefix]:
        _READ_CACHE.pop(key, None)
```
`StandingDirectiveStore.list_active()` should key its cache entry as `("standing_directives", "active")` and every write method must call `_cache_invalidate_prefix(("standing_directives",))`.

---

### `memory/firestore_conversation.py` — add `get_recent_window()` + per-message `ts`

**Analog:** `get()` / `get_full()` (same file, lines 120-166) + `_txn_append` (lines 33-67)

**Existing `get_full` shape to model `get_recent_window` on** (lines 146-166):
```python
def get_full(self, user_id: int) -> list[dict]:
    doc_ref = self._col.document(str(user_id))
    try:
        snapshot = doc_ref.get()
    except GoogleAPICallError:
        logger.warning(
            "FirestoreConversationStore.get_full failed for user_id=%d; "
            "returning empty history.", user_id,
        )
        return []
    if not snapshot.exists:
        return []
    return list((snapshot.to_dict() or {}).get("messages", []))
```
`get_recent_window(user_id, hours=24, max_messages=60)` follows this exact try/except-then-empty-list shape, then filters `messages` by parsing each `m.get("ts")` (added below) against a `datetime.now(timezone.utc) - timedelta(hours=hours)` cutoff. **Legacy messages without `ts` must be tolerated** (kept by position, not KeyError'd) since every message stored before this phase lacks the field.

**`ts` field addition point in `_txn_append`** (line 54 — currently):
```python
messages.append({"role": role, "content": content})
```
Change to:
```python
messages.append({
    "role": role, "content": content,
    "ts": datetime.now(timezone.utc).isoformat(),  # NEW — per-message timestamp
})
```
`datetime`/`timezone` are already imported at the top of this file (line 21) — no new import needed.

**Existing test fixture pattern to extend** (`tests/test_firestore_conversation.py`, lines 20-93):
```python
def _install_firestore_mock() -> None:
    """Stub google.cloud.firestore + google.api_core.exceptions, then flush
    memory.firestore_conversation so it re-imports against the stubs."""
    ...
    firestore_mock.transactional = lambda fn: fn
    sys.modules["google.cloud.firestore"] = firestore_mock
    ...

def _store_with_doc(doc: dict):
    from memory.firestore_conversation import FirestoreConversationStore
    store = FirestoreConversationStore(project_id="p", database="(default)")
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = doc
    store._col.document.return_value.get.return_value = snap
    return store

def test_get_returns_active_session_window(monkeypatch, isolated_modules):
    monkeypatch.delenv("FIRESTORE_CREDENTIALS", raising=False)
    _install_firestore_mock()
    store = _store_with_doc({"messages": _MSGS, "session_start_index": 2, "updated_at": _RECENT})
    assert store.get(1) == [{"role": "user", "content": "c"}]
```
New `get_recent_window` tests reuse `_install_firestore_mock`/`_store_with_doc`/`isolated_modules` verbatim — just seed `messages` with mixed `ts`-present and `ts`-absent dicts and assert the 24h cutoff + `max_messages` cap + legacy-tolerance behavior.

---

### `core/tools.py` — 3 brain-direct tools + shared formatter

**Analog:** `schedule_followup`/`list_followups`/`cancel_followup` (lines 826-861 schemas, 1998-2079 handlers, 2852-2854 dispatch) + `SMART_AGENT_DIRECT_TOOLS` (lines 40-55) + a second frozenset at lines 1405-1420 (worker-exclusion list — **both** need the 3 new tool names, not just `SMART_AGENT_DIRECT_TOOLS`)

**Direct-tools registration — 3 sites, exact pattern:**
```python
# Site 1 — SMART_AGENT_DIRECT_TOOLS (line 40-55)
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    ...
    # Phase 18 — self-scheduled follow-ups (D-15 / AUTO-05)
    "schedule_followup",
    "list_followups",
    "cancel_followup",
    # Phase 31 — add here: "set_standing_directive", "list_standing_directives", "cancel_standing_directive"
    ...
})

# Site 2 — worker-tool exclusion list (lines 1405-1420) — same 3-name addition
# comment: "Phase 18 — self-scheduled follow-ups (brain-direct only)"
"schedule_followup",
"list_followups",
"cancel_followup",

# Site 3 — _HANDLERS dispatch (lines 2852-2854)
"schedule_followup":       lambda args: _handle_schedule_followup(**args),
"list_followups":          lambda args: _handle_list_followups(),
"cancel_followup":         lambda args: _handle_cancel_followup(**args),
```

**Tool schema pattern** (lines 826-861):
```python
{
    "name": "schedule_followup",
    "description": (
        "Schedule a self-managed check-back. ... "
        "Call this directly — do NOT delegate to the worker."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "when": {"type": "string", "description": "ISO 8601 or natural-language datetime."},
            "note": {"type": "string", "description": "Reminder text — what is this check-back about."},
        },
        "required": ["when", "note"],
    },
},
{
    "name": "list_followups",
    "description": ("List your pending self-scheduled check-backs. ... "
                     "Call directly — no worker delegation."),
    "input_schema": {"type": "object", "properties": {}, "required": []},
},
{
    "name": "cancel_followup",
    "description": ("Cancel a previously scheduled follow-up by id. Idempotent ... Call directly."),
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Follow-up id from list_followups."}},
        "required": ["id"],
    },
},
```
Model `set_standing_directive(text, expires_at?, condition_text?)`, `list_standing_directives(include_history?)`, `cancel_standing_directive(id_or_description)` schemas on this exact shape — same "Call directly — do NOT delegate to the worker" phrasing in the description (this phrasing is load-bearing: it's what the brain's own tool-selection reads).

**Handler pattern** (lines 1998-2079):
```python
def _handle_schedule_followup(when: str, note: str) -> str:
    ...
    from memory.firestore_db import FollowupStore
    store = FollowupStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    result = store.add(due_at=due_iso, note=note, origin="klaus_self")
    return json.dumps(result)

def _handle_list_followups() -> str:
    """Return pending follow-ups, stripped of internal fields."""
    from memory.firestore_db import FollowupStore
    store = FollowupStore(project_id=os.environ["GCP_PROJECT_ID"],
                           database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    pending = store.list_pending()
    stripped = [
        {"id": p.get("id", ""), "due_at": p.get("due_at", ""),
         "note": p.get("note", ""), "defer_count": int(p.get("defer_count", 0))}
        for p in pending
    ]
    return json.dumps(stripped)

def _handle_cancel_followup(id: str) -> str:
    """Cancel a follow-up by id. Idempotent (D-15)."""
    from memory.firestore_db import FollowupStore
    store = FollowupStore(project_id=os.environ["GCP_PROJECT_ID"],
                           database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    ok = store.cancel(id)
    return json.dumps({"ok": bool(ok)})
```
`_handle_set_standing_directive(text, expires_at=None, condition_text=None)` mirrors `_handle_schedule_followup` (origin defaults to `"user_chat"` here, unlike the follow-up's `"klaus_self"` default — capture is user-initiated per DIR-01). Reuse the exact `dateutil` NL-parse try/except block (lines 2019-2028) if `expires_at` arrives as natural language rather than a pre-parsed ISO string — the brain is expected to pass ISO where possible, but defense-in-depth matches the followup precedent.

**Shared formatter pattern** (model on `_format_now_block`, `core/autonomous.py:669-683` — "one helper, ... call sites, no drift"):
```python
def _format_now_block(situation: dict) -> str:
    """Render the ``now_context`` time block shared by triage AND both
    Layer-2 composes. ... One helper, three call sites, no drift.
    """
    nc = situation.get("now_context") or {}
    return (
        f"now: {nc.get('now_local', '')}\n"
        f"tick {nc.get('tick_index', 0)} of {nc.get('tick_total', _TICK_TOTAL_PER_DAY)}\n"
        f"last tick at: {nc.get('last_tick_at', '')}"
    )
```
`render_standing_directives_block(directives, *, style="prose"|"json")` belongs in `core/tools.py` (co-located with the store-reading handlers, since 3 of the 5 call sites are in `core/tools.py`-adjacent modules) OR `core/autonomous.py` next to `_format_now_block` (both are Claude's-discretion per RESEARCH.md; either placement is fine as long as it is ONE function, imported by all 5 call sites — never re-implemented per-site).

**Test fixture pattern to extend** (`tests/test_tools.py`, lines 44-93):
```python
class _FakeFollowupStore:
    instances: list["_FakeFollowupStore"] = []
    def __init__(self, project_id: str, database: str = "(default)") -> None:
        ...
        _FakeFollowupStore.instances.append(self)
    def add(self, due_at: str, note: str, origin: str = "user_chat") -> dict:
        ...

@pytest.fixture
def fake_store(monkeypatch):
    _FakeFollowupStore.instances = []
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")
    import memory.firestore_db as firestore_db
    monkeypatch.setattr(firestore_db, "FollowupStore", _FakeFollowupStore)
    yield _FakeFollowupStore
```
Build a `_FakeStandingDirectiveStore` + `fake_directive_store` fixture on this exact shape — same `instances` class-level tracking, same `monkeypatch.setattr(firestore_db, "StandingDirectiveStore", ...)` pattern, so `_handle_set_standing_directive`/`_handle_list_standing_directives`/`_handle_cancel_standing_directive` tests never touch real Firestore.

---

### `core/main.py` — `{standing_directives}` placeholder

**Analog:** existing `.replace()` chain (lines 519-528), stable-first cache-prefix ordering

**Exact insertion point** (verified live, lines 518-528):
```python
coaching_guide_content = getattr(self, "_coaching_guide_content", "")
return (
    template
    .replace("{coaching_guide}", coaching_guide_content)         # PHASE 22 — stable, first
    .replace("{self_md}", self._self_md_content)                 # stable — benefits from cache
    .replace("{self_state}", self_state_snippet)                 # volatile — after stable
    .replace("{journal_digest}", journal_digest)                 # Phase 17 — smart-only (D-15)
    .replace("{training_profile}", training_profile_snippet)     # PHASE 19 — PROMPT-01
    # INSERT HERE: .replace("{standing_directives}", standing_directives_snippet)  # Phase 31
    .replace("{today_date}", today_label)                        # dynamic — always last
    .replace("{current_time}", _current_time_israel())           # dynamic — per-minute
)
```
Build `standing_directives_snippet` the same way `training_profile_snippet` is built above it (lines 393-516): a guarded block that reads the store, and if non-empty calls `render_standing_directives_block(directives, style="prose")`; if empty, stays `""` (empty-state-omits-block discipline, matching `self_state`/`journal_digest`/`training_profile`).

**Placeholder line in `prompts/smart_agent.md`** (verified, lines 1-13):
```
{coaching_guide}

{self_md}

{self_state}

{journal_digest}

{training_profile}

You are Klaus, Amit's personal AI ... Today is {today_date}.
```
Insert `{standing_directives}` as a new line after `{training_profile}` (line 9) and before the prose paragraph (line 13) containing `{today_date}` — matches the `.replace()` chain ordering exactly.

**Test analog** — `tests/test_main_render_smart_system.py` (NOT `tests/test_main.py` — verify this before writing new tests; RESEARCH.md's citation of `tests/test_main.py` does not match the live file layout):
```python
class TestTrainingProfileRendering:
    def test_training_profile_substituted(self):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = MagicMock()
        orch._user_profile_store.load.return_value = {"athletic_goals": ["5k under 20:00"], "schema_version": 1}
        result = orch.render_smart_system("PRE {training_profile} POST")
        assert "PRE" in result and "POST" in result
        assert "**Coaching reference — Amit's training plan:**" in result

    def test_training_profile_empty_renders_empty(self):
        ...
        result = orch.render_smart_system("X{training_profile}Y")
        assert result.startswith("X") and result.endswith("Y")
        assert "{training_profile}" not in result
```
Add a parallel `TestStandingDirectivesRendering` class using `AgentOrchestrator.__new__` + manual attribute injection (this codebase's established way to unit-test `render_smart_system` without full `AgentOrchestrator.__init__` side effects), PLUS one ordering-assertion test: assert the rendered output places `{standing_directives}` content after the training-profile content and before `{today_date}`'s resolved value (cache-prefix ordering is load-bearing per Pitfall 3 — test the position, not just presence).

---

### `core/autonomous.py` — gather job + 3 wiring points

**Analog:** `_gather_due_followups` (lines 320-328), `_is_empty_signals` (lines 175-220), `gather_situation`'s `jobs` dict (lines 588-615), `_build_triage_prompt` (lines 686-737), `_compose_layer2`/`_compose_followup_layer2` (lines 839-939)

**Gather-job pattern** (lines 320-328):
```python
def _gather_due_followups(now: datetime, project_id: str, database: str) -> list:
    """(d) Due follow-ups."""
    try:
        from memory.firestore_db import FollowupStore
        fs = FollowupStore(project_id=project_id, database=database)
        return fs.list_due(now.astimezone(timezone.utc).isoformat())
    except Exception:
        logger.warning("autonomous: followup gather failed", exc_info=True)
        return []
```
```python
def _gather_standing_directives(project_id: str, database: str) -> list:
    try:
        from memory.firestore_db import StandingDirectiveStore
        sds = StandingDirectiveStore(project_id=project_id, database=database)
        return sds.list_active()
    except Exception:
        logger.warning("autonomous: standing_directives gather failed", exc_info=True)
        return []
```

**Registration in `gather_situation`'s `jobs` dict** (lines 588-615) — add one line:
```python
jobs: dict[str, callable] = {
    "calendar": lambda: _gather_calendar(now),
    ...
    "training_evidence": lambda: _gather_training_evidence(now, project_id, database),
    # Phase 31 — add:
    "standing_directives": lambda: _gather_standing_directives(project_id, database),
}
```

**`_is_empty_signals` MUST exclude the new key** (lines 175-220) — critical per Pitfall 4:
```python
def _is_empty_signals(situation: dict) -> bool:
    if situation.get("ticktick_overdue"):
        return False
    if situation.get("due_followups"):
        return False
    ...
    # NOTE: training_status and acwr are CONTEXT only — not triggers.
    # standing_directives is CONTEXT only too — do NOT add a check for it
    # here; its presence must never flip empty=False (mirrors training_status/acwr).
    ...
    return True
```
Add an explicit code comment at the same location (per Pitfall 4's own recommendation) documenting that `standing_directives` is deliberately absent from this function.

**Wiring into `_build_triage_prompt`** (lines 686-737) — the JSON snapshot + prose blocks pattern:
```python
snap = {
    "calendar": situation.get("calendar", []),
    ...
    "training_evidence": situation.get("training_evidence", {}),
    # Phase 31: "standing_directives": render_standing_directives_block(situation.get("standing_directives", []), style="json"),
}
...
outreach_block = ", ".join(outreach_today) if outreach_today else "(none yet)"
return (
    f"Situation snapshot:\n{snap_json}\n\n"
    ...
    f"Topics I have already raised today:\n{outreach_block}\n"
    # Phase 31: append f"\nActive standing directives:\n{directives_block}\n"
)
```

**Wiring into `_compose_layer2`/`_compose_followup_layer2`** (lines 839-939) — these call `orchestrator.render_smart_system(...)` (lines 863, 918), so **the `{standing_directives}` placeholder added to `core/main.py::render_smart_system` is picked up automatically for these 2 call sites** — no separate wiring needed there beyond the `main.py` change. The `snap_summary`/`snap` JSON dicts built inline in these two functions (lines 870-887, 922-928) should ALSO get a `"standing_directives"` key for parity with `_build_triage_prompt`, following the exact same key-addition pattern shown above.

---

### `core/nightly_review.py` — interim injection (D-21/D-22, nightly EXEMPT)

**Analog:** existing `_gather_tomorrow` (lines 165-216) + `_compose_nightly` (lines 223-291)

**Gather addition** (mirrors the `_gather_calendar`/`_gather_recovery` try/except-per-source shape already in `_gather_tomorrow`):
```python
def _gather_tomorrow(tomorrow_iso: str) -> dict:
    data: dict = {"tomorrow_date": tomorrow_iso}
    ...
    # Phase 31 — standing directives (interim injection, D-21/D-22)
    try:
        from memory.firestore_db import StandingDirectiveStore
        sds = StandingDirectiveStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        data["standing_directives"] = sds.list_active()
    except Exception:
        logger.warning("nightly_review: standing_directives gather failed", exc_info=True)
    return data
```
**D-21 note: nightly is EXEMPT from veto power** — this gather feeds the nightly narrative (D-19/D-20 directive-item weaving: proposals/expiries/prune-flags/scope-questions), it must NOT cause `_compose_nightly` to skip. Only `morning_briefing`/`weekly_review` get skip-verdict power (D-22).

**`_compose_nightly`'s existing LLM-call shape** (lines 251-267) — the `payload` dict construction is where a `"standing_directives"` (or `"directive_items"` per the architecture diagram) key gets added, consumed by `prompts/nightly_review.md` (not directly read in this pass — verify its placeholder ordering against the `{coaching_guide}`/`{today_date}` pattern already used at lines 233-237 before adding a new one):
```python
payload = {
    "today_recap": {"summary": (journal or {}).get("summary", ""), "highlights": (journal or {}).get("highlights", [])},
    "tomorrow": tomorrow,
    # Phase 31: "directive_items": <woven directive context — proposals/expiries/prune-flags/scope-questions from reflection>
}
```

---

### `core/morning_briefing.py` — interim injection + skip-verdict (D-21/D-22)

**Analog:** existing `_gather_data` (lines 265-330+) + `run_morning_briefing` (lines 122-197) + the fenced-JSON-trailer precedent `_parse_followup_action` (`core/autonomous.py:799-831`)

**Gather addition** — same try/except-per-source shape as the existing `nightly` snapshot read (lines 299-307):
```python
# Phase 31 — standing directives with FULL veto power over this cron (D-21).
try:
    from memory.firestore_db import StandingDirectiveStore
    sds = StandingDirectiveStore(project_id=os.environ["GCP_PROJECT_ID"],
                                  database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    data["standing_directives"] = sds.list_active()
except Exception:
    logger.warning("morning_briefing: standing_directives gather failed", exc_info=True)
```

**Skip-verdict parsing precedent** (`core/autonomous.py:799-831`, `_parse_followup_action`):
```python
def _parse_followup_action(text: str) -> tuple[str, str]:
    """Parse the trailing JSON action from a Layer-2 follow-up response.
    Looks for a fenced ``json {"action": "send"|"defer"|"cancel"}`` block.
    """
    import re as _re
    if not text:
        return ("send", "")
    m = _re.search(r"```json\s*(\{.*?\})\s*```", text, _re.DOTALL)
    if not m:
        return ("send", text.strip())
    try:
        obj = json.loads(m.group(1))
        action = str(obj.get("action", "send")).lower()
        if action not in ("send", "defer", "cancel"):
            action = "send"
    except (json.JSONDecodeError, ValueError):
        action = "send"
    polished = text[:m.start()].strip()
    return (action, polished)
```
Per the Open Questions in RESEARCH.md, **reuse this exact fenced-JSON-trailer convention** for D-22's skip verdict: add a `_parse_briefing_skip(text) -> tuple[bool, str]` (looks for `{"skip": true, "reason": "..."}`) rather than inventing a new sentinel shape (e.g. a leading `SKIP:` token). Wire it into `run_morning_briefing` right after `text = _compose_briefing(...)` (line 137): if `skip` is true, log `skipped_by_directive` (distinct from a send failure — per D-22) and return WITHOUT calling `send_and_inject`, WITHOUT the `_set_state(... "structured": ...)` write, WITHOUT the `daily_note`/`daily_note_date` write (per the Open Questions recommendation — keep the hub's `/api/today` falling back to its existing D-06 placeholder rather than surfacing stale structured data from a briefing that didn't fire).

**Existing `structured`/`daily_note` write block that must be SKIPPED on a directive veto** (lines 161-197 — for reference, not to copy, but to know exactly what NOT to run):
```python
_set_state(today_iso, {
    "structured": {
        "events": today_data.get("calendar") or [],
        "tasks_today": (today_data.get("tasks") or {}).get("today", []),
        "tasks_overdue": (today_data.get("tasks") or {}).get("overdue", []),
    },
})
...
_sss.set({"daily_note": _coach_note_one_line, "daily_note_date": today_iso})
```

---

### `core/reflection.py` — fix the stale 6h read + learning loop

**Analog:** existing `_gather_day` (lines 123-197), `_brain_reflect`/`_parse_reflection_json` (lines 51-350)

**THE bug to fix — exact line** (line 158-159, currently):
```python
conv_store = FirestoreConversationStore(project_id=project_id, database=database)
gathered["conversation"] = conv_store.get(user_id) or []
```
Replace with:
```python
conv_store = FirestoreConversationStore(project_id=project_id, database=database)
gathered["conversation"] = conv_store.get_recent_window(user_id, hours=24) or []
```
This is the single most concrete fix in this phase (Pitfall 6 / ARCHITECTURE.md "B3") — verify with a live test seeding `updated_at` >6h in the past and asserting `_gather_day`'s conversation list is non-empty (current behavior returns `[]`).

**JSON-schema-extension pattern** (`_parse_reflection_json`, lines 51-116) — the existing 5-required-keys + `**data` passthrough discipline:
```python
_REQUIRED_STR_KEYS = ("summary", "mood", "current_focus", "recent_context")
_HIGHLIGHTS_KEY = "highlights"
_HIGHLIGHTS_CAP = 5
...
result: dict = {}
for key in _REQUIRED_STR_KEYS:
    val = data.get(key)
    result[key] = val if isinstance(val, str) else ""
highlights = data.get(_HIGHLIGHTS_KEY)
if not isinstance(highlights, list):
    highlights = []
highlights = [str(h) for h in highlights if h is not None][:_HIGHLIGHTS_CAP]
result[_HIGHLIGHTS_KEY] = highlights
return result
```
Per RESEARCH.md's Assumption A3, **re-read this function in full before extending it** — verify it does not reject unknown keys. Add 3 new *optional* keys (`directive_proposals`, `prune_flags`, `expiry_notes`) following the same isinstance-guard-then-default discipline as `highlights` above (each defaults to `[]` if missing or wrong-typed — never raises).

**`_brain_reflect`'s 2-tier LLM-call shape** (lines 280-350, brain then `SMART_AGENT_FALLBACK_*`) is unchanged by this phase — the new reaction-pairing/proposal logic is additional *input* (outreach log + windowed conversation) feeding the SAME brain call, and additional *output* keys parsed by the extended `_parse_reflection_json`, not a second LLM call.

**Reaction-pairing input source** — `OutreachLogStore.get_today()` (`memory/firestore_db.py:1918-1936`):
```python
def get_today(self, date_str: str) -> list[dict]:
    """Return today's `entries` list. Never raises."""
    try:
        snap = self._col.document(date_str).get()
        if not snap.exists:
            return []
        data = snap.to_dict() or {}
        return list(data.get("entries") or [])
    except Exception:
        logger.warning("OutreachLogStore.get_today(%r) failed", date_str, exc_info=True)
        return []
```
Each entry has `{topic_key, time, draft, final, tick_index}` (schema documented at firestore_db.py:1841-1867). `run_reflection` should read `OutreachLogStore.get_today(target_date)` alongside the new `get_recent_window(user_id, hours=24)` conversation read, and pass both into the brain-reflect `user_message` JSON payload (same `json.dumps(brain_input, ...)` pattern already at line 408) for the brain to classify replied/ignored-topic/ignored (D-11) and propose self-directives (D-09/D-10/D-12/D-13/D-14).

**Self-directive write pattern** — reuse `StandingDirectiveStore.add(origin="klaus_self", ...)` from the new store (D-09: active immediately, no pending state) inside `run_reflection`, in the same "isolated try/except per write target" style already used for the 3 existing write targets (JournalStore/Pinecone/SelfStateStore, lines 428-489) — a directive-proposal write failure must be non-fatal to the journal write, matching that section's discipline exactly.

**`prompts/reflection.md`'s existing 5-key schema** (lines 27-39) is the direct analog for the schema-doc addition:
```
The JSON object must have EXACTLY these 5 keys:
{
  "summary": "...", "mood": "...", "current_focus": "...",
  "recent_context": "...", "highlights": ["..."]
}
```
Extend the prose (not "EXACTLY these 5" — reword to "these 5 required keys, plus 3 optional keys when applicable") and add a documented shape for `directive_proposals` (list of `{text, condition_text_or_expires_at, rationale}`), `prune_flags` (list of `{directive_id, reason}`), `expiry_notes` (list of `{directive_id, reason}`) — model the sub-schema prose on the existing `highlights` array documentation style (line 34, 39).

---

### `core/tools.py` / `prompts/smart_agent.md` — capture rule prose

**Analog:** "SELF-SCHEDULED FOLLOW-UPS" section, `prompts/smart_agent.md` lines 334-349

**Existing section to model the new one on:**
```
SELF-SCHEDULED FOLLOW-UPS
You can manage your own check-backs with three brain-direct tools (never via delegate_to_worker):

schedule_followup — set a reminder for yourself:
- When Amit asks you to follow up later, OR when you decide a check-back is warranted, call schedule_followup(when, note).
- `when` accepts ISO 8601 ("2026-05-21T15:00:00+00:00") or natural language ("tomorrow 3pm", "next monday 10am").
...

list_followups — inspect what's pending:
- Returns id, due_at, note, defer_count for each pending follow-up.

cancel_followup — drop a follow-up:
- Idempotent. Use when Amit says "forget that reminder" or when you determine it's no longer relevant.
```
Insert a new `STANDING DIRECTIVES` section in this exact style immediately after it (before `CAPABILITY MANIFEST`, line 351), covering: liberal-capture judgment (D-01), the ack format ("Standing order, Sir: …" echo + duration read-back, D-02), the "I already told you…" trigger (D-03, verbatim-restatement-not-history-digging), the conditionless-capture soft-ask (D-06), persona-conflict resolution in the same exchange (D-16), and the security constraint from RESEARCH.md's threat table: **capture is scoped to live conversational turns from Amit only — never to tool-read content** (Gmail bodies, Notion pages, ingested chat-log summaries) that happens to contain imperative-sounding text.

---

## Shared Patterns

### Sentinel-on-failure gather isolation
**Source:** `core/autonomous.py:233-553` (every `_gather_*` function)
**Apply to:** `_gather_standing_directives` (autonomous.py), the directives read added to `core/nightly_review.py::_gather_tomorrow`, and `core/morning_briefing.py::_gather_data`
```python
try:
    ...
except Exception:
    logger.warning("autonomous: <source> gather failed", exc_info=True)
    return []   # or {} / "" / None — typed sentinel matching the field's normal shape
```

### `_READ_CACHE` module-level cache (read-heavy Firestore path)
**Source:** `memory/firestore_db.py:61-86`
**Apply to:** `StandingDirectiveStore.list_active()` — read on every chat turn + 43 ticks/day; every write path (`add`/`cancel`/`supersede`/`expire`) must call `_cache_invalidate_prefix(("standing_directives",))`.

### Render-once shared formatter ("one helper, N call sites, no drift")
**Source:** `core/autonomous.py:669-683` (`_format_now_block`)
**Apply to:** `render_standing_directives_block(directives, *, style="prose"|"json")` — the ONE function consumed by all 5 injection sites (chat, triage, Layer-2 compose, follow-up compose, interim legacy-cron). This codebase already hit the "N independent formatters" failure mode once; do not repeat it.

### Write-after-send discipline
**Source:** `core/nightly_review.py::run_nightly` (lines 373-384, `_set_state(... "status": "sent" ...)` AFTER `send_and_inject`) and `memory/firestore_db.py::OutreachLogStore.append` (gated on send success per CLAUDE.md invariant)
**Apply to:** `core/morning_briefing.py`'s D-22 skip-verdict handling — the `skipped_by_directive` log entry (and the deliberate ABSENCE of the `structured`/`daily_note` writes) happens in place of the normal write-after-send block, not alongside it.

### Fenced-JSON-trailer parsing (LLM emits a message + a machine-readable verdict in one call)
**Source:** `core/autonomous.py:799-831` (`_parse_followup_action`)
**Apply to:** `core/morning_briefing.py`'s D-22 skip-verdict parse (`_parse_briefing_skip`) and (per D-22) `core/nightly_review.py`'s composer if it also needs a machine-readable directive-housekeeping signal distinct from the narrative text.

### Never-raise reads / re-raise writes
**Source:** `FollowupStore` throughout (`memory/firestore_db.py:1656-1815`), `OutreachLogStore` throughout (lines 1841-1953)
**Apply to:** Every method on the new `StandingDirectiveStore`.

### Test double + fixture pattern for Firestore-backed stores
**Source:** `tests/test_tools.py:44-93` (`_FakeFollowupStore` + `fake_store` fixture), `tests/test_firestore_conversation.py:20-53` (`_install_firestore_mock` + `_store_with_doc`)
**Apply to:** `tests/test_tools.py`'s 3 new directive-tool handler tests, `tests/test_firestore_db.py`'s `TestStandingDirectiveStore`, `tests/test_firestore_conversation.py`'s `get_recent_window` tests.

## No Analog Found

None. Every file this phase touches has a live, directly-comparable sibling already in the codebase — this was independently confirmed by RESEARCH.md's own "Don't Hand-Roll" table ("Every mechanical piece of this phase ... has a live, working sibling elsewhere in this exact codebase"). The one genuinely novel piece — the reflection learning loop's reaction-classification judgment (replied/ignored-topic/ignored) and the self-directive-proposal prompt engineering — has no comparable production reference system, but it is prompt-engineering work inside the existing `_brain_reflect`/`prompts/reflection.md` mechanism (an exact structural analog), not a new architectural pattern.

## Metadata

**Analog search scope:** `memory/firestore_db.py`, `memory/firestore_conversation.py`, `core/tools.py`, `core/main.py`, `core/autonomous.py`, `core/nightly_review.py`, `core/morning_briefing.py`, `core/reflection.py`, `prompts/smart_agent.md`, `prompts/autonomous_triage.md`, `prompts/reflection.md`, `tests/test_firestore_db.py`, `tests/test_tools.py`, `tests/test_firestore_conversation.py`, `tests/test_autonomous.py`, `tests/test_main_render_smart_system.py`
**Files scanned:** 16 (all read directly via `Read`/targeted offsets, all line numbers verified against the live 2026-07-19 codebase, not inferred from RESEARCH.md alone)
**Pattern extraction date:** 2026-07-19
**Correction to RESEARCH.md:** RESEARCH.md's test map cites `tests/test_main.py` for the `{standing_directives}` placeholder-ordering test; the live placeholder tests actually live in `tests/test_main_render_smart_system.py` (confirmed by direct read + grep). Planner should target that file, not `tests/test_main.py`.
