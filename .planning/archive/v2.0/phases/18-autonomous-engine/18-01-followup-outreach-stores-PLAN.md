---
phase: 18-autonomous-engine
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - memory/firestore_db.py
  - requirements.txt
  - tests/test_firestore_db.py
autonomous: true
requirements: [AUTO-03, AUTO-04]
requirements_addressed: [AUTO-03, AUTO-04]

must_haves:
  truths:
    - "FollowupStore.add() persists a follow-up doc with status='pending', defer_count=0"
    - "FollowupStore.list_due(now) returns only docs with status=='pending' AND due_at<=now"
    - "FollowupStore.mark_done(id), cancel(id), defer(id, new_due_at) transition state correctly"
    - "OutreachLogStore.append(date, entry) atomically appends entry via firestore.ArrayUnion"
    - "OutreachLogStore.topics_today(date) returns the list of topic_keys for that date (empty list if no doc)"
    - "TickLogStore.write(date, time, snapshot, decision) wraps the tick_logs/{date}/ticks/{HH:MM} write that Plan 06's _write_tick_log needs (NOTE 1) — wrapping it keeps the JournalStore/SelfStateStore/FollowupStore pattern consistent across stores"
    - "All store reads return [] / {} / None on Firestore error and never raise; writes raise after logging (except TickLogStore.write which is best-effort and never raises — matches Plan 06's '_write_tick_log never raises' contract)"
    - "OutreachLogStore.append docstring warns future devs NOT to include SERVER_TIMESTAMP inside the entry dict — ArrayUnion compares list elements by deep equality, and a server-timestamp sentinel would break entry de-duplication (NOTE 2)"
    - "python-dateutil is installed and importable (`from dateutil import parser`)"
  artifacts:
    - path: "memory/firestore_db.py"
      provides: "FollowupStore class (~7 methods) + OutreachLogStore class (~4 methods) + TickLogStore class (~1 method)"
      contains: "class FollowupStore"
    - path: "memory/firestore_db.py"
      provides: "OutreachLogStore class"
      contains: "class OutreachLogStore"
    - path: "memory/firestore_db.py"
      provides: "TickLogStore class (NOTE 1)"
      contains: "class TickLogStore"
    - path: "tests/test_firestore_db.py"
      provides: "FollowupStore + OutreachLogStore + TickLogStore unit tests"
      contains: "test_followup_store"
    - path: "requirements.txt"
      provides: "python-dateutil dependency"
      contains: "python-dateutil"
  key_links:
    - from: "FollowupStore.list_due"
      to: "Firestore composite index on (status, due_at)"
      via: ".where(FieldFilter('status', '==', 'pending')).where(FieldFilter('due_at', '<=', now_iso))"
      pattern: "FieldFilter.*status.*FieldFilter.*due_at"
    - from: "OutreachLogStore.append"
      to: "firestore.ArrayUnion atomic list append"
      via: ".set({entries: ArrayUnion([entry])}, merge=True)"
      pattern: "ArrayUnion"
    - from: "TickLogStore.write"
      to: "core/autonomous.py:_write_tick_log (Plan 06)"
      via: "tick_logs/{date}/ticks/{HH:MM} sub-collection write — best-effort, never raises"
      pattern: "tick_logs"
---

<objective>
Create the three Firestore stores that back the autonomous engine: `FollowupStore`
(scheduled check-backs), `OutreachLogStore` (per-day record of every
escalated send for repeat-suppression context), and `TickLogStore` (per-tick
snapshot for retroactive eval-fixture labeling — NOTE 1 wrapper). Also add
`python-dateutil` to `requirements.txt` (verified absent) so downstream tool
handlers can parse natural-language `when` values per D-12.

