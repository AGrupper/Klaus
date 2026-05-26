# Phase 19: Training Awareness & Nutrition Coaching — Pattern Map

**Mapped:** 2026-05-26
**Files analyzed:** 17 (new + modified)
**Analogs found:** 17 / 17

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `memory/firestore_db.py` :: `UserProfileStore` (fill in stub) | Firestore store | CRUD / merge | `memory/firestore_db.py::SelfStateStore` (lines 613-680) | exact (same singleton-doc + bootstrap pattern) |
| `memory/firestore_db.py` :: `MealStore` (new class) | Firestore store | append + date-partitioned read | `memory/firestore_db.py::JournalStore` (lines 683-773) + `FollowupStore` (776-958) | exact (date-keyed collection, idempotent upsert) |
| `mcp_tools/google_fit_tool.py` (NEW) | API client | request-response (read) | `mcp_tools/calendar_tool.py::GoogleCalendarManager` + `mcp_tools/garmin_tool.py::fetch_garmin_today` | exact (OAuth manager + `googleapiclient.discovery.build`) |
| `mcp_tools/garmin_tool.py` :: `fetch_garmin_training_status` (NEW fn) | API client | request-response | `mcp_tools/garmin_tool.py::fetch_garmin_today` (lines 56-127) | exact (same module, same lib, same auth dance) |
| `mcp_tools/garmin_tool.py` :: `fetch_garmin_activities` (NEW fn) | API client | batch read | `mcp_tools/garmin_tool.py::fetch_garmin_today` | exact |
| `mcp_tools/garmin_tool.py` :: `compute_acwr` (NEW fn) | Pure utility | transform | (no analog — pure-Python math, stdlib only) | no analog — research §Code Examples Ex 3 is the spec |
| `scripts/ingest_garmin_zip.py` (extend) | Ingest script | batch ETL | `scripts/ingest_garmin_zip.py::parse_and_ingest_activities` (lines 202-267) + `parse_and_ingest_wellness` (86-200) | exact (same file — additive `.get()` extraction + ON CONFLICT extension) |
| `core/main.py::render_smart_system` (extend) | Orchestration / prompt wiring | transform | `core/main.py::render_smart_system` (lines 232-283) — same function being extended | exact |
| `core/main.py::AgentOrchestrator.__init__` (extend) | Bootstrap | construct | `core/main.py:224-228` (`_build_self_state_store` + `bootstrap_if_empty`) | exact |
| `core/autonomous.py::gather_situation` (extend) | Orchestration | aggregate fan-out | `core/autonomous.py:201-318` (sources a-h) | exact (add sources i, j, k following same try/except pattern) |
| `core/autonomous.py::_is_empty_signals` (extend) | Gate | predicate | `core/autonomous.py:167-184` | exact |
| `core/autonomous.py::_build_triage_prompt` (extend) | Prompt | render | `core/autonomous.py:353-396` | exact (JSON snapshot extension) |
| `core/morning_briefing.py::_gather_data` (extend) | Orchestration | aggregate | `core/morning_briefing.py:174-230` (5 sources) | exact (add nutrition source + Postgres writeback) |
| `core/tools.py` registration (5 new tools) | Schema + dispatch | request-response | `core/tools.py` Phase-18 followup registration (frozenset L39-52, schemas L58-746, worker exclude L750-766, handlers L1255-1333, _HANDLERS L1340-1372) | exact |
| `core/tools.py` :: `_handle_get_training_profile` + 4 siblings (NEW) | Tool handler | request-response | `core/tools.py::_handle_list_followups` (lines 1297-1318) + `_handle_schedule_followup` (1255-1294) + `_handle_cancel_followup` (1321-1333) | exact (same env-driven store construction + `json.dumps` return) |
| `core/self_manifest.py` (no code change) | Manifest generator | derived | already auto-derives from `core/tools.py` schema names via `_compute_schema_hash` (lines 49-78) | exact (no edits — re-run script post-deploy) |
| `prompts/smart_agent.md` (extend) | Prompt | template | same file (existing `{self_md}`, `{self_state}`, `{journal_digest}` placeholders) | exact (add `{training_profile}` + new section) |
| `prompts/autonomous_triage.md` (extend) | Prompt | template | same file (existing trigger sections) | exact |
| `prompts/morning_briefing.md` (extend) | Prompt | template | `prompts/morning_briefing.md` lines 1-60 (section structure) | exact |
| `prompts/meal_audit.md` (NEW) | Prompt | template | `prompts/proactive_alert.md` (40 lines, voice + scope spec) | exact |
| `tests/test_user_profile_store.py` (NEW) | Test | unit | `tests/test_firestore_db.py` (lines 1-100, `_install_firestore_mock` + sys.modules patching) | exact |
| `tests/test_meal_store.py` (NEW) | Test | unit | `tests/test_firestore_db.py` | exact |
| `tests/test_google_fit_tool.py` (NEW) | Test | unit | `tests/test_firestore_db.py` mock pattern + `tests/test_tools.py` patching | exact |
| `tests/test_garmin_extensions.py` (NEW) | Test | unit | (none verified — `tests/test_morning_briefing.py` for Garmin-fetch mocking idiom) | role-match |
| `tests/test_compute_acwr.py` (NEW) | Test | pure unit | (none — but pattern: pure stdlib math, no mocks) | role-match |
| `tests/test_ingest_schema.py` (NEW) | Test | unit | `tests/test_firestore_db.py` mock pattern adapted to psycopg2 mock | role-match |
| `tests/test_ingest_garmin.py` (NEW) | Test | unit | (no existing ingest test — fixture-based JSON dict test) | role-match |
| `tests/test_main_render_smart_system.py` (EXTEND) | Test | unit | same file (lines 1-60) | exact |
| `tests/test_autonomous.py` (EXTEND) | Test | unit | same file (existing gather + triage tests) | exact |
| `tests/test_morning_briefing.py` (EXTEND) | Test | unit | same file (lines 1-50) | exact |
| `tests/test_tools.py` (EXTEND) | Test | unit | same file (followup registration tests) | exact |

---

## Pattern Assignments

### `memory/firestore_db.py::UserProfileStore` (fill in Phase-5 stub)

**Analog:** `memory/firestore_db.py::SelfStateStore` (lines 613-680)

**Class shape** (lines 613-680):
```python
class SelfStateStore:
    _COLLECTION = "config"
    _DOCUMENT = "self_state"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)

    def get(self) -> dict:
        """Returns {} on any error — never raises."""
        try:
            snap = self._doc_ref.get()
            return snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("SelfStateStore.get() failed — returning empty", exc_info=True)
            return {}

    def set(self, patch: dict) -> None:
        """Merge patch. Raises on failure (caller decides). Always appends updated_at SERVER_TIMESTAMP."""
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("SelfStateStore.set() failed", exc_info=True)
            raise

    def bootstrap_if_empty(self, identity_summary: str) -> None:
        """Seed config/self_state if absent. Safe to call on every startup. Never raises."""
        try:
            snap = self._doc_ref.get()
            if snap.exists:
                return
            self._doc_ref.set({
                "identity_summary": identity_summary,
                ...,
                "bootstrapped_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            logger.info("SelfStateStore: bootstrapped config/self_state")
        except Exception:
            logger.warning("SelfStateStore.bootstrap_if_empty() failed — skipping", exc_info=True)
```

**Discipline contract** (matches PROFILE-01/02/03):
- Reads (`load`) NEVER raise — return `{}` on any error.
- Writes (`update`) re-raise after `logger.error(..., exc_info=True)`.
- `bootstrap_if_empty` is a startup safety call — never raises (logs and skips).
- Always stamp `updated_at: firestore.SERVER_TIMESTAMP` with `merge=True`.

**Phase 19 deltas vs analog:**
- `_COLLECTION = "users"`, `_DOCUMENT_ID = "amit"` (not `_DOCUMENT` — name-shape unchanged).
- Scaffold dict is `{"athletic_goals": [], "training_constraints": [], "recovery_preferences": {}, "schema_version": 1}` (no `identity_summary`).
- Rename `get`→`load` and `set`→`update` to honor PROFILE-01/02 wording (the existing stub already uses these names, lines 398-404).

---

### `memory/firestore_db.py::MealStore` (NEW class)

**Analog:** `memory/firestore_db.py::JournalStore` (lines 683-773) — date-keyed collection + safe reads.

**Imports pattern** (lines 12-21):
```python
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)
```