Purpose: AUTO-04 mandates `FollowupStore` for scheduled follow-ups; AUTO-03 mandates
`outreach_log/{date}` for repeat-suppression. Both must follow the established
Firestore-store contract (never-raise reads, raise-on-writes) so that downstream
callers in `core/autonomous.py` (Plan 06) and `core/tools.py` (Plan 02) can rely on
deterministic returns.

**NOTE 1 fix:** Plan 06's `_write_tick_log` was previously going to call
`memory.firestore_db._make_firestore_client` directly (using a private helper
from outside the module). That breaks the convention every other Phase 18 store
follows — JournalStore, SelfStateStore, FollowupStore, OutreachLogStore all wrap
their persistence in a class. Adding a tiny `TickLogStore` class here keeps the
pattern consistent and lets Plan 06's executor `from memory.firestore_db import
TickLogStore` rather than reach into a private helper.

**NOTE 2 fix:** OutreachLogStore.append's docstring includes an explicit warning
against passing a `SERVER_TIMESTAMP` sentinel inside the `entry` dict. ArrayUnion
compares entries by deep equality, and a server-timestamp sentinel breaks
equality (each call generates a different sentinel object), which would defeat
the atomic-append-without-duplicates semantic. The `updated_at` field belongs
at the document level (already in the doc body), NOT inside individual entries.

Output: Three new classes in `memory/firestore_db.py`, extended test coverage in
`tests/test_firestore_db.py`, and `python-dateutil>=2.8.2` pinned in
`requirements.txt`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/18-autonomous-engine/18-CONTEXT.md
@.planning/phases/18-autonomous-engine/18-RESEARCH.md
@.planning/phases/18-autonomous-engine/18-PATTERNS.md
@docs/CODING_STANDARDS.md

<interfaces>
<!-- The patterns below MUST be followed verbatim from the existing codebase. -->

From memory/firestore_db.py (existing store contract — replicate exactly):

```python
# JournalStore at line 671 — analog for date-keyed reads
class JournalStore:
    _COLLECTION = "journal"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

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

    def set(self, date_str: str, entry: dict) -> None:
        try:
            self._col.document(date_str).set(
                {**entry, "date": date_str, "updated_at": firestore.SERVER_TIMESTAMP}
            )
        except Exception:
            logger.error("JournalStore.set(%r) failed", date_str, exc_info=True)
            raise
```

From memory/firestore_db.py:314-330 (AttendanceStore.add_pinged_pre — ArrayUnion atomic-append template):

```python
from google.cloud import firestore
try:
    self._col.document(date_str).update({
        "pinged_pre_practice": firestore.ArrayUnion(roster_ids),
    })
except GoogleAPICallError:
    logger.error("AttendanceStore.add_pinged_pre(%r) failed", date_str)
    raise