**Constructor + idempotent write** (modeled on `JournalStore.set` lines 726-746):
```python
class MealStore:
    _COLLECTION = "meals"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, source_id: str, meal: dict) -> None:
        """Idempotent on source_id (NUTR-02). Path: meals/{YYYY-MM-DD}/timestamps/{source_id}."""
        try:
            date_str = meal["timestamp"][:10]
            (self._col.document(date_str)
                .collection("timestamps").document(source_id)
                .set({**meal, "source_id": source_id, "updated_at": firestore.SERVER_TIMESTAMP},
                     merge=True))
        except Exception:
            logger.error("MealStore.upsert(%r) failed", source_id, exc_info=True)
            raise
```

**Safe day read** (modeled on `JournalStore.get_recent` lines 748-773):
```python
    def get_day(self, date_str: str) -> list[dict]:
        """Read all meals for a date. Never raises — returns []."""
        try:
            snaps = self._col.document(date_str).collection("timestamps").stream()
            return sorted((s.to_dict() for s in snaps),
                          key=lambda d: d.get("timestamp", ""))
        except Exception:
            logger.warning("MealStore.get_day(%r) failed", date_str, exc_info=True)
            return []
```

**Aggregation method** (no analog — new logic per RESEARCH §MealStore Design):
- Return `{}` (not `{"meal_count": 0}`) when no meals — drives NUTR-07 silent-omit.

---

### `mcp_tools/google_fit_tool.py` (NEW file)

**Primary analog:** `mcp_tools/garmin_tool.py::fetch_garmin_today` (lines 56-127) — same shape: module-level function, lazy import of API lib, custom `*UnavailableError` exception, ISO-date computation in Asia/Jerusalem.

**Secondary analog:** `mcp_tools/calendar_tool.py::GoogleCalendarManager` (lines 27-65) — for the `GoogleAuthManager` plug-in pattern.

**Imports + module header** (from `mcp_tools/garmin_tool.py:1-16`):
```python
"""Google Fit Nutrition tool — Lifesum-sourced meal sync.

Fetches nutrition data points (calories, macros, meal_type) via the
Google Fit REST API. Reuses the shared GoogleAuthManager (Gmail + Calendar)
after operator re-consent for the fitness.nutrition.read scope.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")


class GoogleFitUnavailableError(Exception):
    """Raised when Fit data cannot be fetched (API down, parse error)."""
```

**Service-builder pattern** — copy `mcp_tools/calendar_tool.py:53-65` (lazy service build), but use the env-driven helper used elsewhere:
```python
def _fit_service():
    """Build a Fit v1 service via the shared GoogleAuthManager."""
    from core.auth_google import build_auth_manager_from_env  # lazy import
    manager = build_auth_manager_from_env()
    return build("fitness", "v1", credentials=manager.get_credentials(),
                 cache_discovery=False)
```

**Error-handling contract** (matches `fetch_garmin_today` lines 109-127):
- Wrap `ImportError` of optional libs.
- Wrap auth failure as `GoogleFitUnavailableError`.
- Wrap data fetch/parse failure as `GoogleFitUnavailableError`.
- Per-source-id `try/except` around `datasets().get()` — log + continue (don't fail the whole sync on one bad source).

**`OAuth scope addition site`** — extend `core/auth_google.py:43-44` (verified):
```python
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
# PHASE 19 — read-only nutrition access for Google Fit (Lifesum sync)
FITNESS_NUTRITION_READ_SCOPE = "https://www.googleapis.com/auth/fitness.nutrition.read"
```
And `GoogleAuthManager.SCOPES` (line 192):
```python
SCOPES: list[str] = [GMAIL_SCOPE, CALENDAR_SCOPE, FITNESS_NUTRITION_READ_SCOPE]
```

---

### `mcp_tools/garmin_tool.py` :: `fetch_garmin_training_status` + `fetch_garmin_activities` (NEW functions, same file)

**Analog:** `mcp_tools/garmin_tool.py::fetch_garmin_today` (lines 56-127) — the entire login dance is in the same file.

**Token-cache plumbing** (copy verbatim — lines 27-53):
```python
def _get_garmin_tokens_from_firestore() -> str | None:
    try:
        from memory.firestore_db import _make_firestore_client
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        client = _make_firestore_client(project_id, database)
        snap = client.collection("config").document("garmin_tokens").get()
        if snap.exists:
            return snap.to_dict().get("tokens_json")
    except Exception as e:
        logger.warning("Failed to retrieve Garmin tokens from Firestore: %s", e)
    return None
```

**Auth dance** (lines 79-115) — pull into a private `_authed_garmin_client()` helper as RESEARCH recommends (avoids 3× duplication across `fetch_garmin_today`, `fetch_garmin_training_status`, `fetch_garmin_activities`). Shape:
```python
def _authed_garmin_client():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise GarminAuthError("GARMIN_EMAIL and GARMIN_PASSWORD env vars are required")
    try:
        from garminconnect import Garmin
        api = Garmin(email=email, password=password)
        tokens_json = _get_garmin_tokens_from_firestore()
        ok = False
        if tokens_json:
            try:
                api.login(tokenstore=tokens_json)
                ok = True
            except Exception as exc:
                logger.warning("Garmin token login failed: %s", exc)
        if not ok:
            api.login()
        # persist refreshed tokens
        try:
            new_tokens_json = api.client.dumps()
            if new_tokens_json != tokens_json:
                _save_garmin_tokens_to_firestore(new_tokens_json)
        except Exception as exc:
            logger.warning("Failed to dump tokens: %s", exc)
    except ImportError as exc:
        raise GarminUnavailableError("garminconnect not installed") from exc
    except Exception as exc:
        raise GarminAuthError(f"Garmin login failed: {exc}") from exc
    return api
```

**ISO-date pattern** (line 117):
```python
today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
```

**Final dict + error wrapping** (lines 119-127) — same `try: ... raise GarminUnavailableError(...) from exc` shape.

---

### `mcp_tools/garmin_tool.py::compute_acwr` (NEW pure function)

**No analog** — pure stdlib math, no I/O. Use spec from RESEARCH §Code Examples Ex 3. Reuse the existing module's `ZoneInfo("Asia/Jerusalem")` import (line 14).

---

### `scripts/ingest_garmin_zip.py` (extend in-place)

**Analog:** the same file — extension is additive within existing parsers.

**Schema-DDL extension site** (after line 56):
```python
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS daily_biometrics (...);
CREATE TABLE IF NOT EXISTS activities (...);
CREATE TABLE IF NOT EXISTS laps_telemetry (...);

-- PHASE 19 — additive, idempotent
ALTER TABLE activities ADD COLUMN IF NOT EXISTS training_load REAL;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS perceived_exertion SMALLINT;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS feel SMALLINT;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS vo2_max REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_acute REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_chronic REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS acwr REAL;
"""
```

**Activity parser extension** (lines 232-242 — tuple append):
```python
activities.append((
    activity_id, dt,
    entry.get("activityType", "unknown"),
    int(duration),
    round(float(distance), 2) if distance else None,
    entry.get("averageHeartRate"),
    entry.get("maxHeartRate"),
    entry.get("averagePace"),
    entry.get("trainingEffect"),
    # PHASE 19 ADDITIONS (NULL-safe — keys verified in Deep Research §1)
    entry.get("activityTrainingLoad"),
    entry.get("directWorkoutRpe"),        # was incorrectly "directPerceivedEffort"
    entry.get("directWorkoutFeel"),
))
```

**INSERT ... ON CONFLICT extension** (lines 250-263) — add columns to both column list and `DO UPDATE SET` clause. Same `execute_values` shape.

**UDS parser extension** (lines 140-166) — add `vo2MaxValue` extraction in the same `for entry in data` loop.

**Opportunistic fix** (line 226): replace `psycopg2.tz.FixedOffset(0)` with `datetime.timezone.utc` (deprecated API).

---

### `core/main.py::render_smart_system` (extend lines 232-283)

**Analog:** itself (same function) — `self_state_snippet` (lines 250-259) and `journal_digest` (262-274) blocks already implement the exact pattern.

**Snippet-build pattern** (lines 250-259, copy for `training_profile_snippet`):
```python
self_state_snippet = ""
if self._self_state_store is not None:
    state = self._self_state_store.get()
    non_empty = {k: v for k, v in state.items()
                 if k not in ("updated_at", "bootstrapped_at") and v}
    if non_empty:
        lines = ["**Self-state:**"]
        for key, value in non_empty.items():
            lines.append(f"- {key}: {value}")
        self_state_snippet = "\n".join(lines)
```

**Substitution chain** (lines 277-283) — add a 5th `.replace`:
```python
return (
    template
    .replace("{self_md}", self._self_md_content)
    .replace("{self_state}", self_state_snippet)
    .replace("{journal_digest}", journal_digest)
    .replace("{training_profile}", training_profile_snippet)  # PHASE 19
    .replace("{today_date}", today_label)
)
```

**Bootstrap site** (lines 224-228, copy the pattern):
```python
self._self_state_store = _build_self_state_store()
if self._self_state_store is not None:
    self._self_state_store.bootstrap_if_empty(
        identity_summary=_extract_intro_paragraph(self._self_md_content)
    )

# PHASE 19 — UserProfileStore bootstrap (sibling)
self._user_profile_store = _build_user_profile_store()
if self._user_profile_store is not None:
    self._user_profile_store.bootstrap_if_empty()
```

---

### `core/autonomous.py::gather_situation` (extend lines 187-318)

**Analog:** same function, sources (a)–(h) at lines 219-307.

**Per-source try/except pattern** (extracted from source (a) calendar, lines 219-231):
```python
try:
    from core.tools import _get_calendar_tool
    cal = _get_calendar_tool()
    local = now.astimezone(_TZ)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    gathered["calendar"] = cal.list_events(...) or []
except Exception:
    logger.warning("autonomous: calendar gather failed", exc_info=True)
```

**Apply to 3 new sources (i, j, k)** — insert BEFORE the `gathered["empty"] = _is_empty_signals(gathered)` line at 310:
```python
# (i) Recent meals from Google Fit + MealStore sync — PHASE 19 (NUTR-04)
try:
    from mcp_tools.google_fit_tool import sync_recent_meals
    from memory.firestore_db import MealStore
    ms = MealStore(project_id=project_id, database=database)
    gathered["meals_since_last_tick"] = sync_recent_meals(since_hours=1, store=ms)
except Exception:
    logger.warning("autonomous: meals gather failed", exc_info=True)
    gathered["meals_since_last_tick"] = []

# (j) Garmin training status (live) — PHASE 19
try:
    from mcp_tools.garmin_tool import fetch_garmin_training_status
    gathered["training_status"] = fetch_garmin_training_status() or {}
except Exception:
    logger.warning("autonomous: training_status gather failed", exc_info=True)
    gathered["training_status"] = {}

# (k) ACWR from Postgres — PHASE 19
try:
    from mcp_tools.garmin_tool import compute_acwr_from_db
    gathered["acwr"] = compute_acwr_from_db() or {"ratio": None}
except Exception:
    logger.warning("autonomous: acwr gather failed", exc_info=True)
    gathered["acwr"] = {"ratio": None}
```

**`_is_empty_signals` extension** (lines 167-184):
```python
def _is_empty_signals(situation: dict) -> bool:
    if situation.get("ticktick_overdue"): return False
    if situation.get("due_followups"): return False
    if _calendar_has_gap_or_overload(...): return False
    if situation.get("meals_since_last_tick"): return False  # PHASE 19
    return True
```
(`training_status` and `acwr` are NOT triggers — they're context only.)

---

### `core/morning_briefing.py::_gather_data` (extend lines 174-230)

**Analog:** same function, 5 existing sources.

**Per-source pattern** (lines 211-220 — Garmin block):
```python
try:
    from mcp_tools.garmin_tool import fetch_garmin_today
    garmin = fetch_garmin_today()
    if garmin and garmin.get("date") == today_iso:
        data["garmin"] = {"state": 1, **garmin}
    else:
        data["garmin"] = {"state": 2}
except Exception:
    logger.warning("morning_briefing: Garmin data fetch failed", exc_info=True)
    data["garmin"] = {"state": 2}
```

**Apply to nutrition recap** (NUTR-05, NUTR-07 — silent-omit on empty):
```python
# Yesterday's nutrition recap — PHASE 19 (NUTR-05/07)
try:
    from memory.firestore_db import MealStore
    yesterday = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
    ms = MealStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )
    agg = ms.get_day_aggregate(yesterday)
    if agg:                       # NUTR-07: omit key entirely when empty
        data["nutrition"] = agg
except Exception:
    logger.warning("morning_briefing: meals aggregate failed", exc_info=True)
```

**Postgres biometrics writeback** (GARMIN-05) — best-effort, after existing Garmin block:
```python
try:
    from mcp_tools.garmin_tool import write_today_biometrics_to_postgres
    if data.get("garmin", {}).get("state") == 1:
        write_today_biometrics_to_postgres(data["garmin"])
except Exception:
    logger.warning("morning_briefing: Postgres biometrics writeback failed", exc_info=True)
```

---

### `core/tools.py` — 5 new tool registrations

**Analog:** Phase-18 follow-up tools — covers all 5 required sites.

**Site 1: `SMART_AGENT_DIRECT_TOOLS` frozenset** (lines 39-52):
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "remember", "recall", "run_morning_briefing", "search_chat_history",
    "list_own_files", "read_own_source", "search_own_source", "get_self_status",
    "schedule_followup", "list_followups", "cancel_followup",
    # PHASE 19 — brain-direct only (NOT fetch_* tools)
    "get_training_profile",
    "update_training_profile",
})
```

**Site 2: `TOOL_SCHEMAS` list** — append 5 entries before line 746 closing `]`. Follow the same Anthropic-tool-use shape as lines 58-79 (`list_calendar_events`).

**Site 3: `WORKER_TOOL_SCHEMAS` exclusion** (lines 750-766):
```python
WORKER_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        "delegate_to_worker", "remember", "recall", "search_chat_history",
        "list_own_files", "read_own_source", "search_own_source", "get_self_status",
        "schedule_followup", "list_followups", "cancel_followup",
        # PHASE 19 — brain-direct profile tools excluded; fetch_* tools STAY in worker
        "get_training_profile",
        "update_training_profile",
    }
]
```

**Site 4: `_HANDLERS` dispatch** (lines 1340-1372) — add 5 entries:
```python
"get_training_profile":     lambda args: _handle_get_training_profile(),
"update_training_profile":  lambda args: _handle_update_training_profile(**args),
"fetch_training_status":    lambda args: _handle_fetch_training_status(),
"fetch_recent_activities":  lambda args: _handle_fetch_recent_activities(**args),
"fetch_recent_meals":       lambda args: _handle_fetch_recent_meals(**args),
```

**Site 5: Handler functions** — see next section.

---

### `core/tools.py` — handler implementations

**Analog:** `_handle_list_followups` (lines 1297-1318), `_handle_cancel_followup` (1321-1333).

**Brain-direct handler shape** (lines 1297-1318):
```python
def _handle_list_followups() -> str:
    """Return pending follow-ups, stripped of internal fields."""
    from memory.firestore_db import FollowupStore
    store = FollowupStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    pending = store.list_pending()
    stripped = [...]
    return json.dumps(stripped)