```

From memory/firestore_db.py:144-159 (RosterStore.list_active — FieldFilter status query template):

```python
from google.cloud.firestore_v1.base_query import FieldFilter
snapshots = (
    self._col
    .where(filter=FieldFilter("active", "==", True))
    .stream()
)
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add python-dateutil to requirements.txt and create FollowupStore class</name>
  <files>requirements.txt, memory/firestore_db.py, tests/test_firestore_db.py</files>
  <read_first>
    - memory/firestore_db.py (read fully — observe existing class layout, _make_firestore_client signature, ArrayUnion usage in AttendanceStore at lines 314-330, FieldFilter usage in RosterStore at lines 144-159, JournalStore at lines 671-761)
    - requirements.txt (verify python-dateutil is absent before adding)
    - tests/test_firestore_db.py (if exists — observe existing test class style; if missing, follow tests/test_reflection.py shape)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (sections: "memory/firestore_db.py (MODIFIED)" and "Never-raise contract on reads")
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-12, D-13, D-14, D-15 — schema details and lifecycle)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "memory/firestore_db.py — two new stores", lines 139-157 for FollowupStore schema)
  </read_first>
  <behavior>
    - Test 1: `FollowupStore.add(due_at="2026-05-21T15:00:00+00:00", note="check on maya")` returns `{"id": <non-empty str>, "due_at": "2026-05-21T15:00:00+00:00"}` and persists a Firestore doc with `status="pending"`, `defer_count=0`, `created_at` set, `origin="user_chat"` (default).
    - Test 2: `FollowupStore.add(..., origin="klaus_self")` persists `origin="klaus_self"`.
    - Test 3: `FollowupStore.list_due(now)` returns only docs where `status == "pending"` AND `due_at <= now_iso`; docs with `status="done"` or `status="cancelled"` are excluded; docs with `due_at > now` are excluded.
    - Test 4: `FollowupStore.list_pending()` returns docs with `status == "pending"` regardless of `due_at`.
    - Test 5: `FollowupStore.mark_done(id)` transitions status to "done".
    - Test 6: `FollowupStore.cancel(id)` transitions status to "cancelled" and is idempotent (calling twice returns True both times).
    - Test 7: `FollowupStore.defer(id, new_due_at)` updates `due_at` to `new_due_at` and increments `defer_count` by 1.
    - Test 8: Firestore error on `.get()` / `.stream()` causes read methods (`list_due`, `list_pending`) to return `[]` not raise.
    - Test 9: Firestore error on `.set()` / `.update()` causes write methods to log and re-raise.
  </behavior>
  <action>
    Step A — requirements.txt: Append after the line containing `python-telegram-bot>=21.0` (or in the appropriate dependency section — find the section by reading the file first), add: `python-dateutil>=2.8.2  # NL datetime parse for schedule_followup (D-12)`. Verify with `grep -n "python-dateutil" requirements.txt` returns 1 hit.

    Step B — memory/firestore_db.py: Append a new class `FollowupStore` after `JournalStore` (after line 761 — read the file to confirm the exact insertion point). Use this exact shape:

    ```python
    class FollowupStore:
        """Persists scheduled follow-ups for Klaus's self-managed check-backs.

        Schema (collection: followups/{id}):
            id: str                           # doc-id (uuid4 hex)
            due_at: str                       # ISO-8601 UTC
            note: str                         # human-readable reminder text
            created_at: str                   # ISO-8601 UTC
            status: str                       # 'pending' | 'done' | 'cancelled'
            defer_count: int                  # incremented each time Klaus defers (force-fire at >=3)
            origin: str                       # 'user_chat' | 'klaus_self'

        Reads never raise (return [] / None on error); writes raise after logging.
        Phase 18 — AUTO-04, D-12/D-13/D-14/D-15.
        """

        _COLLECTION = "followups"

        def __init__(self, project_id: str, database: str = "(default)") -> None:
            self._client = _make_firestore_client(project_id, database)
            self._col = self._client.collection(self._COLLECTION)

        def add(self, due_at: str, note: str, origin: str = "user_chat") -> dict:
            """Insert a new follow-up. Returns {id, due_at}. Raises on Firestore error."""
            import uuid
            from datetime import datetime, timezone
            fid = uuid.uuid4().hex
            doc = {
                "id": fid,
                "due_at": due_at,
                "note": note,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                "defer_count": 0,
                "origin": origin,
            }
            try:
                self._col.document(fid).set(doc)
            except Exception:
                logger.error("FollowupStore.add failed (note=%r)", note, exc_info=True)
                raise
            return {"id": fid, "due_at": due_at}

        def list_due(self, now_iso: str) -> list[dict]:
            """Return pending follow-ups with due_at <= now_iso. Never raises."""
            # NOTE: requires composite index on (status, due_at) — see docs/DEPLOYMENT.md (Plan 09 §Firestore Composite Indexes).
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

        def list_pending(self) -> list[dict]:
            """Return all pending follow-ups (regardless of due_at). Never raises."""
            from google.cloud.firestore_v1.base_query import FieldFilter
            try:
                snaps = (
                    self._col
                    .where(filter=FieldFilter("status", "==", "pending"))
                    .stream()
                )
                return [s.to_dict() for s in snaps]
            except Exception:
                logger.warning("FollowupStore.list_pending failed", exc_info=True)
                return []

        def mark_done(self, fid: str) -> None:
            """Mark a follow-up as done. Raises on Firestore error."""
            try:
                self._col.document(fid).update({"status": "done"})
            except Exception:
                logger.error("FollowupStore.mark_done(%r) failed", fid, exc_info=True)
                raise

        def cancel(self, fid: str) -> bool:
            """Mark a follow-up as cancelled. Idempotent — returns True even if already cancelled.

            Returns False only if the doc does not exist; does not raise on already-cancelled.
            """
            try:
                snap = self._col.document(fid).get()
                if not snap.exists:
                    return False
                self._col.document(fid).update({"status": "cancelled"})
                return True
            except Exception:
                logger.error("FollowupStore.cancel(%r) failed", fid, exc_info=True)
                raise

        def defer(self, fid: str, new_due_at: str) -> None:
            """Push the due_at forward and increment defer_count. Raises on Firestore error."""
            from google.cloud import firestore
            try:
                self._col.document(fid).update({
                    "due_at": new_due_at,
                    "defer_count": firestore.Increment(1),
                })
            except Exception:
                logger.error("FollowupStore.defer(%r) failed", fid, exc_info=True)
                raise
    ```

    Step C — tests/test_firestore_db.py: If the file does not exist, create it; if it exists, append a new test class. Use mocks for Firestore (mirror the pattern from `tests/test_reflection.py`). Add a test class `TestFollowupStore` with these test methods:
      - `test_add_persists_pending_doc`
      - `test_add_with_origin_klaus_self`
      - `test_list_due_filters_by_status_and_time`
      - `test_list_pending_returns_all_pending`
      - `test_mark_done_updates_status`
      - `test_cancel_idempotent`
      - `test_cancel_nonexistent_returns_false`
      - `test_defer_uses_firestore_increment`
      - `test_list_due_returns_empty_on_firestore_error`
      - `test_add_raises_on_firestore_error`

    No "v1" / "simplified" / placeholder allowed — implement every method fully.
  </action>
  <verify>
    <automated>grep -n "python-dateutil" requirements.txt && grep -n "^class FollowupStore" memory/firestore_db.py && pytest tests/test_firestore_db.py::TestFollowupStore -x</automated>
  </verify>
  <done>
    - `grep -n "python-dateutil" requirements.txt` returns exactly 1 line containing `python-dateutil>=2.8.2`
    - `grep -n "^class FollowupStore:" memory/firestore_db.py` returns exactly 1 line
    - `grep -n "composite index" memory/firestore_db.py` returns at least 1 hit (the NOTE comment in `list_due`)
    - All 10 test methods in `TestFollowupStore` pass with `pytest tests/test_firestore_db.py::TestFollowupStore -x`
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add OutreachLogStore class (with NOTE 2 docstring warning) + TickLogStore class (NOTE 1) + tests</name>
  <files>memory/firestore_db.py, tests/test_firestore_db.py</files>
  <read_first>
    - memory/firestore_db.py (review your Task 1 additions; observe `AttendanceStore.add_pinged_pre` at lines 314-330 for `firestore.ArrayUnion` pattern; observe `JournalStore.get` at lines 693-704 for the date-keyed get pattern)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "OutreachLogStore" — the `ArrayUnion` template at lines 308-318)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-07, D-09, D-10, D-21)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (lines 159-170 for OutreachLogStore schema)
  </read_first>
  <behavior>
    OutreachLogStore:
    - Test 1: `OutreachLogStore.append("2026-05-21", {"topic_key": "overdue:reply-to-maya", "time": "14:20", "draft": "Sir, you have...", "final": "Sir...", "tick_index": 22})` uses `.set({..., "entries": firestore.ArrayUnion([entry])}, merge=True)` (atomic — verify via mock call args).
    - Test 2: `OutreachLogStore.get_today("2026-05-21")` returns the entries list for the day; returns `[]` if the doc does not exist.
    - Test 3: `OutreachLogStore.topics_today("2026-05-21")` returns `["overdue:reply-to-maya", "silence:afternoon"]` extracted from the entries list (in order).
    - Test 4: `topics_today` returns `[]` if no doc for that date.
    - Test 5: Firestore error on `.get()` causes `get_today` and `topics_today` to return `[]` (never raises).
    - Test 6: Firestore error on `.set()` causes `append` to log and re-raise.
    - Test 7 (NEW — NOTE 2 regression guard): the OutreachLogStore.append docstring contains a warning about SERVER_TIMESTAMP inside entry dicts. Implement as `assert "SERVER_TIMESTAMP" in OutreachLogStore.append.__doc__` — guards against a future dev removing the warning.

    TickLogStore (NOTE 1):
    - Test 8: `TickLogStore.write("2026-05-21", "14:20", {"calendar": [], ...}, {"sent": True, "trail": [...]})` writes to `tick_logs/{date}/ticks/{HH:MM}` with `captured_at`, `situation_snapshot`, `decision_trail` fields.
    - Test 9: Firestore error on the underlying `.set()` is swallowed (best-effort — never raises). Verify the test by making the mocked Firestore raise and asserting `TickLogStore().write(...)` returns None without propagating.
  </behavior>
  <action>
    Step A — memory/firestore_db.py: Append `OutreachLogStore` and then `TickLogStore` after `FollowupStore`. Use this exact shape:

    ```python
    class OutreachLogStore:
        """Per-day record of autonomous outreach sends for repeat-suppression context.

        Schema (collection: outreach_log/{YYYY-MM-DD}):
            date: str                              # YYYY-MM-DD (also the doc id)
            entries: list[dict]                    # each entry = {topic_key, time, draft, final, tick_index}
            updated_at: SERVER_TIMESTAMP           # doc-level only — set by append(), NOT inside entries

        D-07 — topic_key from tick-brain JSON output.
        D-09 — daily reset: new date key = fresh doc.
        D-10 — written only after send_and_inject succeeds (caller responsibility).
        Reads never raise; writes raise after logging.
        Phase 18 — AUTO-03.

        NOTE 2 — DO NOT include `firestore.SERVER_TIMESTAMP` (or any other sentinel
        value) inside the `entry` dict you pass to `append()`. ArrayUnion compares
        list elements by deep equality, and each SERVER_TIMESTAMP sentinel is a new
        object — so two ticks emitting the "same" entry with embedded sentinels
        would NOT de-duplicate, defeating the atomic-append semantics. Keep
        `updated_at` at the document level (handled inside append) and use static
        ISO strings (`"time": "HH:MM"`) inside entries.
        """

        _COLLECTION = "outreach_log"

        def __init__(self, project_id: str, database: str = "(default)") -> None:
            self._client = _make_firestore_client(project_id, database)
            self._col = self._client.collection(self._COLLECTION)

        def append(self, date_str: str, entry: dict) -> None:
            """Atomically append entry to today's outreach_log doc. Raises on error.

            Uses firestore.ArrayUnion so concurrent ticks cannot clobber each other.

            NOTE 2 — `entry` MUST NOT contain `firestore.SERVER_TIMESTAMP` sentinels.
            ArrayUnion deep-equality comparison treats each sentinel object as
            distinct, breaking de-duplication. Use static ISO strings (e.g.
            `"time": "14:20"`) instead. The doc-level `updated_at` set below is
            the only place SERVER_TIMESTAMP appears.
            """
            from google.cloud import firestore
            try:
                self._col.document(date_str).set(
                    {
                        "date": date_str,
                        "entries": firestore.ArrayUnion([entry]),
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
            except Exception:
                logger.error("OutreachLogStore.append(%r) failed", date_str, exc_info=True)
                raise

        def get_today(self, date_str: str) -> list[dict]:
            """Return today's entries list. Returns [] on missing doc or Firestore error. Never raises."""
            try:
                snap = self._col.document(date_str).get()
                if not snap.exists:
                    return []
                data = snap.to_dict() or {}
                return list(data.get("entries") or [])
            except Exception:
                logger.warning("OutreachLogStore.get_today(%r) failed", date_str, exc_info=True)
                return []

        def topics_today(self, date_str: str) -> list[str]:
            """Return today's list of topic_keys (in entry order). Never raises."""
            entries = self.get_today(date_str)
            return [str(e.get("topic_key", "")) for e in entries if e.get("topic_key")]


    class TickLogStore:
        """Per-tick snapshot writer — supports retroactive eval-fixture labeling.

        Schema (collection: tick_logs/{YYYY-MM-DD}/ticks/{HH:MM}):
            captured_at: str                       # ISO-8601 UTC
            situation_snapshot: dict               # the gather_situation output (minus 'empty')
            decision_trail: dict                   # the run_autonomous_tick decision dict

        Best-effort writes: NEVER raises. Matches Plan 06's contract for
        `_write_tick_log`. Used downstream by the retroactive-labeling workflow
        documented in `evals/tick_brain/README.md` (Plan 04).

        Phase 18 — D-21 (Claude's discretion: per-tick logging for eval fixture growth).

        NOTE 1 — added in Plan 01 (rather than calling `_make_firestore_client` from
        Plan 06's `_write_tick_log`) to keep the JournalStore/SelfStateStore/
        FollowupStore/OutreachLogStore wrapper-class pattern consistent across stores.
        """

        _COLLECTION = "tick_logs"

        def __init__(self, project_id: str, database: str = "(default)") -> None:
            self._client = _make_firestore_client(project_id, database)
            self._col = self._client.collection(self._COLLECTION)

        def write(self, date_str: str, tick_time: str, situation: dict, decision: dict) -> None:
            """Write one tick's snapshot. Best-effort — swallows all exceptions.

            Args:
                date_str: YYYY-MM-DD (Israel time) — top-level doc id under tick_logs.
                tick_time: HH:MM (Israel time) — sub-collection doc id under ticks/.
                situation: gather_situation output (Plan 06).
                decision: run_autonomous_tick decision trail dict (Plan 06).
            """
            from datetime import datetime, timezone
            try:
                self._col.document(date_str).collection("ticks").document(tick_time).set({
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "situation_snapshot": {k: v for k, v in situation.items() if k != "empty"},
                    "decision_trail": decision,
                })
            except Exception:
                logger.warning(
                    "TickLogStore.write(%r, %r) failed (non-fatal)",
                    date_str, tick_time, exc_info=True,
                )
    ```

    Step B — tests/test_firestore_db.py: Append two test classes:
    - `TestOutreachLogStore` with 7 tests (the 6 original + `test_append_docstring_warns_about_server_timestamp` for NOTE 2). The NOTE 2 test shape:
      ```python
      def test_append_docstring_warns_about_server_timestamp(self):
          """NOTE 2 — regression guard: warning must remain in docstring."""
          from memory.firestore_db import OutreachLogStore
          doc = OutreachLogStore.append.__doc__ or ""
          assert "SERVER_TIMESTAMP" in doc, (
              "NOTE 2 regression: OutreachLogStore.append docstring must warn against "
              "passing SERVER_TIMESTAMP inside entry dicts (ArrayUnion equality break)"
          )
      ```
    - `TestTickLogStore` with the 2 tests from the behavior block.

    Step C — Cross-reference for Plan 06 executor: `_write_tick_log` should now use `from memory.firestore_db import TickLogStore` and call `TickLogStore(project_id, database).write(date_str, tick_time, situation, decision)` rather than reach into `_make_firestore_client`. Plan 06's executor will adjust this when implementing `_write_tick_log`.
  </action>
  <verify>
    <automated>grep -n "^class OutreachLogStore" memory/firestore_db.py && grep -n "^class TickLogStore" memory/firestore_db.py && grep -n "ArrayUnion" memory/firestore_db.py && grep -n "SERVER_TIMESTAMP" memory/firestore_db.py && grep -c "NOTE 2" memory/firestore_db.py && pytest tests/test_firestore_db.py::TestOutreachLogStore tests/test_firestore_db.py::TestTickLogStore -x</automated>
  </verify>
  <done>
    - `grep -n "^class OutreachLogStore:" memory/firestore_db.py` returns exactly 1 line
    - `grep -n "^class TickLogStore:" memory/firestore_db.py` returns exactly 1 line (NOTE 1)
    - `grep -nE "ArrayUnion\\(\\[entry\\]\\)" memory/firestore_db.py` returns at least 1 hit (inside `OutreachLogStore.append`)
    - `grep -c "NOTE 2" memory/firestore_db.py` returns at least 1 (NOTE 2 docstring marker)
    - All 9 test methods in `TestOutreachLogStore` (7) + `TestTickLogStore` (2) pass
    - Full test file run: `pytest tests/test_firestore_db.py -x` passes
  </done>