```

**Apply pattern to `_handle_get_training_profile`** (RESEARCH §Code Examples Ex 2 — verified shape):
```python
def _handle_get_training_profile() -> str:
    from memory.firestore_db import UserProfileStore
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    return json.dumps(store.load())


def _handle_update_training_profile(patch: dict) -> str:
    from memory.firestore_db import UserProfileStore
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    try:
        store.update(patch)
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})
```

**Worker-delegated fetch handlers** — follow `_handle_fetch_garmin_today` shape (in same file): lazy import, call function, return `json.dumps(result)`. On `GarminUnavailableError`/`GoogleFitUnavailableError`, return `json.dumps({"error": str(exc)})` — same as `_handle_update_training_profile` exception branch.

---

### `prompts/meal_audit.md` (NEW)

**Analog:** `prompts/proactive_alert.md` (40 lines, succinct system prompt with voice + scope guidance).

**Voice header pattern** (proactive_alert.md lines 1-10):
```markdown
You are Klaus, composing a proactive evening alert for Sir (Amit).
...
Use your JARVIS/C-3PO hybrid voice. Be concise — this is unsolicited, not
a conversation. Lead with the most critical alert.

Do not use emojis or exclamation marks. Address the user as "Sir."
```

Adapt opener for `meal_audit.md`: "You are Klaus, auditing a meal log for Sir." Keep JARVIS register, "no emojis, no exclamation marks, address as Sir" — IDENTICAL voice constraints. Body content per RESEARCH §`prompts/meal_audit.md`.

---

### `prompts/smart_agent.md` extension

**Analog:** same file — already has 4 `{placeholder}` substitutions (`{self_md}`, `{self_state}`, `{journal_digest}`, `{today_date}`).

**Add `{training_profile}` placeholder** at the top, after `{journal_digest}`. New "TRAINING & ATHLETIC COACHING" section per RESEARCH §Smart Agent Prompt Wiring — voice match per `docs/AGENT.md` JARVIS×C-3PO blend, less hedging per locked decision.

---

### `prompts/morning_briefing.md` extension

**Analog:** same file (lines 1-60 — section structure with separators, emoji headers, "If no events:" fallback lines).

**Section structure pattern** (lines 19-29 — Schedule section):
```markdown
---

📅 Schedule
HH:MM–HH:MM — Event name
[one entry per timed event; skip all-day events unless genuinely relevant]

If no events: Nothing on the calendar today, sir.
```

**Add nutrition recap** with the SAME shape — `🥗 Yesterday's Nutrition` header, separator, conditional content. Crucially: instruct "OMIT this entire section if `nutrition` key is absent from data" (NUTR-07 silent-omit).

---

### `prompts/autonomous_triage.md` extension

**Analog:** same file (existing trigger sections). Add "Meals as triggers (Phase 19)" section per RESEARCH §NUTR-06.

---

## Shared Patterns

### Pattern A: Firestore-store discipline contract

**Source:** `memory/firestore_db.py` — `SelfStateStore` (613-680), `JournalStore` (683-773), `FollowupStore` (776-958), `OutreachLogStore` (verified L847-902).
**Apply to:** `UserProfileStore` (filled), `MealStore` (new).

**Three rules** (extracted from every existing store):
1. **Reads never raise.** Return `{}` (dict-returning) or `[]` (list-returning) on any exception. Use `logger.warning(..., exc_info=True)`.
2. **Writes re-raise after logging.** `logger.error(..., exc_info=True)` then `raise`. Caller decides.
3. **Every merge write includes `updated_at: firestore.SERVER_TIMESTAMP`** with `merge=True`.