</task>

</tasks>

<verification>
After both tasks complete:
1. `pytest tests/test_firestore_db.py -x` — all FollowupStore + OutreachLogStore + TickLogStore tests pass
2. `grep -c "^class " memory/firestore_db.py` — count is 3 higher than before (FollowupStore + OutreachLogStore + TickLogStore added)
3. `grep -n "python-dateutil" requirements.txt` — 1 hit
4. `python -c "from memory.firestore_db import FollowupStore, OutreachLogStore, TickLogStore; print('OK')"` — prints OK (imports resolve cleanly)
5. `python -c "from dateutil import parser; print(parser.parse('tomorrow 3pm'))"` — prints a datetime (verifies dateutil installed)
6. `grep -c "NOTE 2" memory/firestore_db.py` >= 1 (NOTE 2 warning marker)
</verification>

<success_criteria>
- Three new Firestore-backed classes exist and implement the contracts described in 18-CONTEXT.md D-12/D-13/D-14/D-15 (FollowupStore), D-07/D-09/D-10 (OutreachLogStore), D-21 (TickLogStore).
- All 19 unit tests (10 FollowupStore + 7 OutreachLogStore + 2 TickLogStore) pass.
- `python-dateutil>=2.8.2` is pinned in requirements.txt.
- Composite-index requirement documented inline (comment in `list_due`) and will be ratified in Plan 09 (DEPLOYMENT.md).
- NOTE 1: TickLogStore wrapper class added — Plan 06's `_write_tick_log` will use it instead of the private `_make_firestore_client` helper, keeping the store-wrapper pattern consistent.
- NOTE 2: OutreachLogStore.append docstring warns against SERVER_TIMESTAMP inside entries (regression-guarded by `test_append_docstring_warns_about_server_timestamp`).
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-01-SUMMARY.md` documenting:
- Lines added to `memory/firestore_db.py` (FollowupStore + OutreachLogStore + TickLogStore line ranges)
- Test class additions in `tests/test_firestore_db.py` (call out `test_append_docstring_warns_about_server_timestamp` — NOTE 2 regression guard)
- `python-dateutil>=2.8.2` line in requirements.txt
- Flag: composite Firestore index `(status, due_at)` on `followups` may need first-deploy creation — to be documented in Plan 09 DEPLOYMENT.md
- NOTE 1 cross-reference: Plan 06's executor should `from memory.firestore_db import TickLogStore` rather than `_make_firestore_client` for tick-log writes.
</output>