Excerpt:
```python
def get(self) -> dict:
    try:
        snap = self._doc_ref.get()
        return snap.to_dict() or {} if snap.exists else {}
    except Exception:
        logger.warning("SelfStateStore.get() failed — returning empty", exc_info=True)
        return {}

def set(self, patch: dict) -> None:
    try:
        self._doc_ref.set({**patch, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True)
    except Exception:
        logger.error("SelfStateStore.set() failed", exc_info=True)
        raise
```

---

### Pattern B: Lazy-import + env-driven store construction in handlers

**Source:** `core/tools.py::_handle_list_followups` (lines 1303-1308).
**Apply to:** all 5 new tool handlers.

```python
from memory.firestore_db import FollowupStore  # IMPORT IS LAZY (inside function)
store = FollowupStore(
    project_id=os.environ["GCP_PROJECT_ID"],
    database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
)
```

**Why lazy:** `core/tools.py` import must never trigger Firestore I/O (test isolation, cold-start cost).

---

### Pattern C: Per-source try/except in aggregator

**Source:** `core/autonomous.py:201-318` (8 sources a-h), `core/morning_briefing.py:174-230` (5 sources).
**Apply to:** `core/autonomous.py::gather_situation` (add i, j, k); `core/morning_briefing.py::_gather_data` (add nutrition + writeback).

```python
try:
    from <module> import <fn>
    gathered["<key>"] = <fn>() or <sentinel>
except Exception:
    logger.warning("autonomous: <source> gather failed", exc_info=True)
    gathered["<key>"] = <sentinel>
```

**One failure NEVER masks others.** Sentinel must match downstream consumer's empty-shape contract (`[]`, `{}`, `None`, `0`).

---

### Pattern D: Lazy module-level singleton (for new Google-API clients)

**Source:** `core/tools.py:810-837` (`_get_auth_manager`, `_get_gmail_tool`, `_get_calendar_tool`).
**Apply to:** any new `_get_google_fit_tool()` helper if google_fit_tool exposes a class. (Current RESEARCH design uses module-level functions, so this may be N/A — but if Wave 2 introduces a class, follow this pattern.)

```python
_calendar_tool: GoogleCalendarManager | None = None

def _get_calendar_tool() -> GoogleCalendarManager:
    global _calendar_tool
    if _calendar_tool is None:
        _calendar_tool = GoogleCalendarManager(auth_manager=_get_auth_manager())
    return _calendar_tool
```

---

### Pattern E: Garmin token persistence dance

**Source:** `mcp_tools/garmin_tool.py::fetch_garmin_today` lines 79-115.
**Apply to:** `fetch_garmin_training_status`, `fetch_garmin_activities`.

**Recommendation per RESEARCH:** extract into `_authed_garmin_client()` helper to avoid 3× duplication. This is a Wave-1 refactor opportunity.

---

### Pattern F: Schema DDL idempotence

**Source:** `scripts/ingest_garmin_zip.py:23-56,79-84` — `SCHEMA_DDL` is a single string; `setup_schema(conn)` runs it on every ingest.
**Apply to:** Phase 19 schema migration. Use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (Postgres 9.6+ — Neon is 16+) so re-runs are idempotent.

**Do NOT introduce Alembic** — research recommends staying in `SCHEMA_DDL` for the 7-column additive change.

---

### Pattern G: Test mock-installation (Firestore, google-cloud)

**Source:** `tests/test_firestore_db.py::_install_firestore_mock` (lines 29-80).
**Apply to:** all new tests touching Firestore (`test_user_profile_store.py`, `test_meal_store.py`).

**Sentinel objects:** `_Increment`, `_ArrayUnion`, `firestore.SERVER_TIMESTAMP = object()` — tests must use these distinguishable sentinels to assert "store used SERVER_TIMESTAMP, not a raw datetime".

```python
firestore_mock.SERVER_TIMESTAMP = object()
sys.modules["google.cloud.firestore"] = firestore_mock
google_cloud_mod.firestore = firestore_mock
```

---

### Pattern H: Tool-registration test (introspection)

**Source:** `tests/test_tools.py` (Phase-18 followup tests verify `SMART_AGENT_DIRECT_TOOLS` membership, `WORKER_TOOL_SCHEMAS` exclusion, `_HANDLERS` dispatch table, and `TOOL_SCHEMAS` schema name).
**Apply to:** `tests/test_tools.py::test_phase19_profile_tools_registered`, `::test_phase19_fetch_tools_worker_delegated`.

Read `core.tools` as a module and inspect the 4 registry sites — no Firestore I/O needed.

---

## No Analog Found

| File | Role | Data Flow | Reason | What to use instead |
|------|------|-----------|--------|---------------------|
| `mcp_tools/garmin_tool.py::compute_acwr` | Pure utility | transform | No existing pure-math util in the codebase; ACWR is novel | Specify directly from RESEARCH §Code Examples Ex 3 (12-line stdlib function). Test with hand-built fixtures — no mocks needed. |
| `tests/test_compute_acwr.py` | Test | pure unit | No existing pure-math test analog | Pure pytest functions, no mocking, fixture activities lists with known dates + loads. |
| `tests/test_ingest_schema.py`, `tests/test_ingest_garmin.py` | Test | unit | No existing test for `scripts/ingest_garmin_zip.py` | Use `tests/test_firestore_db.py` mock-installation pattern adapted for `psycopg2` (mock `cursor`, `execute_values`). For parser tests, use plain dict fixtures (no DB). |

---

## Metadata

**Analog search scope:** `core/`, `memory/`, `mcp_tools/`, `prompts/`, `scripts/`, `tests/` (full project tree).
**Files scanned:** ~30 source files inspected; 12 analogs read in detail.
**Pattern extraction date:** 2026-05-26
**Required reading consumed:** `19-RESEARCH.md` (2608 lines), `REQUIREMENTS.md` (160 lines), `ROADMAP.md` (119 lines), `CLAUDE.md` (project).
**RESEARCH §References used:** Code Examples (Ex 1/2/3), §UserProfileStore Design, §MealStore Design, §Garmin Live Reads, §Autonomous Tick Extension, §Morning Briefing Extension, §Smart Agent Prompt Wiring, §Tool Registration, §SELF.md Regeneration.
