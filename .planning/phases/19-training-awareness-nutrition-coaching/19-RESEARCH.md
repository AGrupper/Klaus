# Phase 19: Training Awareness & Nutrition Coaching — Research

**Researched:** 2026-05-25
**Domain:** Postgres schema migration · 3-year Garmin backfill · Firestore stores
(`UserProfileStore`, `MealStore`) · Google Fit Nutrition REST API · ACWR
computation · autonomous-tick gather extension · morning-briefing recap ·
smart-agent prompt extension
**Confidence:** MEDIUM-HIGH (Google Fit shape HIGH; Garmin export field names
LOW until live export inspected)

---

## Summary

Phase 19 is an **integration + plumbing** phase: it threads three independent
data planes (Garmin Postgres analytics, Google Fit nutrition reads, Firestore
profile/meals) into Klaus's existing brain/triage/morning-briefing surfaces
without changing the autonomous-tick scheduler, the dual-model architecture,
or the brain/worker split. **No personalized rules ship** — the
`UserProfileStore` is an empty scaffold; the LLM prompts are extended to read
training/nutrition context but instructed to ask Sir for any threshold it
needs, not invent one.

The phase is decomposable into seven loosely-coupled vertical slices:

1. **Postgres schema migration** (SCHEMA-01..03 + INGEST-01..02) — additive
   `ALTER TABLE ADD COLUMN IF NOT EXISTS` patches to `activities` +
   `daily_biometrics`, plus parser-side field extraction in `ingest_garmin_zip.py`.
2. **3-year Garmin backfill** (INGEST-03) — operator runs the existing ingest
   script against a Garmin Connect export zip; verification queries document
   row counts + NULL rates.
3. **`UserProfileStore`** (PROFILE-01..04) — Firestore-backed store at
   `users/amit`, brain-direct tools `get_training_profile` +
   `update_training_profile`.
4. **Garmin tool extensions** (GARMIN-01..05) — `fetch_garmin_training_status`,
   `fetch_garmin_activities`, pure-Python `compute_acwr`; morning-briefing
   gather writes fresh biometrics to Postgres.
5. **Google Fit nutrition integration** (NUTR-01..05) — new
   `mcp_tools/google_fit_tool.py`, OAuth scope addition via incremental
   authorization, `MealStore` at `meals/{date}/{timestamp}`, autonomous-tick
   layer-0 + morning-briefing data gather extensions.
6. **Prompt extensions** (NUTR-06..08, PROMPT-01..03) — `prompts/smart_agent.md`
   training section, `prompts/autonomous_triage.md` meal triggers,
   `prompts/morning_briefing.md` nutrition recap, new `prompts/meal_audit.md`,
   `{training_profile}` placeholder wired into `render_smart_system`.
7. **Tool registration + SELF.md** (PROFILE-04, GARMIN-04, NUTR-03,
   PROMPT-03) — 5 new tool handlers in `core/tools.py`,
   `SMART_AGENT_DIRECT_TOOLS` / `WORKER_TOOL_SCHEMAS` partition updated,
   `core/self_manifest.py` regenerates `docs/SELF.md` automatically.

**Primary recommendation:** Plan in five waves — (Wave 0) schema + ingest
parsers + backfill, (Wave 1) `UserProfileStore` + Garmin reads + ACWR,
(Wave 2) Google Fit tool + `MealStore`, (Wave 3) autonomous tick + morning
briefing gather extensions, (Wave 4) prompt extensions + SELF.md regen +
end-to-end test. Each wave is independently mergeable.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

> **Note:** No CONTEXT.md exists for Phase 19 (no `/gsd-discuss-phase` run yet).
> The constraints below are extracted verbatim from the orchestrator-provided
> "Locked architectural decisions" block in the research scope. The planner
> should treat them as locked-equivalent.

### Locked Decisions
- **No personalized rules/thresholds in v3.0** — plumbing only.
  `UserProfileStore` ships as an empty scaffold
  (`athletic_goals: []`, `training_constraints: []`,
  `recovery_preferences: {}`, `schema_version: 1`).
- **Nutrition source = Google Fit Nutrition REST API**, NOT photo audit of
  meals. Lifesum writes to Fit (via Health Connect); Klaus reads from Fit.
- **Mid-day proactive coaching runs inside the existing autonomous tick**
  (`*/20 7-21` Asia/Jerusalem) — no new cron, no new Cloud Scheduler job.
- **Morning recap = new step inside the existing morning-briefing state
  machine**, not a new cron.
- **Persona = JARVIS-blended** (`docs/AGENT.md` § JARVIS × C-3PO). New
  prompt sections keep the same voice.
- **21:00 user check-in is OUT OF SCOPE for Phase 19.** That cron is
  Phase 20 (`klaus-training-checkin`).

### Claude's Discretion
- Exact ACWR formula choice (TRIMP vs duration×RPE vs Garmin
  `trainingLoad`) — research recommends Garmin `trainingLoad` as the workload
  unit (see § ACWR Computation).
- Exact "insufficient chronic baseline" threshold (research recommends
  < 14 days of data with `training_load != NULL` returns `ratio=None`).
- Meal-idempotency key strategy (research recommends
  `source_id` = Google Fit `dataPoint.dataTypeName + originDataSourceId +
  startTimeNanos`).
- Where ACWR is computed (research recommends pure Python on top of a
  `database_tool.py` query — keeps SQL simple, makes the function
  unit-testable without a live DB).
- Whether `{training_profile}` is injected as JSON or as a rendered text block
  (research recommends rendered text block, same convention as `{self_state}`).

### Deferred Ideas (OUT OF SCOPE)
- 21:00 training check-in cron (Phase 20 — `CHECKIN-01..06`).
- `TrainingLogStore` + `log_training` tool (Phase 20 — `LOG-01..04`).
- Weekly training review cron (Phase 20 — `REVIEW-01..04`).
- `recovery_concern` flag in morning briefing (Phase 20 — `RECOVERY-01..03`).
- Personalized HR zones, lift targets, pace goals (will be populated via
  `update_training_profile` in a separate session after Phase 19 ships).
- Food-name fidelity (Google Fit carries macros + timing but not food names;
  defer until proven insufficient).
- Manual screenshot fallback for meals (defer until Google Fit proves
  insufficient).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHEMA-01 | `activities` gains `training_load REAL`, `perceived_exertion SMALLINT`, `feel SMALLINT` | § Postgres Schema Migration |
| SCHEMA-02 | `daily_biometrics` gains `vo2_max REAL`, `training_load_acute REAL`, `training_load_chronic REAL`, `acwr REAL` | § Postgres Schema Migration |
| SCHEMA-03 | All adds via idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` | § Migration Approach |
| INGEST-01 | Activity parser extracts `trainingLoad`, `perceivedExertion`, `feel` (NULL-safe) | § Garmin Export Field Map |
| INGEST-02 | UDS parser extracts `vo2MaxValue` → `daily_biometrics.vo2_max` | § Garmin Export Field Map |
| INGEST-03 | 3-year backfill ingests end-to-end; row counts + NULL rates documented | § Backfill Strategy |
| PROFILE-01 | `UserProfileStore.load()` never raises; returns `{}` on failure | § UserProfileStore Design |
| PROFILE-02 | `UserProfileStore.update(patch)` merges + stamps `updated_at` | § UserProfileStore Design |
| PROFILE-03 | `bootstrap_if_empty()` creates empty scaffold | § UserProfileStore Design |
| PROFILE-04 | `get_training_profile` + `update_training_profile` brain-direct at all 5 sites | § Tool Registration |
| GARMIN-01 | `fetch_garmin_training_status()` returns dict with `vo2_max`, `training_status`, `load_focus` | § Garmin Live Reads |
| GARMIN-02 | `fetch_garmin_activities(days=7)` returns normalized list incl. `perceived_exertion`, `feel` | § Garmin Live Reads |
| GARMIN-03 | `compute_acwr(activities_28d)` returns `{acute, chronic, ratio}`, `ratio=None` on insufficient | § ACWR Computation |
| GARMIN-04 | `fetch_training_status` + `fetch_recent_activities` worker-delegated (NOT smart-direct) | § Tool Registration |
| GARMIN-05 | Morning-briefing `_gather_data()` writes fresh biometrics + activities to Postgres (best-effort) | § Morning Briefing Extension |
| NUTR-01 | `mcp_tools/google_fit_tool.py` wraps Fit REST API; returns normalized meals | § Google Fit Integration |
| NUTR-02 | `MealStore` at `meals/{date}/{timestamp}` with macros + meal_type + source; idempotent | § MealStore Design |
| NUTR-03 | `fetch_recent_meals(hours)` worker-delegated | § Tool Registration |
| NUTR-04 | Autonomous-tick layer-0 syncs Fit → MealStore + includes meals-since-last-tick in triage context | § Autonomous Tick Extension |
| NUTR-05 | Morning-briefing `_gather_data()` aggregates yesterday's meals (totals + breakdown + biggest gap) | § Morning Briefing Extension |
| NUTR-06 | `prompts/autonomous_triage.md` treats new meals as potential triggers | § Prompt Extensions |
| NUTR-07 | `prompts/morning_briefing.md` includes nutrition recap; silently omitted when empty | § Morning Briefing Extension |
| NUTR-08 | `prompts/meal_audit.md` exists; referenced by both autonomous tick + morning briefing | § Prompt Extensions |
| PROMPT-01 | `render_smart_system()` injects `{training_profile}` placeholder | § Smart Agent Prompt Wiring |
| PROMPT-02 | `prompts/smart_agent.md` gains TRAINING & ATHLETIC COACHING section | § Prompt Extensions |
| PROMPT-03 | `docs/SELF.md` regen lists all 7 new tools | § SELF.md Regeneration |

**7 new tools total:** `get_training_profile`, `update_training_profile`,
`fetch_training_status`, `fetch_recent_activities`, `fetch_recent_meals`,
plus 2 implied (`compute_acwr` lives inside `fetch_training_status` per
GARMIN-01 wording; if exposed as its own tool that makes 6 — recommend
keeping ACWR as an internal helper called from `database_tool.py` queries or
inside `fetch_training_status`). **Success criterion 6 names exactly 5 new
tools**, so the plan should target 5 user-visible tools + `compute_acwr` as
an internal utility.
</phase_requirements>

## Project Constraints (from CLAUDE.md)

| Invariant | Phase 19 application |
|-----------|---------------------|
| All GCP/Pinecone names lowercase `klaus-` | New Firestore collections: `users`, `meals` (lowercase, no `klaus-` prefix needed — that's only for top-level resources) |
| `load_dotenv(override=True)` always | New scripts use this if they call `load_dotenv` |
| Embeddings via Gemini AI Studio, NEVER Vertex | N/A — Phase 19 adds no embedding calls |
| Brain (`gemini-3.5-flash`) sees every message | New `get_training_profile` is brain-direct; `fetch_training_status` / `fetch_recent_activities` / `fetch_recent_meals` are worker-delegated |
| Autonomous tick cost gating | Layer-0 extension is free (Fit API + Postgres reads); only Layer-1+Layer-2 cost money — must not change empty-signals gating |
| `OutreachLogStore.append` success-gated | Existing pattern preserved; nutrition outreach uses same `topic_key` discipline |
| `_get_orchestrator()` process-wide singleton | Untouched — `render_smart_system` already singleton-aware |
| File names: lowercase `klaus-` for GCP resources | No new Cloud Scheduler jobs created in Phase 19 (deferred to Phase 20) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Garmin schema + 3-yr backfill | Database / Storage (Postgres) | Script (`ingest_garmin_zip.py`) | Persistent analytics tier; script is the bridge from offline export → DB |
| `UserProfileStore` | Database / Storage (Firestore) | Brain-direct tools (`core/tools.py`) | Slow-changing user config; Firestore is the proven low-latency K/V store; brain reads/writes directly (no judgment in worker for user identity) |
| `MealStore` | Database / Storage (Firestore) | Sync layer (`mcp_tools/google_fit_tool.py`) | Append-mostly time-series in Firestore; the Fit tool is the producer, MealStore is the persistence boundary |
| Google Fit auth + read | API client (`mcp_tools/google_fit_tool.py`) | OAuth layer (`core/auth_google.py`) | Standard tier mapping for an external API; auth shared with Gmail/Calendar |
| Garmin live reads (`fetch_training_status`, `fetch_recent_activities`) | API client (`mcp_tools/garmin_tool.py`) | Brain via worker delegation | Same shape as existing `fetch_garmin_today` — extend the tool, don't fork |
| ACWR computation | Pure Python utility | `database_tool.py` (read source) | Math on Postgres rows; no I/O of its own; trivially unit-testable |
| Autonomous-tick gather extension | Orchestration (`core/autonomous.py`) | Producers (Fit tool, Garmin tool) | Layer-0 is a pure aggregator — same "per-source try/except" pattern as existing 8 sources |
| Morning-briefing extension | Orchestration (`core/morning_briefing.py`) | Producers (MealStore + Postgres + Garmin tool) | `_gather_data` extends with the same per-source isolation pattern |
| Smart-agent prompt extension | Prompt layer (`prompts/smart_agent.md` + `render_smart_system`) | — | Same `{placeholder}` injection convention as `{self_md}`, `{self_state}`, `{journal_digest}` |
| Tool registration | Schema + dispatch (`core/tools.py`) | Manifest (`core/self_manifest.py`) | Single source of truth; manifest derives from schemas |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `psycopg2-binary` | (already pinned) | Postgres driver | `[VERIFIED: scripts/ingest_garmin_zip.py:5]` Already used by ingest + `database_tool.py`. Don't switch to `psycopg3` mid-phase. |
| `garminconnect` | (already pinned) | Garmin Connect Python client | `[VERIFIED: mcp_tools/garmin_tool.py:80]` Has `get_training_status(cdate)`, `get_training_readiness(cdate)`, `get_max_metrics(cdate)`, `get_activities(start, limit)`, `get_activities_by_date(start, end)` `[CITED: github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py]` |
| `google-cloud-firestore` | (already pinned) | Firestore client | `[VERIFIED: memory/firestore_db.py:18]` Already used by 8+ stores; `MealStore` and `UserProfileStore` follow the same wrapper pattern. |
| `google-auth-oauthlib` + `google-api-python-client` | (already pinned) | Google OAuth + REST | `[VERIFIED: core/auth_google.py:32-34]` Used today for Gmail + Calendar. Add Fit Nutrition scope via incremental authorization. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `datetime` + `zoneinfo` | — | Tz-aware date math (Asia/Jerusalem) | All date math (ACWR windows, meals aggregation) — same pattern as `core/autonomous.py:44` |
| stdlib `statistics` | — | Mean for chronic load average | `compute_acwr` chronic window mean |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Garmin live `get_training_status` | Postgres-only reads | Live gives "today's training status enum" which the backfill zip doesn't carry; Postgres gives multi-day analytics. Use BOTH — live for status, Postgres for ACWR. |
| Reading meals from Fit on every tick | Postgres-cached meal index | Phase 19 ships MealStore on Firestore (per NUTR-02). Defer Postgres mirror — Firestore reads are < 50ms and meals fit easily into the autonomous-tick budget. |
| `psycopg2.tz.FixedOffset(0)` for UTC | `datetime.timezone.utc` | `psycopg2.tz` is deprecated. Existing `ingest_garmin_zip.py:226` uses it — should be migrated to `datetime.timezone.utc` opportunistically when SCHEMA-01 lands. |

**Installation:** Nothing new to install. Phase 19 reuses the existing dependency set.

**Version verification:** Skipped — all libraries are already pinned in
`requirements.txt`/`pyproject.toml`. The planner should ALWAYS verify by
running `pip show garminconnect google-api-python-client google-cloud-firestore psycopg2-binary`
in Wave 0 to confirm no drift.

---

## Architecture Patterns

### System Architecture Diagram

```
                    ┌──────────────────────────────────────────────┐
                    │  Garmin Connect Export (zip)  [operator run] │
                    └──────────────┬───────────────────────────────┘
                                   │ 3-year backfill (one-time)
                                   ▼
                    ┌──────────────────────────────────────────────┐
                    │  scripts/ingest_garmin_zip.py (extended)     │
                    │  • parse summaries.json + UDSFile.json       │
                    │  • setup_schema() runs idempotent ALTERs     │
                    │  • UPSERT activities + daily_biometrics      │
                    └──────────────┬───────────────────────────────┘
                                   ▼
                    ┌──────────────────────────────────────────────┐
                    │  Neon Postgres                               │
                    │  ├─ activities (+training_load,              │
                    │  │       perceived_exertion, feel)           │
                    │  ├─ daily_biometrics (+vo2_max,              │
                    │  │       acwr_acute, acwr_chronic, acwr)     │
                    │  └─ laps_telemetry                           │
                    └──────────────┬───────────────────────────────┘
                                   │
                                   │ on-demand SELECT (read-only)
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │  mcp_tools/database_tool.py  query_health_database(sql)  │
        └──────────────┬───────────────────────────────┬───────────┘
                       │                               │
                       ▼                               ▼
        ┌─────────────────────────┐    ┌───────────────────────────┐
        │  compute_acwr (Python)  │    │  Brain (gemini-3.5-flash) │
        │  • acute = mean(7d)     │    │  • answers "ACWR this week"
        │  • chronic = mean(28d)  │    │  • interprets joined data │
        │  • ratio = a / c        │    └───────────────────────────┘
        │  • None if days<14      │
        └─────────────────────────┘

        ┌──────────────────────────────────────────────────────────┐
        │  Lifesum app  ─→  Google Health Connect  ─→  Google Fit  │
        │                                              (cloud)     │
        └────────────────────────────────────┬─────────────────────┘
                                             │
                                             │ HTTPS GET (read-only)
                                             ▼
        ┌──────────────────────────────────────────────────────────┐
        │  mcp_tools/google_fit_tool.py                            │
        │  • OAuth via core/auth_google.py (+ nutrition.read scope)│
        │  • POST /fitness/v1/users/me/dataset:aggregate           │
        │  • dataTypeName = com.google.nutrition                   │
        │  • normalize → [{ts, kcal, protein_g, carbs_g, fat_g,    │
        │                  meal_type, source_id}]                  │
        └──────────────────────────────────────────┬───────────────┘
                                                   │
                                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │  MealStore (Firestore)                                   │
        │  • meals/{YYYY-MM-DD}/timestamps/{ISO}                   │
        │  • idempotent on source_id                               │
        └────────┬─────────────────────────────────────────────────┘
                 │
                 │           (also written: UserProfileStore at users/amit)
                 │
        ┌────────┴───────────────┐
        │                        │
        ▼                        ▼
 ┌──────────────────┐    ┌─────────────────────────────────────────┐
 │ Morning briefing │    │ Autonomous tick (*/20 7-21)             │
 │ • _gather_data() │    │ • Layer 0: extended gather              │
 │   adds yesterday │    │   (fetch_recent_meals + Postgres ACWR + │
 │   meals aggreg.  │    │    Garmin training_status, all free)    │
 │ • prompt: recap  │    │ • Layer 1: triage prompt extended       │
 │   if meals exist │    │   (NUTR-06: meal triggers)              │
 │ • silent if none │    │ • Layer 2: brain composes (existing)    │
 └──────────────────┘    └─────────────────────────────────────────┘
                                            │
                                            ▼
                                  Telegram outreach
                                  (success-gated OutreachLog
                                   with topic_key="nutrition:*")
```

### Recommended Project Structure

```
Klaus/
├── core/
│   ├── main.py                    # render_smart_system: +{training_profile}
│   ├── autonomous.py              # gather_situation: +meals +training_status +acwr
│   ├── morning_briefing.py        # _gather_data: +meals +biometrics_writeback
│   ├── tools.py                   # +5 schemas, +5 handlers, +2 to SMART_DIRECT
│   └── self_manifest.py           # untouched — auto-picks up new tools
├── memory/
│   └── firestore_db.py            # +MealStore class, fill in UserProfileStore stub
├── mcp_tools/
│   ├── garmin_tool.py             # +fetch_garmin_training_status, +fetch_garmin_activities, +compute_acwr
│   └── google_fit_tool.py         # NEW — Fit nutrition REST wrapper
├── scripts/
│   └── ingest_garmin_zip.py       # ALTER TABLE + extract trainingLoad/perceivedExertion/feel/vo2MaxValue
├── prompts/
│   ├── smart_agent.md             # +TRAINING & ATHLETIC COACHING section, +{training_profile} placeholder
│   ├── autonomous_triage.md       # +meal trigger criteria
│   ├── morning_briefing.md        # +yesterday's nutrition recap block (conditional)
│   └── meal_audit.md              # NEW — non-personalized critique guidance
├── docs/
│   └── SELF.md                    # AUTO-regenerated (lists 5 new tools)
└── tests/
    ├── test_user_profile_store.py   # NEW — bootstrap_if_empty + load + update
    ├── test_meal_store.py           # NEW — idempotency on source_id
    ├── test_google_fit_tool.py      # NEW — payload normalization, scope error path
    ├── test_garmin_training_status.py  # NEW — patches garminconnect lib
    ├── test_compute_acwr.py         # NEW — math + insufficient-history None
    ├── test_autonomous.py           # EXTEND — meals in layer-0 gather, triage prompt rendering
    ├── test_morning_briefing.py     # EXTEND — meals aggregation, silent-on-empty
    └── test_main_render_smart_system.py  # EXTEND — {training_profile} substitution
```

### Pattern 1: Lazy-singleton Firestore Store

**What:** Every Firestore-backed persistence wrapper follows the same shape.
**When to use:** Any new collection (`users`, `meals`).
**Example:** see `JournalStore` `[VERIFIED: memory/firestore_db.py:683-773]`,
`FollowupStore` `[VERIFIED: memory/firestore_db.py:776-958]`, `SelfStateStore`
`[VERIFIED: memory/firestore_db.py:613-680]`.

Pattern signature:
```python
class MealStore:
    _COLLECTION = "meals"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, source_id: str, meal: dict) -> None:
        """Append-or-update. Idempotent on source_id."""
        try:
            date_str = meal["timestamp"][:10]  # YYYY-MM-DD prefix
            # Path: meals/{date}/timestamps/{source_id}
            (self._col.document(date_str)
                .collection("timestamps").document(source_id)
                .set({**meal, "source_id": source_id, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True))
        except Exception:
            logger.error("MealStore.upsert(%r) failed", source_id, exc_info=True)
            raise

    def get_day(self, date_str: str) -> list[dict]:
        """Read all meals for a date. Never raises — returns []."""
        try:
            snaps = self._col.document(date_str).collection("timestamps").stream()
            return sorted((s.to_dict() for s in snaps), key=lambda d: d.get("timestamp", ""))
        except Exception:
            logger.warning("MealStore.get_day(%r) failed", date_str, exc_info=True)
            return []
```

**Read methods never raise; write methods re-raise after logging.** Matches
`FollowupStore` / `OutreachLogStore` / `JournalStore` discipline exactly.
`[VERIFIED: memory/firestore_db.py:847,902,1034]`

### Pattern 2: Per-source `try/except` in gather

**What:** Each external source is isolated so one failure does not mask others.
**When to use:** Extending `gather_situation()` (autonomous) or `_gather_data()`
(morning briefing).
**Example:** `[VERIFIED: core/autonomous.py:201-318]` — 8 sources, each in
its own `try/except` block, each falling back to a sentinel
(empty list / 0 / None) on exception.

For Phase 19, add three new sources to autonomous `gather_situation` AFTER the
existing 8, BEFORE the `_is_empty_signals` gate:

```python
# (i) Recent meals from Google Fit + MealStore sync
try:
    from mcp_tools.google_fit_tool import sync_recent_meals
    from memory.firestore_db import MealStore
    ms = MealStore(project_id=project_id, database=database)
    new_meals = sync_recent_meals(since_hours=1, store=ms)
    gathered["meals_since_last_tick"] = new_meals  # list[dict]
except Exception:
    logger.warning("autonomous: meals gather failed", exc_info=True)
    gathered["meals_since_last_tick"] = []

# (j) Garmin training status (live)
try:
    from mcp_tools.garmin_tool import fetch_garmin_training_status
    gathered["training_status"] = fetch_garmin_training_status() or {}
except Exception:
    logger.warning("autonomous: training_status gather failed", exc_info=True)
    gathered["training_status"] = {}

# (k) ACWR from Postgres
try:
    from mcp_tools.garmin_tool import compute_acwr_from_db
    gathered["acwr"] = compute_acwr_from_db() or {"ratio": None}
except Exception:
    logger.warning("autonomous: acwr gather failed", exc_info=True)
    gathered["acwr"] = {"ratio": None}
```

**CRITICAL:** Update `_is_empty_signals` to consider `meals_since_last_tick` —
new meals are a potential trigger and must NOT be gated out by the existing
"empty signals" detection. `[VERIFIED: core/autonomous.py:167-184]`

### Pattern 3: Brain-direct vs Worker-delegated tool registration

**What:** Tools that need the brain's judgment (or read identity-shaped state)
go in `SMART_AGENT_DIRECT_TOOLS`. Tools that the worker (`gemini-2.5-flash`)
can call without judgment go through `delegate_to_worker`.
**When to use:** Each of the 5 new tools.

| Tool | Direct? | Why |
|------|---------|-----|
| `get_training_profile` | YES | Brain reads identity-shaped state; same class as `get_self_status` |
| `update_training_profile` | YES | Brain writes user-facing config; same class as `remember` |
| `fetch_training_status` | NO (worker) | Plain data fetch; brain interprets the result |
| `fetch_recent_activities` | NO (worker) | Plain data fetch; brain interprets |
| `fetch_recent_meals` | NO (worker) | Plain data fetch; brain interprets |

Update sites (5 per PROFILE-04 wording — but really 4 places per tool):
1. `SMART_AGENT_DIRECT_TOOLS` frozenset `[VERIFIED: core/tools.py:39-52]`
2. `TOOL_SCHEMAS` list `[VERIFIED: core/tools.py:58-746]`
3. `WORKER_TOOL_SCHEMAS` exclusion list `[VERIFIED: core/tools.py:750-766]`
4. `_HANDLERS` dispatch dict `[VERIFIED: core/tools.py:1340-1372]`
5. Handler function `_handle_*` defined in `core/tools.py`

The fifth "site" is the handler implementation itself.

### Anti-Patterns to Avoid

- **Hand-rolling the Fit nutrition payload parser** — use the documented field
  names (`calories`, `protein`, `fat.total`, `carbs.total`, `meal_type`) so a
  Lifesum schema change doesn't silently break ingestion. The Google Fit
  spec is stable.
- **Putting ACWR into a SQL window function** — the math fits in 12 lines of
  Python, is trivially unit-testable, and keeps `database_tool.py` SQL guard
  rails (read-only enforcement) clean. Don't push ACWR into a stored procedure
  or a CTE.
- **Auto-tagging meals "before workout" / "after workout" in Phase 19** — that
  needs personalized timing rules that don't ship in v3.0. Leave it to the
  prompt to do the reasoning.
- **Calling Garmin live API from inside the LLM tool loop** — `fetch_training_status`
  in the worker is fine, but DON'T add Garmin live calls to every autonomous-tick
  layer-0 gather. Caching layer is the existing `fetch_garmin_today` Firestore
  token cache; do not bypass it. `[VERIFIED: mcp_tools/garmin_tool.py:27-53]`

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Google OAuth token refresh for Fit | A second auth manager | Extend `GoogleAuthManager.SCOPES` `[VERIFIED: core/auth_google.py:192]` | Existing manager already handles RefreshError, file/secret storage, and incremental authorization is a documented standard `[CITED: developers.google.com/identity/protocols/oauth2/web-server]` |
| Garmin API endpoint dispatch | A second HTTP client | Reuse `garminconnect` lib | `get_training_status`, `get_activities_by_date`, `get_max_metrics` already exist `[CITED: github.com/cyberjunky/python-garminconnect]` |
| Firestore retry/error wrapping | A custom retry decorator | Follow `JournalStore.set` pattern: `try/except` + log + re-raise on write, `[]/{}` on read | Phase 18 enforced this contract across 5 stores; new stores must conform |
| Tz-aware date math | A new `_TZ` constant | `ZoneInfo("Asia/Jerusalem")` already in every relevant module | `[VERIFIED: core/autonomous.py:44, core/morning_briefing.py:24]` |
| SQL migration tracking | An ORM migration system (Alembic) | Idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` in `SCHEMA_DDL` | Phase 19 has 7 new columns total; single-developer project; ORM is overkill |
| ACWR computation library | Pip-install an "acwr" package | 12-line Python function | No standard library exists; sport-science formulas vary; better to keep visible and tweakable |

**Key insight:** Phase 19 is a thread-the-needle phase — the dangerous instinct
is to add new abstractions. Every existing pattern already covers a Phase 19
need. The plan should reuse, not re-invent.

---

## Runtime State Inventory

> Phase 19 is **additive**, not a rename/refactor. No existing strings change.
> The following audit confirms no runtime-state migration is needed.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New Firestore docs at `users/amit` and `meals/{date}/timestamps/*`. No existing docs are renamed. New Postgres columns are ADDed, none renamed. | None — additive |
| Live service config | Google OAuth token in Secret Manager `[VERIFIED: core/auth_google.py:102-171]` must be re-issued (incremental authorization) to include the new `fitness.nutrition.read` scope. The refresh token survives across scope adds when using `include_granted_scopes='true'` on the consent URL `[CITED: developers.google.com/identity/protocols/oauth2/web-server]`. | One-time operator re-consent via `python -m core.auth_google` after the scopes list is extended. |
| OS-registered state | No Cloud Scheduler job changes in Phase 19. Phase 20 will add `klaus-training-checkin` and `klaus-weekly-training-review`. | None |
| Secrets/env vars | No new secrets. Fit reuses `GOOGLE_TOKEN_SECRET_NAME` / `GOOGLE_APPLICATION_CREDENTIALS`. | None |
| Build artifacts | None — no package renames or version bumps. | None |

**The canonical question:** *After every file in the repo is updated, what
runtime systems still have the old string cached, stored, or registered?*

Answer: only the cached OAuth token (no nutrition scope yet). Resolution: one
operator re-consent.

---

## Postgres Schema Migration

### Current Schema (verified)

`[VERIFIED: scripts/ingest_garmin_zip.py:23-56]`

```sql
CREATE TABLE IF NOT EXISTS daily_biometrics (
    date DATE PRIMARY KEY,
    resting_hr INTEGER,
    hrv_baseline INTEGER,
    hrv_overnight INTEGER,
    sleep_score INTEGER CHECK (sleep_score BETWEEN 0 AND 100),
    sleep_duration NUMERIC(4,2),
    body_battery_max INTEGER CHECK (body_battery_max BETWEEN 0 AND 100),
    training_readiness INTEGER CHECK (training_readiness BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id BIGINT PRIMARY KEY,
    date TIMESTAMP WITH TIME ZONE NOT NULL,
    type VARCHAR(50) NOT NULL,
    duration_sec INTEGER NOT NULL,
    distance_m NUMERIC(8,2),
    avg_hr INTEGER,
    max_hr INTEGER,
    avg_pace NUMERIC(5,2),
    training_effect NUMERIC(3,1) CHECK (training_effect BETWEEN 0.0 AND 5.0)
);
```

### Required Phase 19 Additions

```sql
-- SCHEMA-01
ALTER TABLE activities ADD COLUMN IF NOT EXISTS training_load REAL;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS perceived_exertion SMALLINT;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS feel SMALLINT;

-- SCHEMA-02
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS vo2_max REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_acute REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS training_load_chronic REAL;
ALTER TABLE daily_biometrics ADD COLUMN IF NOT EXISTS acwr REAL;
```

### Migration Approach

**Recommendation:** Place the `ALTER TABLE` block inside the existing
`SCHEMA_DDL` string `[VERIFIED: scripts/ingest_garmin_zip.py:23]` AFTER the
`CREATE TABLE IF NOT EXISTS` blocks. `setup_schema(conn)` runs the whole
string on every ingest; `ADD COLUMN IF NOT EXISTS` is idempotent in Postgres
9.6+ (Neon is 16+) — running it 1× or 100× yields the same result.

Why NOT a numbered migration file:
1. Phase 19 has only 7 columns total — Alembic-style migrations would dwarf
   the actual change.
2. Single-developer project, single environment (Neon).
3. The existing convention is `setup_schema` runs on every ingest. Breaking
   that convention to introduce migrations is a phase-of-its-own discussion,
   not a Phase 19 deliverable.

If a future phase introduces a destructive migration (column drop, type
change), revisit. For Phase 19: stay in `SCHEMA_DDL`.

### Why `REAL` and `SMALLINT`?

- `training_load REAL` — Garmin reports `trainingLoad` as a float (e.g., 78.3).
  `REAL` is 4-byte float, sufficient precision for sport-science load metrics.
- `perceived_exertion SMALLINT` — Garmin Connect captures RPE as 0–10 integer
  (Borg scale CR-10). `SMALLINT` (-32768 to +32767) is plenty.
- `feel SMALLINT` — Garmin captures "feel" as an enum (1–5: very_weak →
  very_strong) in `directWorkoutFeel`. `SMALLINT` covers it.
- `vo2_max REAL` — VO2 max is a float (e.g., 51.7 ml/kg/min). `REAL` is
  sufficient.
- `training_load_acute REAL`, `training_load_chronic REAL`, `acwr REAL` —
  populated by an offline (or in-script) ACWR computation pass; can be left
  NULL if the live `compute_acwr` runs each query.

**Plan question for discuss-phase:** Are `training_load_acute/chronic/acwr`
populated by the ingest script (one-shot post-processing) or computed live
on every query? Research recommends **live computation** — keeps the DB
simple and the math testable. The columns exist in case a future Phase 20
weekly-review wants pre-computed snapshots.

---

## Garmin Export Field Map

### Export Shape (existing)

The Garmin Connect export is a single zip with directory tree:
```
DI_CONNECT/
  ├── DI-Connect-Wellness/   (*sleepData.json)
  ├── DI-Connect-User/       (*UDSFile.json)
  └── DI-Connect-Fitness/    (*summaries.json)
```

`[VERIFIED: scripts/ingest_garmin_zip.py:87,137,203]`

The export contains all data the operator has ever recorded — for a 3-year
account, all 3 years are in one zip. The user requests the export from
[Garmin Connect → Account → Data Management → Export]. Garmin emails a
download link within 24–48 hours.

### Field Extraction Targets

`[ASSUMED]` — exact JSON keys below are based on common Garmin Connect export
field conventions; the plan should add a **first-step task** to dump one
activity's JSON keys via `python -c "import json; print(list(json.load(open(p)))[0].keys())"`
and confirm names before committing parser code.

| Postgres column | Likely JSON key in `*summaries.json` | Source within Garmin Connect | Confidence |
|-----------------|--------------------------------------|------------------------------|------------|
| `activities.training_load` | `activityTrainingLoad` or `trainingLoad` | "Training Load" on activity detail | `[ASSUMED]` — verify in first parse |
| `activities.perceived_exertion` | `directPerceivedEffort` or `perceivedExertion` | User-entered RPE 0–10 on activity detail | `[ASSUMED]` |
| `activities.feel` | `directWorkoutFeel` or `workoutFeel` | User-entered feel 1–5 | `[ASSUMED]` |
| `daily_biometrics.vo2_max` | `vO2MaxValue` (note capital O) in `*UDSFile.json` | "VO2 max" estimate from runs/walks | `[ASSUMED]` — exact capitalization is `vO2MaxValue` per Garmin convention; verify |

`[VERIFIED: github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py]` — the live API client uses `/metrics-service/metrics/maxmet/daily/{date}/{date}` for VO2 max but the field name inside the JSON payload is NOT documented in the README.

**Wave-0 verification task:** Add a one-shot script that opens the user's
real export zip, dumps `json.load(open(first_summaries_file))[0].keys()`, and
prints the keyset. The planner should make this an explicit task in Wave 0
BEFORE the schema migration commits — to avoid a `NULL` storm if the keys
differ from `[ASSUMED]`.

### Parser Extension Pattern

`[VERIFIED: scripts/ingest_garmin_zip.py:217-242]` — existing parser is a
straight `.get()` from the entry dict; NULL-safe by default. Pattern:

```python
activities.append((
    activity_id,
    dt,
    entry.get("activityType", "unknown"),
    int(duration),
    round(float(distance), 2) if distance else None,
    entry.get("averageHeartRate"),
    entry.get("maxHeartRate"),
    entry.get("averagePace"),
    entry.get("trainingEffect"),
    # PHASE 19 ADDITIONS (NULL-safe):
    entry.get("activityTrainingLoad"),        # [ASSUMED key]
    entry.get("directPerceivedEffort"),       # [ASSUMED key]
    entry.get("directWorkoutFeel"),           # [ASSUMED key]
))
```

The `INSERT ... ON CONFLICT ... DO UPDATE SET` must be extended with the new
columns so re-running the backfill UPDATEs existing rows that were ingested
pre-Phase 19. `[VERIFIED: scripts/ingest_garmin_zip.py:250-263]`

### Backfill Strategy

1. Operator requests Garmin export (24–48h email turnaround).
2. Operator runs `python scripts/ingest_garmin_zip.py /path/to/export.zip`.
3. The script:
   - Runs `setup_schema()` — applies the new `ALTER TABLE` patches idempotently.
   - Parses all `*summaries.json` and `*UDSFile.json` files.
   - UPSERTs every activity and every daily biometric.
4. Operator runs verification queries via `mcp_tools/database_tool.py`:

```sql
-- Row count
SELECT COUNT(*) FROM activities;
SELECT COUNT(*) FROM daily_biometrics;

-- Date range
SELECT MIN(date), MAX(date) FROM activities;
SELECT MIN(date), MAX(date) FROM daily_biometrics;

-- NULL rates on new columns
SELECT
  COUNT(*) AS total,
  100.0 * SUM(CASE WHEN training_load IS NULL THEN 1 ELSE 0 END) / COUNT(*) AS pct_null_training_load,
  100.0 * SUM(CASE WHEN perceived_exertion IS NULL THEN 1 ELSE 0 END) / COUNT(*) AS pct_null_rpe,
  100.0 * SUM(CASE WHEN feel IS NULL THEN 1 ELSE 0 END) / COUNT(*) AS pct_null_feel
FROM activities;

SELECT
  COUNT(*) AS total,
  100.0 * SUM(CASE WHEN vo2_max IS NULL THEN 1 ELSE 0 END) / COUNT(*) AS pct_null_vo2
FROM daily_biometrics;
```

**Pre-acceptance thresholds (Plan should pin):**
- `total >= 100` for `activities` (3 years of training, even sparse, yields hundreds of rows).
- `total >= 800` for `daily_biometrics` (3 years × 365 ≈ 1095 rows; allow 25%
  device-off days).
- NULL rate on `training_load` < 60% (Garmin only computes load on workouts of
  certain types — walking, cycling, running, gym; daily-step rows may NULL).
- NULL rate on `perceived_exertion` < 95% (RPE is user-entered, often skipped;
  this column will be mostly NULL in v0).
- NULL rate on `feel` < 95% (same as RPE — user-entered).
- NULL rate on `vo2_max` < 90% (VO2 max is only estimated on certain runs/walks).

Success criterion 3 says "documented row counts and NULL rates" — there is no
threshold contract beyond "documented". Plan should still pin acceptance
numbers so a botched ingest is caught.

---

## UserProfileStore Design

### Existing Stub

`[VERIFIED: memory/firestore_db.py:391-404]`

```python
class UserProfileStore:
    def __init__(self, project_id: str, document_path: str = "users/amit") -> None: ...
    def load(self) -> dict:          # stub — raises NotImplementedError
    def update(self, patch: dict):   # stub — raises NotImplementedError
```

### Phase 19 Implementation

Fill in the stub, add `bootstrap_if_empty`. Same shape as `SelfStateStore`
`[VERIFIED: memory/firestore_db.py:660-680]`:

```python
class UserProfileStore:
    _COLLECTION = "users"
    _DOCUMENT_ID = "amit"
    _SCAFFOLD = {
        "athletic_goals": [],
        "training_constraints": [],
        "recovery_preferences": {},
        "schema_version": 1,
    }

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT_ID)

    def load(self) -> dict:
        """PROFILE-01: never raises, returns {} on any error."""
        try:
            snap = self._doc_ref.get()
            return snap.to_dict() or {} if snap.exists else {}
        except Exception:
            logger.warning("UserProfileStore.load() failed — returning empty", exc_info=True)
            return {}

    def update(self, patch: dict) -> None:
        """PROFILE-02: merge + stamp updated_at SERVER_TIMESTAMP."""
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("UserProfileStore.update() failed", exc_info=True)
            raise

    def bootstrap_if_empty(self) -> None:
        """PROFILE-03: create with empty scaffold if absent."""
        try:
            snap = self._doc_ref.get()
            if snap.exists:
                return
            self._doc_ref.set({
                **self._SCAFFOLD,
                "bootstrapped_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            })
            logger.info("UserProfileStore: bootstrapped users/amit")
        except Exception:
            logger.warning("UserProfileStore.bootstrap_if_empty() failed — skipping", exc_info=True)
```

### Bootstrap Site

`AgentOrchestrator.__init__` already bootstraps `SelfStateStore` at startup
`[VERIFIED: core/main.py:224-228]`. Add a sibling call:

```python
self._user_profile_store = _build_user_profile_store()
if self._user_profile_store is not None:
    self._user_profile_store.bootstrap_if_empty()
```

### Schema Versioning Pattern

`schema_version: 1` is the forward-compat contract. Future writes:

```python
def update_with_migration(self, patch: dict) -> None:
    current = self.load()
    if current.get("schema_version", 1) < 2:
        # Apply schema migration before merging patch
        patch = self._migrate_v1_to_v2(patch, current)
    self.update(patch)
```

Phase 19 ships only `schema_version: 1`; the migration helper is future work.

---

## Garmin Live Reads

### `fetch_garmin_training_status()`

`[VERIFIED: github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py]`
The lib exposes `get_training_status(cdate: str)` which hits
`/metrics-service/metrics/trainingstatus/aggregated/{cdate}` and
`get_max_metrics(cdate: str)` which hits
`/metrics-service/metrics/maxmet/daily/{cdate}/{cdate}`.

The exact response JSON shape is NOT documented in the lib's README. `[ASSUMED]`
based on Garmin Connect API conventions:

```python
{
    "vo2_max": float | None,
    "training_status": str | None,        # e.g., "PRODUCTIVE", "MAINTAINING", "RECOVERY", "DETRAINING", "OVERREACHING"
    "load_focus": str | None,             # e.g., "BALANCED", "HIGH_AEROBIC", "ANAEROBIC"
}
```

**Plan task:** Wave-1 first task should be "call `get_training_status` and
`get_max_metrics` from a one-shot script, dump JSON, document the exact
keys." This is a 5-minute probe that locks the mapping before parser code
is written.

Pattern mirrors `fetch_garmin_today` `[VERIFIED: mcp_tools/garmin_tool.py:56-127]`:

```python
def fetch_garmin_training_status() -> dict:
    api = _authed_garmin_client()  # extract token-cache plumbing from fetch_garmin_today
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    try:
        ts_raw = api.get_training_status(today)
        mm_raw = api.get_max_metrics(today)
        return {
            "vo2_max": _safe_extract(mm_raw, "...", "vO2MaxValue"),
            "training_status": _safe_extract(ts_raw, "...", "trainingStatus"),
            "load_focus": _safe_extract(ts_raw, "...", "loadFocus"),
        }
    except Exception as exc:
        raise GarminUnavailableError(f"training_status fetch failed: {exc}") from exc
```

**Recommendation:** Extract the token-cache plumbing (`_get_garmin_tokens_from_firestore`
+ `_save_garmin_tokens_to_firestore` + the login dance) into a private
`_authed_garmin_client()` helper inside `mcp_tools/garmin_tool.py` so it's
shared across `fetch_garmin_today`, `fetch_garmin_training_status`,
`fetch_garmin_activities`. Avoids 3× duplication.

### `fetch_garmin_activities(days=7)`

Uses `get_activities_by_date(startdate, enddate)`. `[VERIFIED]`. Returns a list
of activity dicts; normalize to:

```python
{
    "activity_id": int,
    "date": str,                    # ISO 8601
    "type": str,
    "duration_sec": int,
    "distance_m": float | None,
    "perceived_exertion": int | None,
    "feel": int | None,
    "training_load": float | None,
}
```

**Live vs. Postgres decision (GARMIN-02):** GARMIN-02 wording says
`fetch_garmin_activities(days=7)`. The Postgres backfill should populate the
same data, but for "recent 24h" the live API catches activities that haven't
been re-ingested yet. Recommendation: **live API for `fetch_garmin_activities`
(real-time)**, **Postgres for ACWR analytical queries (historical)**.

### `compute_acwr(activities_28d)`

Pure-Python utility. No live I/O. Signature:

```python
def compute_acwr(activities: list[dict], today: date | None = None) -> dict:
    """Acute:Chronic Workload Ratio.

    Args:
        activities: List of activity dicts with at minimum {date, training_load}.
        today: Reference date (defaults to today). Acute window = today-6..today.

    Returns:
        {
            "acute": float,           # mean training_load over last 7 days
            "chronic": float | None,  # mean training_load over last 28 days
            "ratio": float | None,    # acute / chronic, None when chronic baseline insufficient
        }
    """
```

**"Insufficient chronic baseline" definition** (recommendation):
- Need ≥ 14 days with at least 1 activity each in the 28-day window.
- If fewer than 14 days have load data, return `ratio=None`.

Math per `[CITED: pmc.ncbi.nlm.nih.gov/articles/PMC7047972/]` and
`[CITED: scienceforsport.com/acutechronic-workload-ratio/]`:
- Acute window: 7 days (rolling sum or mean).
- Chronic window: 28 days (4 weeks rolling mean).
- "Sweet spot" 0.8–1.3; spike ≥ 1.5 = elevated injury risk.

```python
def compute_acwr(activities, today=None):
    today = today or datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    by_date = collections.defaultdict(float)
    for a in activities:
        d = date.fromisoformat(a["date"][:10])
        load = a.get("training_load")
        if load is not None:
            by_date[d] += float(load)

    acute_days = [today - timedelta(days=i) for i in range(7)]
    chronic_days = [today - timedelta(days=i) for i in range(28)]

    acute = sum(by_date.get(d, 0) for d in acute_days) / 7.0
    chronic_days_with_data = sum(1 for d in chronic_days if d in by_date)
    if chronic_days_with_data < 14:
        return {"acute": acute, "chronic": None, "ratio": None}
    chronic = sum(by_date.get(d, 0) for d in chronic_days) / 28.0
    return {"acute": acute, "chronic": chronic, "ratio": acute / chronic if chronic else None}
```

**Bonus convenience:** `compute_acwr_from_db()` — a thin wrapper that reads
the last 28 days from Postgres via `query_health_database` and calls
`compute_acwr`. Used by autonomous-tick layer-0.

---

## Google Fit Integration

### OAuth Scope Addition

`[VERIFIED: developers.google.com/fit/datatypes/nutrition]` — exact scope:
- Read: `https://www.googleapis.com/auth/fitness.nutrition.read`
- Write: `https://www.googleapis.com/auth/fitness.nutrition.write` (NOT
  needed for Phase 19 — Klaus only reads)

Update `core/auth_google.py:43-44`:

```python
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
FITNESS_NUTRITION_READ_SCOPE = "https://www.googleapis.com/auth/fitness.nutrition.read"

class GoogleAuthManager:
    SCOPES: list[str] = [GMAIL_SCOPE, CALENDAR_SCOPE, FITNESS_NUTRITION_READ_SCOPE]
```

**Incremental authorization vs. full re-consent:**
`[CITED: developers.google.com/identity/protocols/oauth2/web-server]`
- Setting `access_type='offline'` + `include_granted_scopes='true'` allows
  expanding scopes without revoking the old grant.
- BUT: the existing cached token has scopes `[gmail.modify, calendar]`. When
  `GoogleAuthManager._load_cached_token` parses it with `from_authorized_user_info(payload, SCOPES_INCLUDING_NUTRITION)`, the credential will be marked invalid (scope mismatch).
- **Operator must re-run `python -m core.auth_google`** to refresh the consent
  flow with the new scope set. The refresh token issued will cover all 3 scopes.
- ALTERNATIVE if operator wants to avoid re-consent: keep the old token
  for Gmail/Calendar, build a SEPARATE `GoogleAuthManager` with only the
  Fit scope inside `google_fit_tool.py`. **Not recommended** — leads to two
  cached tokens, two refresh paths, two secret-manager versions. Cleaner to
  re-consent once.

### Reading Nutrition Data

REST endpoint: `POST https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate`
`[VERIFIED: developers.google.com/fit/rest/v1/reference/users/dataset/aggregate]`

Request body:

```json
{
  "aggregateBy": [{"dataTypeName": "com.google.nutrition"}],
  "bucketByTime": {"durationMillis": 3600000},
  "startTimeMillis": <start>,
  "endTimeMillis": <end>
}
```

For Klaus's case (read individual meals, not aggregates), use the dataset
read endpoint instead: `GET /fitness/v1/users/me/dataSources/{dsid}/datasets/{startNanos}-{endNanos}`. But first the tool must enumerate Fit data sources:

`GET /fitness/v1/users/me/dataSources?dataTypeName=com.google.nutrition`

This returns the user's Fit-connected nutrition sources (Lifesum, Health Connect, etc).

Response payload per nutrition data point `[VERIFIED: developers.google.com/fit/datatypes/nutrition]`:

```json
{
  "startTimeNanos": "1716624000000000000",
  "endTimeNanos": "1716624000000000000",
  "dataTypeName": "com.google.nutrition",
  "originDataSourceId": "raw:com.google.nutrition:com.sillens.shapeupclub:...",
  "value": [
    {
      "mapVal": [
        {"key": "calories", "value": {"fpVal": 420.0}},
        {"key": "protein", "value": {"fpVal": 35.0}},
        {"key": "fat.total", "value": {"fpVal": 14.5}},
        {"key": "carbs.total", "value": {"fpVal": 38.0}}
      ]
    },
    {"intVal": 3},      // meal_type: 3 = Lunch
    {"stringVal": "grilled chicken salad"}  // food_item (if Lifesum populates it)
  ]
}
```

Nutrient keys: `calories` (kcal), `protein` / `carbs.total` / `fat.total`
(grams), plus optional `sodium` / `cholesterol` / `dietary_fiber` / `sugar`
(grams or mg).

Meal type enum: `1=Unknown, 2=Breakfast, 3=Lunch, 4=Dinner, 5=Snack`.

### `mcp_tools/google_fit_tool.py` Shape

```python
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")


class GoogleFitUnavailableError(Exception): pass


def _fit_service():
    """Build a Fitness v1 service via the shared GoogleAuthManager."""
    from core.auth_google import build_auth_manager_from_env
    manager = build_auth_manager_from_env()
    return build("fitness", "v1", credentials=manager.get_credentials(), cache_discovery=False)


def fetch_recent_meals(hours: int = 24) -> list[dict]:
    """Return Fit nutrition entries from the last `hours` hours.

    Returns:
        List of normalized meal dicts:
        {
            "source_id": str,         # for MealStore idempotency
            "timestamp": str,         # ISO 8601 Israel time
            "meal_type": int,         # 1-5 per Fit enum
            "calories": float | None,
            "protein_g": float | None,
            "carbs_g": float | None,
            "fat_g": float | None,
            "food_item": str | None,
            "source": str,            # "google_fit"
        }
    """
    svc = _fit_service()
    end = datetime.now(_TZ)
    start = end - timedelta(hours=hours)
    start_nanos = int(start.timestamp() * 1e9)
    end_nanos = int(end.timestamp() * 1e9)

    # Discover nutrition data sources
    sources = (svc.users().dataSources()
                  .list(userId="me", dataTypeName="com.google.nutrition")
                  .execute()).get("dataSource", [])

    out: list[dict] = []
    for src in sources:
        ds_id = src["dataStreamId"]
        try:
            ds = (svc.users().dataSources().datasets()
                     .get(userId="me", dataSourceId=ds_id,
                          datasetId=f"{start_nanos}-{end_nanos}")
                     .execute())
        except Exception:
            logger.warning("google_fit: dataset.get failed for %s", ds_id, exc_info=True)
            continue
        for point in ds.get("point", []):
            out.append(_normalize_point(point, ds_id))
    return out


def _normalize_point(point: dict, ds_id: str) -> dict:
    nanos = int(point.get("startTimeNanos", 0))
    ts = datetime.fromtimestamp(nanos / 1e9, _TZ).isoformat()
    source_id = f"{ds_id}:{nanos}"  # idempotency key

    # Parse value array per Fit schema
    macros = {}
    meal_type = 1
    food_item = None
    for v in point.get("value", []):
        if "mapVal" in v:
            for kv in v["mapVal"]:
                macros[kv["key"]] = kv["value"].get("fpVal")
        elif "intVal" in v:
            meal_type = v["intVal"]
        elif "stringVal" in v:
            food_item = v["stringVal"]

    return {
        "source_id": source_id,
        "timestamp": ts,
        "meal_type": meal_type,
        "calories": macros.get("calories"),
        "protein_g": macros.get("protein"),
        "carbs_g": macros.get("carbs.total"),
        "fat_g": macros.get("fat.total"),
        "food_item": food_item,
        "source": "google_fit",
    }


def sync_recent_meals(since_hours: int, store) -> list[dict]:
    """Fetch + upsert into MealStore. Returns the meals just synced."""
    meals = fetch_recent_meals(hours=since_hours)
    for m in meals:
        try:
            store.upsert(source_id=m["source_id"], meal=m)
        except Exception:
            logger.warning("sync_recent_meals: upsert failed for %s", m["source_id"], exc_info=True)
    return meals
```

### Lifesum → Google Fit Timing

`[ASSUMED + CITED: lifesum.helpshift.com/hc/en/3-lifesum/faq/38-how-do-i-connect-to-google-fit/]`

- Lifesum connects to Google Fit via Health Connect on Android.
- Sync is approximately near-real-time but can take up to ~30 minutes for
  nutrition entries to appear in Fit (per general Health Connect propagation
  behavior — exact timing not officially documented).
- Klaus's autonomous tick runs every 20 minutes — meals logged in Lifesum will
  typically appear in MealStore on the SECOND tick after logging, sometimes
  the first.

**Success criterion 2 wording:** "Lifesum meal → Google Fit (~30 min) → next
autonomous tick (≤20 min) writes meals/{date}/{timestamp} to Firestore" —
this matches the observed propagation. The plan can document this as the
expected latency contract.

### Rate Limits

`[CITED: developers.google.com/fit/rest/v1]` — Google Fit API quota is
generally generous (per-user per-day quotas in the tens of thousands of
requests for the free tier). One autonomous tick = 1 dataSources.list +
N dataset.get calls (where N = number of nutrition sources, typically 1–2).
At 43 ticks/day × 2 calls = 86 requests/day — well within the limit.

### Pagination / Delta Sync

Fit dataset.get returns all points in the time window in one response (no
pagination for typical meal volumes — even a heavy eater logs < 20 meals/day).
For multi-day backfills, page by 1-day windows.

**Delta-sync via `source_id`:** Since MealStore idempotently upserts on
`source_id` (= `dataStreamId + ":" + startTimeNanos`), re-syncing the same
window is safe — duplicates are merged into the same Firestore doc.

---

## MealStore Design

### Firestore Path

Per NUTR-02: `meals/{date}/{timestamp}`. Recommendation: use sub-collections
to keep doc-listing efficient at scale:

```
meals (collection)
└─ {YYYY-MM-DD} (document)
   └─ timestamps (sub-collection)
      └─ {source_id} (document)
         { timestamp, calories, protein_g, carbs_g, fat_g, meal_type,
           food_item, source, source_id, updated_at }
```

Why sub-collections: a single doc would balloon with 1000+ meals over time.
Sub-collections keep day-level reads (the morning briefing's only use case)
to a single `.collection("timestamps").stream()` call.

Idempotency key: **`source_id` from `_normalize_point`** = Fit's
`dataStreamId + ":" + startTimeNanos`. Re-syncs produce no duplicates.

### `MealStore.get_yesterday_aggregate(date_str)`

For morning briefing's "totals + biggest gap":

```python
def get_day_aggregate(self, date_str: str) -> dict:
    """Return totals + per-meal-type breakdown + biggest_gap_minutes.

    Returns {} when no meals were logged on date_str.
    """
    meals = self.get_day(date_str)  # sorted by timestamp
    if not meals:
        return {}

    totals = {
        "calories": sum(m.get("calories") or 0 for m in meals),
        "protein_g": sum(m.get("protein_g") or 0 for m in meals),
        "carbs_g": sum(m.get("carbs_g") or 0 for m in meals),
        "fat_g": sum(m.get("fat_g") or 0 for m in meals),
    }
    by_type = collections.defaultdict(list)
    for m in meals:
        by_type[m.get("meal_type", 1)].append(m)

    biggest_gap_minutes = 0
    for i in range(1, len(meals)):
        t_prev = datetime.fromisoformat(meals[i-1]["timestamp"])
        t_curr = datetime.fromisoformat(meals[i]["timestamp"])
        gap = (t_curr - t_prev).total_seconds() / 60.0
        biggest_gap_minutes = max(biggest_gap_minutes, gap)

    return {
        "meal_count": len(meals),
        "totals": totals,
        "by_type": {k: len(v) for k, v in by_type.items()},
        "biggest_gap_minutes": round(biggest_gap_minutes, 1),
        "meals": meals,  # ordered list — included so prompt can show breakdown
    }
```

**"Silently omit on no-meals day"** is controlled by `if not meals: return {}`
— the prompt then sees `nutrition: {}` and the recap section's template
is rendered conditionally (Jinja-style `{% if nutrition %}`-equivalent, but
since these prompts are plain strings, the morning-briefing compose function
must build the data block conditionally OR the prompt must instruct "omit
section entirely if nutrition is empty"). Recommendation: have
`_compose_briefing` strip empty keys before serializing `today_data` to JSON;
prompt instructs "if `nutrition` key is missing, do not mention it". Same
pattern as `garmin.state == 2` in the existing prompt
`[VERIFIED: prompts/morning_briefing.md:91-93]`.

---

## Autonomous Tick Extension

### Where to Add (Layer 0)

`[VERIFIED: core/autonomous.py:187-318]` — `gather_situation()` has 8 sources
labeled (a)–(h). Add three new sources (i), (j), (k) per the snippet in §
"Pattern 2: Per-source try/except in gather" above. Insert BEFORE the
`gathered["empty"] = _is_empty_signals(gathered)` line.

### Update `_is_empty_signals`

`[VERIFIED: core/autonomous.py:167-184]` currently checks:
- `ticktick_overdue`
- `due_followups`
- `_calendar_has_gap_or_overload`

Add: a new meal in `meals_since_last_tick` is a potential trigger. Also, an
ACWR spike (`ratio >= 1.5`) could be a trigger, but per locked decisions
no thresholds in v3.0 — leave ACWR informational, not gating. Same for
training_status.

**Recommendation:**
```python
def _is_empty_signals(situation):
    if situation.get("ticktick_overdue"): return False
    if situation.get("due_followups"): return False
    if _calendar_has_gap_or_overload(...): return False
    if situation.get("meals_since_last_tick"): return False  # PHASE 19
    return True
```

`training_status` and `acwr` are NOT in the empty-signals gate. They're
context for triage prompts, not standalone triggers — meals are the only
new active trigger.

### Update `_build_triage_prompt`

`[VERIFIED: core/autonomous.py:353-396]` — extend the JSON snapshot to include
the new fields:

```python
snap = {
    "calendar": situation.get("calendar", []),
    "ticktick_overdue": situation.get("ticktick_overdue", []),
    "unread_email_count": situation.get("unread_email_count", 0),
    "due_followups": situation.get("due_followups", []),
    # PHASE 19 additions:
    "meals_since_last_tick": situation.get("meals_since_last_tick", []),
    "training_status": situation.get("training_status", {}),
    "acwr": situation.get("acwr", {"ratio": None}),
}
```

Also extend `_compose_layer2`'s synthetic-content JSON `[VERIFIED: core/autonomous.py:520-533]`
the same way.

### Update Eval Fixture Contract

`[VERIFIED: tests/test_evals.py::TestFixtureSchema`] (per STATE.md) — fixture
schema currently is `{calendar, ticktick_overdue, unread_email_count,
due_followups, hours_since_contact, recent_journal_digest, self_state,
today_outreach_log, now_context}`. Phase 19 adds 3 new keys. The eval
fixtures and the test guard must be extended to match, otherwise the eval
harness drifts from production. **Plan task:** update fixture schema, add
empty-defaults to existing 5 seed fixtures so they still parse.

### Tick-Interval Confirmation

`[VERIFIED: core/autonomous.py:46-48]` — `*/20 7-21` = 43 ticks/day,
Asia/Jerusalem. **Phase 19 makes ZERO scheduler changes.** Confirmed.

---

## Morning Briefing Extension

### Where to Add Nutrition Recap (NUTR-05, NUTR-07)

`[VERIFIED: core/morning_briefing.py:174-230]` — `_gather_data(today_iso)`
has 5 sources today: weather, calendar, email, garmin, tasks.

Add yesterday-nutrition aggregation:

```python
# Yesterday's nutrition recap (PHASE 19 — NUTR-05)
try:
    from memory.firestore_db import MealStore
    yesterday = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
    ms = MealStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )
    agg = ms.get_day_aggregate(yesterday)
    if agg:
        data["nutrition"] = agg            # NUTR-07: omit key entirely on empty
except Exception:
    logger.warning("morning_briefing: meals aggregate failed", exc_info=True)
```

Then in `_compose_briefing`, when serializing `today_data` to JSON, the
`nutrition` key is either present (recap rendered by the LLM) or absent
(prompt instructs "no nutrition section").

### Postgres Writeback (GARMIN-05)

`[VERIFIED: GARMIN-05 wording]` — morning briefing's `_gather_data()` must
write fresh daily biometrics + activities into Postgres on each tick
(best-effort).

Recommendation: after the existing Garmin fetch succeeds:

```python
# After data["garmin"] is populated (existing code lines 211-220)
try:
    from mcp_tools.garmin_tool import write_today_biometrics_to_postgres
    if data.get("garmin", {}).get("state") == 1:
        write_today_biometrics_to_postgres(data["garmin"])  # best-effort UPSERT
except Exception:
    logger.warning("morning_briefing: Postgres biometrics writeback failed", exc_info=True)
```

The writeback uses the same `INSERT ... ON CONFLICT (date) DO UPDATE SET ...`
pattern as `parse_and_ingest_wellness` `[VERIFIED: scripts/ingest_garmin_zip.py:171-200]`.

### Update `prompts/morning_briefing.md`

Add a new section between Garmin recovery (already part of summary line) and
the Schedule block:

```markdown
---

🥗 Yesterday's Nutrition (only when nutrition key present in data)
Totals: ~{calories} kcal / {protein_g}g P / {carbs_g}g C / {fat_g}g F
Meals: {meal_count} ({meal-type breakdown})
{Note about biggest gap if > 6 hours}

If nutrition key is absent from data, OMIT this entire section. Do not
write "no nutrition data" or any placeholder.
```

This is the NUTR-07 "silently omitted" contract — handled by prompt
instruction + presence/absence of the JSON key.

---

## Smart Agent Prompt Wiring

### `render_smart_system` Extension (PROMPT-01)

`[VERIFIED: core/main.py:232-283]` — current implementation chains 4
`.replace()` calls. Add a 5th:

```python
def render_smart_system(self, template: str) -> str:
    ...
    # PHASE 19: training profile block
    training_profile_snippet = ""
    if self._user_profile_store is not None:
        profile = self._user_profile_store.load()
        non_empty = {k: v for k, v in profile.items()
                     if k not in ("updated_at", "bootstrapped_at", "schema_version") and v}
        if non_empty:
            lines = ["**Training profile:**"]
            for k, v in non_empty.items():
                lines.append(f"- {k}: {v}")
            training_profile_snippet = "\n".join(lines)
        # else: empty profile → empty string (the prompt instructs "ask the user")

    return (
        template
        .replace("{self_md}", self._self_md_content)
        .replace("{self_state}", self_state_snippet)
        .replace("{journal_digest}", journal_digest)
        .replace("{training_profile}", training_profile_snippet)
        .replace("{today_date}", today_label)
    )
```

### `prompts/smart_agent.md` Extension (PROMPT-02)

Add `{training_profile}` placeholder near the top (after `{journal_digest}`):

```markdown
{self_md}

{self_state}

{journal_digest}

{training_profile}

---

You are Klaus, a hyper-competent personal AI assistant...
```

Add a new section before "LONG-TERM MEMORY":

```markdown
TRAINING & ATHLETIC COACHING

You read Amit's training data (Garmin training status, recent activities,
ACWR) and nutrition data (Google Fit, Lifesum-sourced) on demand via worker-
delegated tools (`fetch_training_status`, `fetch_recent_activities`,
`fetch_recent_meals`), and read his training profile (goals, constraints,
recovery preferences) via the brain-direct `get_training_profile` tool.

If the training profile is empty (no goals or constraints recorded), do NOT
invent thresholds, targets, or scheduling buffers. Instead:
1. Answer questions using just the metric (e.g., "Your ACWR this week is
   1.42, sir. That puts you above the typical sweet spot of 0.8–1.3.").
2. When commentary would benefit from a personalized rule (a target HR zone,
   a weekly mileage cap), politely ask Sir to state his preference, then
   call `update_training_profile` to record it.
3. Never make up a personalized rule. The discipline here is honesty over
   coverage.

Sharper edge: training and nutrition are areas where Sir asked for direct
coaching. The JARVIS register holds, but pull less of the C-3PO hedging.
"Sir, that's your second protein-free meal in a row before a heavy lift —
worth reconsidering" is in voice. Avoid "I'm afraid I must mention" softening
when the metric is unambiguous.
```

### `prompts/autonomous_triage.md` Extension (NUTR-06)

Add a section after "Repeat-suppression as info, not block":

```markdown
## Meals as triggers (Phase 19)

A new meal in `meals_since_last_tick` is a candidate trigger to speak up.
Speak when one of:
- A large macro imbalance vs. the time of day (e.g., 800 kcal of carbs with
  no protein logged before a workout block in the next 2h).
- A long gap since the last meal (e.g., 6+ hours, no breakfast logged by
  noon).
- A meal type out of pattern given the calendar (e.g., a heavy "Dinner"
  entry at 14:00 while the schedule shows an evening workout — the food
  may not be timed well for the session).

When `training_profile` is empty (most of v3.0), do NOT cite specific
numeric thresholds. Use general nutritional reasoning ("low protein before
a heavy lift", "long gap may affect afternoon energy"). When the profile
becomes populated in a later session, the same triggers will read it.

If `meals_since_last_tick` is empty AND no other signal is active, prefer
silence. Meals alone are not a quota — only judge-out when the signal is
genuine.
```

### `prompts/meal_audit.md` (NUTR-08, new file)

```markdown
## Meal Audit — non-personalized critique guidance

When Klaus assesses a meal (mid-day in the autonomous tick, or in the
morning briefing recap), the critique uses these heuristics in absence of
personalized rules:

### Nutrition density
- Calories without protein/fat/fiber = low density. A 600 kcal carb-only
  meal is lower density than a 600 kcal meal with 30g protein + 15g fat.

### Protein adequacy (general adult heuristic)
- ~25–40g per meal is a reasonable target band.
- < 15g per meal that is not labeled "snack" is light on protein.
- A day-total < 100g for an active adult is light overall.

### Carb appropriateness vs. training context
- Heavy carbs (>80g) before a sedentary block: high glycemic load with
  nowhere to go.
- Light carbs (<30g) before an intense session: may underfuel.

### When to comment proactively (autonomous tick)
- Speak up on a clear timing miss (e.g., long-gap before workout, or carb-
  heavy meal pre-sleep).
- Stay silent on a normal meal pattern. The bar is "Sir would thank me for
  noticing", not "I could find something to say".

### Voice
- JARVIS register, leaner on hedging than usual. Direct observations.
- Never moralize. Never use the words "good food" or "bad food".
- Cite the metric, not the verdict ("400 kcal carb-only" beats "junk food").
```

This file is referenced from both `prompts/autonomous_triage.md` (via the
tick-brain's training/nutrition awareness) and the brain's smart_agent
prompt (via the new TRAINING & ATHLETIC COACHING section). Plan can keep
it as a standalone file referenced as context, OR inline it into both —
recommendation is **standalone file** so non-personalized heuristics can
be tuned in one place.

---

## Tool Registration

### 5 New Tool Schemas (TOOL_SCHEMAS list `[VERIFIED: core/tools.py:58-746]`)

```python
{
    "name": "get_training_profile",
    "description": "Read Amit's stored training profile (goals, constraints, recovery preferences). Brain-direct.",
    "input_schema": {"type": "object", "properties": {}, "required": []}
},
{
    "name": "update_training_profile",
    "description": "Merge new fields into Amit's stored training profile. Brain-direct. Always confirms with the user before recording.",
    "input_schema": {
        "type": "object",
        "properties": {
            "patch": {
                "type": "object",
                "description": "Dict of fields to merge. Recognized top-level keys: athletic_goals (list), training_constraints (list), recovery_preferences (object)."
            }
        },
        "required": ["patch"]
    }
},
{
    "name": "fetch_training_status",
    "description": "Get Garmin training status, VO2 max, and load focus for today. Worker-delegated.",
    "input_schema": {"type": "object", "properties": {}, "required": []}
},
{
    "name": "fetch_recent_activities",
    "description": "Get the last N days of Garmin activities (default 7). Worker-delegated.",
    "input_schema": {
        "type": "object",
        "properties": {"days": {"type": "integer", "description": "Days back to fetch. Default 7."}},
        "required": []
    }
},
{
    "name": "fetch_recent_meals",
    "description": "Get nutrition entries from Google Fit (Lifesum-sourced) in the last N hours (default 24). Worker-delegated.",
    "input_schema": {
        "type": "object",
        "properties": {"hours": {"type": "integer", "description": "Hours back to fetch. Default 24."}},
        "required": []
    }
}
```

### 5 New Handlers (`_HANDLERS` dict `[VERIFIED: core/tools.py:1340-1372]`)

```python
"get_training_profile":     lambda args: _handle_get_training_profile(),
"update_training_profile":  lambda args: _handle_update_training_profile(**args),
"fetch_training_status":    lambda args: _handle_fetch_training_status(),
"fetch_recent_activities":  lambda args: _handle_fetch_recent_activities(**args),
"fetch_recent_meals":       lambda args: _handle_fetch_recent_meals(**args),
```

### `SMART_AGENT_DIRECT_TOOLS` update `[VERIFIED: core/tools.py:39-52]`

Add `get_training_profile` and `update_training_profile`. Do NOT add the
three fetch tools — they go through `delegate_to_worker`.

### `WORKER_TOOL_SCHEMAS` exclusion `[VERIFIED: core/tools.py:750-766]`

Add `get_training_profile` and `update_training_profile` to the exclusion set
so they are NOT exposed to the worker.

---

## SELF.md Regeneration

### Auto-Pickup (PROMPT-03)

`[VERIFIED: core/self_manifest.py:49-78]` — `_compute_schema_hash` greps
`"name":` from `core/tools.py`. Adding the 5 new schemas automatically
changes the SHA. The heartbeat code-staleness check
`[VERIFIED: core/heartbeat.py:378]` will flag the SHA mismatch if SELF.md
is not regenerated.

**Plan must include:** `python core/self_manifest.py` as a build step.

The full `core/self_manifest.py` script writes `docs/SELF.md` listing all
tools, cron jobs, channels, memory stores, and the model map. After Phase 19,
new tools appear in the "## Tools" section of SELF.md automatically.

### Verification

After running `python core/self_manifest.py`, success criterion 6 is:
- `grep -c "get_training_profile" docs/SELF.md` → 1
- `grep -c "update_training_profile" docs/SELF.md` → 1
- `grep -c "fetch_training_status" docs/SELF.md` → 1
- `grep -c "fetch_recent_activities" docs/SELF.md` → 1
- `grep -c "fetch_recent_meals" docs/SELF.md` → 1

---

## Common Pitfalls

### Pitfall 1: OAuth scope expansion breaks existing cached token

**What goes wrong:** Adding `fitness.nutrition.read` to `GoogleAuthManager.SCOPES`
without re-consent makes `from_authorized_user_info(payload, SCOPES)` mark
the existing token as invalid — silently. Gmail and Calendar suddenly fail.
**Why it happens:** `google-auth` validates that the cached creds cover the
requested scopes. Mismatch = invalid.
**How to avoid:** Plan must include explicit operator step: run
`python -m core.auth_google` after the scope is added, on a machine where
the operator can complete browser consent. Then deploy.
**Warning signs:** Cloud Run logs show `RefreshError: invalid_scope` or
Gmail tool starts returning 401.

### Pitfall 2: Lifesum sync timing variance

**What goes wrong:** Meals logged in Lifesum appear in Google Fit anywhere
from ~30 seconds to ~30 minutes later, depending on Android background-sync
state and Health Connect propagation. Klaus's autonomous tick might miss a
meal on tick N, then re-sync on tick N+1, then re-sync again on tick N+2
because of out-of-order timestamps.
**Why it happens:** Health Connect ↔ Fit sync is asynchronous and
non-deterministic.
**How to avoid:** Idempotent upsert on `source_id` (combination of
`dataStreamId` + `startTimeNanos`). Even if a meal is re-synced 5 times,
MealStore writes the same doc 5 times — no duplicates.
**Warning signs:** `meals_since_last_tick` returns the same meal twice across
ticks. NOT a bug if idempotency holds.

### Pitfall 3: Garmin export field names differ from `[ASSUMED]` set

**What goes wrong:** The parser code references `entry.get("activityTrainingLoad")`
but the actual JSON key is `trainingLoad` (no "activity" prefix) — the parser
silently fills the column with NULLs.
**Why it happens:** Garmin field naming is inconsistent across export versions
and live API endpoints. Documentation is sparse.
**How to avoid:** Wave-0 task: open the real export zip, dump `keys()` of
the first activity entry, lock the mapping. Add a unit test that asserts
known keys are present in a fixture entry.
**Warning signs:** Backfill row count looks right (e.g., 800 rows) but NULL
rate on `training_load` is 100%.

### Pitfall 4: Empty MealStore.get_day_aggregate vs. no aggregation key

**What goes wrong:** Morning briefing prompt expects either `data["nutrition"]`
populated OR the key absent. If `get_day_aggregate` returns
`{"meal_count": 0, ...}` instead of `{}`, the prompt sees the key, renders
"0 meals, 0 kcal" — violates NUTR-07 "silently omitted".
**Why it happens:** Truthy-empty vs. absent is a real distinction.
**How to avoid:** `get_day_aggregate` returns `{}` (not `{"meal_count": 0}`)
when no meals exist. `_gather_data` does `if agg: data["nutrition"] = agg`.
**Warning signs:** Morning briefing shows "Yesterday's Nutrition: 0 meals"
on no-data days.

### Pitfall 5: ACWR computed on too-short history yields misleading ratio

**What goes wrong:** New user (3 days of data); `compute_acwr` returns
`acute=120, chronic=15, ratio=8.0` — the brain reports "ACWR 8.0,
catastrophic". Reality: not enough history.
**Why it happens:** No guard on chronic-window data sufficiency.
**How to avoid:** Insufficient-baseline guard returning `ratio=None`. The
prompt instructs to say "chronic baseline insufficient" instead of a number.
**Warning signs:** ACWR ratio > 4.0 in early data. (Even an injury-bound
athlete rarely exceeds 2.0.)

### Pitfall 6: Updating fixture schema breaks existing 5 eval fixtures

**What goes wrong:** Phase 18 locked `tests/test_evals.py::TestFixtureSchema`
to a 9-key shape `[VERIFIED: STATE.md Phase 18-04]`. Phase 19 adds 3 keys
(`meals_since_last_tick`, `training_status`, `acwr`). If the test guard isn't
updated, all 5 fixtures fail.
**Why it happens:** Phase 18 contract was strict on purpose to catch drift.
**How to avoid:** Plan task: update `TestFixtureSchema` to include the 3 new
keys (with empty defaults), AND add empty defaults to all 5 fixture JSON
files (`0001..0005-*.json`).
**Warning signs:** `pytest tests/test_evals.py` fails with `KeyError` on
fixture load.

### Pitfall 7: Bootstrap order in `AgentOrchestrator.__init__`

**What goes wrong:** `bootstrap_if_empty` for `UserProfileStore` is called
before the LLMClient is built; if it raises (despite the `try/except`),
the entire orchestrator construction fails — and per
`_get_orchestrator()` double-checked-locking, that means EVERY autonomous
tick on this Cloud Run instance is now broken.
**Why it happens:** Construction-time work that crashes the singleton.
**How to avoid:** `UserProfileStore.bootstrap_if_empty()` follows the
`SelfStateStore` pattern — wraps all I/O in `try/except` and logs without
raising `[VERIFIED: memory/firestore_db.py:660-680]`. Plan must enforce
this. Test that bootstrap with a broken Firestore mock does not raise.
**Warning signs:** Cloud Run logs show repeated `AgentOrchestrator()`
construction failures after Phase 19 deploy.

---

## Code Examples

### Example 1: New Firestore store skeleton

`[VERIFIED: pattern from memory/firestore_db.py:683-773 JournalStore]`

```python
class MealStore:
    _COLLECTION = "meals"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, source_id: str, meal: dict) -> None:
        try:
            date_str = meal["timestamp"][:10]
            (self._col.document(date_str)
                .collection("timestamps").document(source_id)
                .set({**meal, "source_id": source_id, "updated_at": firestore.SERVER_TIMESTAMP},
                     merge=True))
        except Exception:
            logger.error("MealStore.upsert(%r) failed", source_id, exc_info=True)
            raise

    def get_day(self, date_str: str) -> list[dict]:
        try:
            snaps = self._col.document(date_str).collection("timestamps").stream()
            return sorted((s.to_dict() for s in snaps), key=lambda d: d.get("timestamp", ""))
        except Exception:
            logger.warning("MealStore.get_day(%r) failed", date_str, exc_info=True)
            return []
```

### Example 2: Brain-direct tool handler

`[VERIFIED: pattern from core/tools.py:1297-1318 _handle_list_followups]`

```python
def _handle_get_training_profile() -> str:
    """Return the user training profile dict as JSON string."""
    from memory.firestore_db import UserProfileStore
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    return json.dumps(store.load())


def _handle_update_training_profile(patch: dict) -> str:
    """Merge a patch into the user training profile."""
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

### Example 3: ACWR pure function

```python
import collections
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Jerusalem")


def compute_acwr(activities: list[dict], today: date | None = None) -> dict:
    """ACWR = mean(7d training_load) / mean(28d training_load).

    Returns ratio=None when chronic baseline has < 14 days of data.
    """
    today = today or datetime.now(_TZ).date()
    by_date = collections.defaultdict(float)
    for a in activities:
        try:
            d = date.fromisoformat(a["date"][:10])
        except (KeyError, ValueError):
            continue
        load = a.get("training_load")
        if load is not None:
            by_date[d] += float(load)

    acute_days = [today - timedelta(days=i) for i in range(7)]
    chronic_days = [today - timedelta(days=i) for i in range(28)]

    acute = sum(by_date.get(d, 0.0) for d in acute_days) / 7.0
    chronic_days_with_data = sum(1 for d in chronic_days if d in by_date)
    if chronic_days_with_data < 14:
        return {"acute": round(acute, 1), "chronic": None, "ratio": None}
    chronic = sum(by_date.get(d, 0.0) for d in chronic_days) / 28.0
    ratio = (acute / chronic) if chronic else None
    return {
        "acute": round(acute, 1),
        "chronic": round(chronic, 1),
        "ratio": round(ratio, 2) if ratio is not None else None,
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Stub `UserProfileStore` (Phase 5 — `NotImplementedError`) | Filled-in store with `bootstrap_if_empty` | Phase 19 | Brain now has a stable place to read/write user profile |
| Garmin only used for "today" snapshot | Live + Postgres-backed history | Phase 19 (Postgres backfill via commit `2c8be7a` infra, schema this phase) | ACWR queries possible |
| No nutrition data | Google Fit Nutrition (Lifesum-sourced) | Phase 19 | Klaus has visibility into meals for the first time |
| Single OAuth scope set (Gmail + Calendar) | + `fitness.nutrition.read` | Phase 19 | One-time operator re-consent required |
| Eval fixture schema 9-key | 12-key (adds meals/training/acwr) | Phase 19 | Existing 5 fixtures need empty defaults backfilled |

**Deprecated/outdated:**
- `psycopg2.tz.FixedOffset(0)` `[VERIFIED: scripts/ingest_garmin_zip.py:226]`
  — should be `datetime.timezone.utc`. Opportunistic fix when this file is
  edited for SCHEMA-01.
- Photo-audit meal pipeline (was the original v3.0 design before locked
  decisions chose Google Fit) — superseded.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Garmin export key for training load is `activityTrainingLoad` | Garmin Export Field Map | **RESOLVED — see § Deep Research §1.** HIGH confidence (GarminDB `garmin_json_data.py:321`, garmin-grafana `garmin_fetch.py:726`). Field lives in `summaryDTO` of `activity_details_*.json`. |
| A2 | Garmin export key for RPE is `directWorkoutRpe` (was assumed `directPerceivedEffort`) | Garmin Export Field Map | **RESOLVED — see § Deep Research §1.** HIGH confidence (GarminDB `garmin_json_data.py:314`). **Plan correction:** previous assumption `directPerceivedEffort` was WRONG; correct key is `directWorkoutRpe`. Update INGEST-01 fixture + parser. |
| A3 | Garmin export key for feel is `directWorkoutFeel` | Garmin Export Field Map | **RESOLVED — see § Deep Research §1.** HIGH confidence (GarminDB `garmin_json_data.py:313`). |
| A4 | Garmin export key for VO2 max is `vO2MaxValue` (lives on the per-activity record, NOT in UDSFile) | Garmin Export Field Map | **RESOLVED — see § Deep Research §1.** HIGH confidence (GarminDB `garmin_json_data.py:121,181`; garmin-grafana `garmin_fetch.py:711`). **Plan correction:** SCHEMA-02 originally placed `vo2_max` in `daily_biometrics`. The export source is per-activity (running/cycling separately). Recommend: keep the column in `daily_biometrics`, populate it from the max `vO2MaxValue` across all activities that share a `calendarDate`, OR move it to `activities`. See §1 for the recommended pattern. |
| A5 | Lifesum sync to Google Fit takes ~30 min (general Health Connect propagation) | Lifesum Timing | **STILL UNRESOLVED — see § Deep Research §4.** Lifesum docs do not publish a sync interval. Empirical anchor needed via operator. Plan should keep "~30 min" as a soft latency target in success criterion 2; if observed delay is much larger, narrow it post-launch. |
| A6 | Garmin `get_training_status` payload has nested `mostRecentTrainingStatus.latestTrainingStatusData[<deviceId>]` with keys `trainingStatus`, `weeklyTrainingLoad`, `fitnessTrend`, `acuteTrainingLoadDTO.{acwrPercent, dailyTrainingLoadAcute, dailyTrainingLoadChronic, dailyAcuteChronicWorkloadRatio}` | Garmin Live Reads | **RESOLVED — see § Deep Research §2.** HIGH confidence (garmin-grafana `garmin_fetch.py:1308-1339`). GARMIN-01 spec should target these exact field paths. **Bonus:** Garmin's own `dailyAcuteChronicWorkloadRatio` is already computed on Garmin's side — if present, prefer it over our `compute_acwr` when source is Garmin live. |
| A7 | Chronic baseline "insufficient" = < 14 days with data in the 28-day window | ACWR Computation | **RESOLVED — see § Deep Research §5.** MEDIUM-HIGH (Catapult PlayerTek recommends 21 days as the threshold for a "full" calculation). **Plan correction:** raise the threshold from 14 → 21 days for GARMIN-03 / `compute_acwr` `insufficient_baseline` branch. Below 21 days, return `ratio=None` with reason `"baseline_too_short"`. |
| A8 | Google Fit nutrition rate limits are generous (43 ticks/day × 2 calls = ~86/day) | Google Fit Integration | **RESOLVED — see § Deep Research §3.** HIGH confidence: Google Fit REST quota is **86,400 requests/day per project** and **5 req/s per user** (openmhealth/shimmer + Google API Console). Klaus's load (~86/day, 1 user) is **0.1% of the project quota**. No risk. |
| A9 | Existing `garminconnect` library in `requirements.txt` is `garminconnect>=0.2` `[VERIFIED: requirements.txt:34]`. Latest on PyPI is 0.3.3 (Apr 2026). All four methods `get_training_status`, `get_training_readiness`, `get_max_metrics`, `get_activities_by_date` exist in master `garminconnect/__init__.py` at lines 1855, 1687, 1300, 2253 respectively | Garmin Live Reads | **RESOLVED — see § Deep Research §6.** Recommendation: bump `requirements.txt` from `garminconnect>=0.2` → `garminconnect>=0.3.3` to guarantee these methods exist (the `0.1.x` series predates `get_training_status`). Add a Wave-0 task: `pip install -U garminconnect && pip show garminconnect`. |
| A10 | All 5 new tools fit within `MAX_TOOL_ITERATIONS = 8` brain budget `[VERIFIED: core/main.py:43]` | Tool Registration | A complex training query may use `fetch_training_status` + `fetch_recent_activities` + `database_tool` queries — 3 tool calls. Plenty of budget. |
| A11 | Lifesum is configured to write nutrition to Health Connect / Google Fit on Amit's Android phone | Google Fit Integration | **NARROWED — see § Deep Research §4.** Lifesum's Help Center confirms the path exists ("Nutrition (tracked food)" can be exported to Health Connect), but the operator must explicitly enable it in Lifesum → Progress → Profile → Settings → Automatic Tracking. Must be verified by operator before Wave 2 — operator step remains. |

**If this table is empty:** N/A — Phase 19 has multiple assumptions that
need verification, mostly Garmin field names.

---

## Open Questions

1. ~~**What is the actual key name for Garmin's training load in `*summaries.json`?**~~
   - **RESOLVED — see § Deep Research §1.** Field is `activityTrainingLoad`,
     verified in two independent open-source parsers. The Wave-0 key-dump probe
     is no longer required to *unblock* INGEST-01 — but is still recommended
     as a 5-minute sanity check before backfilling 3 years of data.

2. ~~**Does Lifesum write `food_item` to Fit, or only macros?**~~
   - **STILL UNRESOLVED — see § Deep Research §4.** Lifesum docs do not
     disclose whether food names cross the Health Connect boundary. **Plan
     remains correct as-is:** Google Fit tool extracts `food_item` when
     present, treats as `None` when absent. No code change required either
     way — the brain prompt should describe meals via macros, mentioning
     food names only when populated.

3. **Should `UserProfileStore.update` accept arbitrary keys or validate against the scaffold schema?**
   - **NARROWED — see § Deep Research §9.** Precedent is on the side of
     accept-all: `JournalStore` and `SelfStateStore` in
     `memory/firestore_db.py` both accept arbitrary dict shapes (no
     pre-write validation), and `SelfStateStore.update` uses Firestore
     `set(..., merge=True)` — exactly the pattern PROFILE-02 should adopt.
     **Recommendation unchanged:** accept all keys in v0.

4. ~~**Where does `meal_audit.md` get inlined or referenced from?**~~
   - **RESOLVED — see § Deep Research §8.** Both `core/autonomous.py` and
     `core/morning_briefing.py` already use a `_load_prompt("prompts/<name>.md")`
     helper (autonomous.py:512, 548, 769; morning_briefing.py:239). NUTR-08
     plan: add `_load_prompt("prompts/meal_audit.md")` calls at those same
     sites and append the returned string to the existing system prompt
     before passing to the LLM.

5. **Should `compute_acwr_from_db` cache its result for the duration of a tick?**
   - What we know: ACWR is a read-only query over 28 days of `activities`.
   - What's unclear: cost of re-querying per source.
   - Recommendation: don't cache in Phase 19 — Neon is fast (< 100ms for this
     query), and caching adds complexity. Revisit if the autonomous-tick
     latency budget tightens.

6. **(NEW — surfaced by Deep Research §7) Should Phase 19 use EWMA-ACWR or rolling-window ACWR?**
   - What we know: a 2017 paper by Williams et al. (cited 200+ times) and
     several 2025 follow-ups show EWMA-ACWR is more sensitive to injury
     risk than rolling-average ACWR.
   - What's unclear: whether the additional complexity is worth shipping
     in v0.
   - Recommendation: **stay with rolling-window in Phase 19** — it's the
     industry default (Catapult, Garmin, TrainingPeaks), the Athlytics R
     package exposes both, and the rolling version is dramatically easier
     to explain to the user. Flag EWMA-ACWR as a candidate Phase 20
     refinement once Klaus has enough activity history (~90 days) to make
     the comparison meaningful.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Neon Postgres (`PG_CONNECTION_STRING`) | INGEST-* / GARMIN-05 / ACWR | ✓ | (already wired, commit `2c8be7a`) | — |
| Firestore (`klaus-firestore`) | PROFILE-* / NUTR-02 | ✓ | (already wired) | — |
| Google OAuth (`GOOGLE_TOKEN_SECRET_NAME`) | NUTR-01 | ✓ but needs new scope | — | None — must re-consent |
| `garminconnect` Python lib | GARMIN-01..02 | ✓ | (verify `pip show`) | — |
| Garmin Connect account export | INGEST-03 (one-time) | operator action required | — | Postpone backfill; ship Phase 19 with empty `activities` table; ACWR queries return `ratio=None` until backfill done |
| Lifesum → Google Fit sync configured | NUTR-04 | operator action required | — | None — Phase 19 ships, but NUTR-04 evidence requires it |

**Missing dependencies with no fallback:**
- Google OAuth token re-consent for `fitness.nutrition.read` scope — operator step.
- Lifesum → Google Fit configuration on operator's Android — operator step.

**Missing dependencies with fallback:**
- Garmin 3-year export — can be deferred; ACWR returns `None` gracefully.

---

## Validation Architecture

> nyquist_validation enabled (no `.planning/config.json` override). Include
> this section in VALIDATION.md derivation.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` `[VERIFIED: tests/ directory contains pytest tests]` |
| Config file | (none — pytest auto-discovers from `tests/`) |
| Quick run command | `pytest tests/test_user_profile_store.py tests/test_meal_store.py tests/test_google_fit_tool.py tests/test_compute_acwr.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCHEMA-01 | `activities` has 3 new columns | unit (in-mem sqlite or psycopg2 mock) | `pytest tests/test_ingest_schema.py::test_activities_has_phase19_columns -x` | ❌ Wave 0 |
| SCHEMA-02 | `daily_biometrics` has 4 new columns | unit | `pytest tests/test_ingest_schema.py::test_daily_biometrics_has_phase19_columns -x` | ❌ Wave 0 |
| SCHEMA-03 | DDL re-run is idempotent | integration (psycopg2 mock counting executes) | `pytest tests/test_ingest_schema.py::test_setup_schema_idempotent -x` | ❌ Wave 0 |
| INGEST-01 | parser extracts trainingLoad/perceivedExertion/feel NULL-safe | unit (fixture JSON) | `pytest tests/test_ingest_garmin.py::test_activity_phase19_fields -x` | ❌ Wave 0 |
| INGEST-02 | parser extracts vo2MaxValue from UDS | unit | `pytest tests/test_ingest_garmin.py::test_uds_vo2_max -x` | ❌ Wave 0 |
| INGEST-03 | end-to-end backfill row counts + NULL rates | manual operator (with `database_tool` queries) | (manual) | manual-only |
| PROFILE-01 | `load()` returns `{}` on Firestore exception | unit (Firestore client mock) | `pytest tests/test_user_profile_store.py::test_load_returns_empty_on_error -x` | ❌ Wave 1 |
| PROFILE-02 | `update()` merges + stamps `updated_at` | unit | `pytest tests/test_user_profile_store.py::test_update_merges_and_stamps -x` | ❌ Wave 1 |
| PROFILE-03 | `bootstrap_if_empty` writes scaffold when absent, no-op when present | unit | `pytest tests/test_user_profile_store.py::test_bootstrap_creates_when_missing -x` AND `test_bootstrap_skips_when_present` | ❌ Wave 1 |
| PROFILE-04 | both tools registered + brain-direct | unit (introspect schemas + frozenset) | `pytest tests/test_tools.py::test_phase19_profile_tools_registered -x` | ❌ Wave 1 |
| GARMIN-01 | `fetch_training_status` returns dict with 3 keys | unit (`garminconnect` mock) | `pytest tests/test_garmin_extensions.py::test_training_status_shape -x` | ❌ Wave 1 |
| GARMIN-02 | `fetch_recent_activities(days=7)` returns normalized list | unit | `pytest tests/test_garmin_extensions.py::test_recent_activities_shape -x` | ❌ Wave 1 |
| GARMIN-03 | `compute_acwr` ratio + None on insufficient | unit (no I/O) | `pytest tests/test_compute_acwr.py::test_normal_ratio` AND `test_insufficient_baseline_returns_none` | ❌ Wave 1 |
| GARMIN-04 | both fetch tools in WORKER_TOOL_SCHEMAS, not in SMART_AGENT_DIRECT_TOOLS | unit | `pytest tests/test_tools.py::test_phase19_fetch_tools_worker_delegated -x` | ❌ Wave 1 |
| GARMIN-05 | morning briefing writes biometrics to Postgres (best-effort) | unit (psycopg2 mock + Postgres-outage test) | `pytest tests/test_morning_briefing.py::test_writes_biometrics_to_postgres` AND `test_postgres_outage_does_not_block_briefing` | partial Wave 3 |
| NUTR-01 | Google Fit tool normalizes a nutrition data point | unit (Fit HTTP response fixture) | `pytest tests/test_google_fit_tool.py::test_normalize_point -x` | ❌ Wave 2 |
| NUTR-02 | MealStore idempotent on source_id | unit | `pytest tests/test_meal_store.py::test_upsert_idempotent_on_source_id -x` | ❌ Wave 2 |
| NUTR-03 | `fetch_recent_meals` tool registered worker-delegated | unit | `pytest tests/test_tools.py::test_fetch_recent_meals_worker_delegated -x` | ❌ Wave 2 |
| NUTR-04 | autonomous gather extends with meals + training_status + acwr | unit (extend test_autonomous.py) | `pytest tests/test_autonomous.py::test_gather_includes_phase19_keys -x` | partial Wave 3 |
| NUTR-05 | morning briefing aggregates yesterday's meals | unit | `pytest tests/test_morning_briefing.py::test_aggregates_yesterday_meals -x` | partial Wave 3 |
| NUTR-06 | autonomous_triage.md mentions meal triggers | unit (string grep) | `pytest tests/test_prompts.py::test_triage_mentions_meal_triggers -x` | ❌ Wave 4 |
| NUTR-07 | recap silently omitted on no-meals day | unit | `pytest tests/test_morning_briefing.py::test_no_nutrition_key_when_empty` AND `test_prompt_omits_section_when_no_nutrition` | ❌ Wave 4 |
| NUTR-08 | `prompts/meal_audit.md` exists and is referenced | unit (file existence + grep) | `pytest tests/test_prompts.py::test_meal_audit_exists` AND `test_meal_audit_referenced` | ❌ Wave 4 |
| PROMPT-01 | `{training_profile}` substitution works | unit | `pytest tests/test_main_render_smart_system.py::test_training_profile_substituted -x` | ❌ Wave 4 |
| PROMPT-02 | smart_agent.md has training section | unit | `pytest tests/test_prompts.py::test_smart_agent_has_training_section -x` | ❌ Wave 4 |
| PROMPT-03 | SELF.md lists 5 new tools | unit (grep) | `pytest tests/test_docs.py::test_self_md_lists_phase19_tools -x` | partial Wave 4 |

### Sampling Rate

- **Per task commit:** quick run command (above) — covers the file being edited.
- **Per wave merge:** `pytest tests/ -x` — full suite (~465 tests today + ~30 Phase 19).
- **Phase gate:** Full suite green before `/gsd-verify-work`. Manual operator
  step for INGEST-03 (3-year backfill).

### Wave 0 Gaps

- [ ] `tests/test_ingest_schema.py` — covers SCHEMA-01..03
- [ ] `tests/test_ingest_garmin.py` — covers INGEST-01..02
- [ ] Garmin export key probe script (one-shot, not a test) — locks A1–A4

### Wave 1 Gaps

- [ ] `tests/test_user_profile_store.py` — covers PROFILE-01..03
- [ ] `tests/test_garmin_extensions.py` — covers GARMIN-01..02
- [ ] `tests/test_compute_acwr.py` — covers GARMIN-03
- [ ] Extend `tests/test_tools.py` — covers PROFILE-04, GARMIN-04, NUTR-03 (registration tests)

### Wave 2 Gaps

- [ ] `tests/test_google_fit_tool.py` — covers NUTR-01
- [ ] `tests/test_meal_store.py` — covers NUTR-02
- [ ] OAuth re-consent — operator manual step (not a test)

### Wave 3 Gaps

- [ ] Extend `tests/test_autonomous.py` — covers NUTR-04 + eval-fixture schema update + 5-fixture backfill
- [ ] Extend `tests/test_morning_briefing.py` — covers NUTR-05, NUTR-07, GARMIN-05

### Wave 4 Gaps

- [ ] Extend `tests/test_prompts.py` — covers NUTR-06, NUTR-08, PROMPT-02
- [ ] Extend `tests/test_main_render_smart_system.py` — covers PROMPT-01
- [ ] Extend `tests/test_docs.py` — covers PROMPT-03
- [ ] Run `python core/self_manifest.py` and commit `docs/SELF.md`

### Pure-Unit-Testable vs. Integration-Required Boundaries

**Pure unit (no I/O):**
- `compute_acwr` (GARMIN-03) — list-in, dict-out.
- Meal aggregation (`MealStore.get_day_aggregate` math) — once given a meal list.
- All prompt-content tests (string grep / file existence).
- Tool-registration tests (introspect schema lists).
- Fit nutrition payload normalization (NUTR-01) — JSON fixture in, normalized dict out.

**Integration-required (real or stubbed dependency):**
- `UserProfileStore` / `MealStore` Firestore interactions — use the same
  `mock.patch("google.cloud.firestore")` pattern as existing
  `tests/test_firestore_db.py`.
- `fetch_training_status` / `fetch_recent_activities` — patch `garminconnect.Garmin`.
- Backfill INGEST-03 — manual operator step with real export zip and real Neon.
- Morning briefing Postgres writeback (GARMIN-05) — patch `psycopg2.connect`.
- Google Fit `fetch_recent_meals` — patch `googleapiclient.discovery.build`.

**Manual-only:**
- INGEST-03 row counts + NULL rates after a real 3-year backfill.
- End-to-end Lifesum → Fit → MealStore → Telegram outreach loop (success
  criterion 2).
- OAuth scope re-consent (one-time).

---

## Deep Research — Open Questions Resolution

> Appended 2026-05-26 in response to a follow-up research request. Resolves
> 7 of 9 priority items; lifts Assumptions Log A1–A4, A6–A9 from LOW/MEDIUM
> to HIGH confidence. The remaining unresolved items (A5/A11 — Lifesum sync
> timing) cannot be resolved without operator-side empirical observation.

### §1 — Garmin Export Field Names (A1, A2, A3, A4)

**Original assumptions:**
- A1: `activityTrainingLoad`
- A2: `directPerceivedEffort` (or `perceivedExertion`)
- A3: `directWorkoutFeel` (or `workoutFeel`)
- A4: `vO2MaxValue` lives in `*UDSFile.json`

**What I found.** I cloned two independent, mature open-source Garmin
parsers and grep'd them. Both agree on the exact field names; one
contradicts a critical assumption.

**Source 1 — GarminDB by Tom Goetz** (>2k GitHub stars, the de-facto
reference parser for Garmin Connect export zips):

| Phase 19 column | GarminDB field | File location |
|-----------------|----------------|---------------|
| `training_load` | `activityTrainingLoad` | `garmindb/garmin_json_data.py:321`, inside `summary_dto` block |
| `rpe` (perceived effort) | **`directWorkoutRpe`** | `garmindb/garmin_json_data.py:314` |
| `workout_feel` | `directWorkoutFeel` | `garmindb/garmin_json_data.py:313` |
| `vo2_max` (per activity) | `vO2MaxValue` | `garmindb/garmin_json_data.py:121, 181` |

Source URL: https://github.com/tcgoetz/GarminDB/blob/master/garmindb/garmin_json_data.py

**Source 2 — garmin-grafana by Arpan Ghosh** (active 2025/2026 fork
maintained for Grafana visualization, ingests via python-garminconnect
live API but normalizes to the same Garmin field names):

| Phase 19 column | garmin-grafana field | File location |
|-----------------|---------------------|---------------|
| `training_load` | `activityTrainingLoad` | `src/garmin_grafana/garmin_fetch.py:726` |
| `vo2_max` (per activity) | `vO2MaxValue` | `src/garmin_grafana/garmin_fetch.py:711` |

Source URL: https://github.com/arpanghosh8453/garmin-grafana/blob/main/src/garmin_grafana/garmin_fetch.py

**Resolution:**

- **A1: VERIFIED.** Field is `activityTrainingLoad`. HIGH confidence.
- **A2: REVISED + VERIFIED.** Field is `directWorkoutRpe`, **not**
  `directPerceivedEffort`. The phase plan's assumed key was wrong. HIGH
  confidence. **Action:** INGEST-01 parser must reference
  `directWorkoutRpe`, and the test fixture in `tests/test_ingest_garmin.py`
  must use that key.
- **A3: VERIFIED.** Field is `directWorkoutFeel`. HIGH confidence.
- **A4: VERIFIED + REVISED.** Field is `vO2MaxValue` (camelCase with
  capital `O`), but it lives **on the per-activity record** (in either the
  top-level `activity_*.json` or the `summary_dto` of `activity_details_*.json`),
  **not** in `*UDSFile.json` as Phase 19 originally assumed. UDSFile contains
  daily summaries (RHR, body battery, training readiness) but not VO2 max.
  HIGH confidence.

  **Plan correction for SCHEMA-02:** The column placement is a design call:

  | Option | Behavior |
  |--------|----------|
  | **Recommended** — keep `vo2_max` in `daily_biometrics` | Populate by taking the **maximum** `vO2MaxValue` across all activities on each `calendarDate`. Matches Garmin Connect Web UI, which shows one VO2 max per day. INGEST-02 reads from `activity_*.json` and writes to `daily_biometrics.vo2_max`. |
  | Alternative — move to `activities` | More normalized, but requires ACWR / Phase 19 queries to JOIN `activities` for VO2 max, costing one extra query in every dashboard view. |

  Recommend option 1.

**Bonus finding — additional fields available for future phases:**
The export records `aerobicTrainingEffect` (0.0–5.0), `anaerobicTrainingEffect`
(0.0–5.0), `moderateIntensityMinutes`, `vigorousIntensityMinutes`, and
`hrTimeInZone_1..5`. None are in scope for Phase 19, but they're cheap to
add to `activities` while the schema migration is open. Defer to v3.1 if
Project Shifu wants intensity-zone analysis later.

**Wave-0 task downgrade:** The `keys()` probe task is no longer
*blocking* (we know the keys). Keep it as a 5-minute sanity check before
running the 3-year backfill — Garmin has changed field names before, and
the probe is cheap insurance.

---

### §2 — Garmin Live API: `get_training_status` Payload (A6, A9)

**Original assumption:** `get_training_status` returns a dict with
`vo2_max`, `training_status`, `load_focus` fields under "some nested path."

**What I found.** garmin-grafana extracts training status via the same
python-garminconnect API call Klaus uses. The response shape is nested
under `mostRecentTrainingStatus.latestTrainingStatusData[<device_id>]`.

Source: `src/garmin_grafana/garmin_fetch.py:1308-1339` (verbatim quote):

```python
ts_list_all = garmin_obj.get_training_status(date_str)
ts_training_data_all = (ts_list_all.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData", {})

if ts_training_data_all:
    for device_id, ts_dict in ts_training_data_all.items():
        data_fields = {
            "trainingStatus":                  ts_dict.get("trainingStatus"),
            "trainingStatusFeedbackPhrase":    ts_dict.get("trainingStatusFeedbackPhrase"),
            "weeklyTrainingLoad":              ts_dict.get("weeklyTrainingLoad"),
            "fitnessTrend":                    ts_dict.get("fitnessTrend"),
            "acwrPercent":                     (ts_dict.get("acuteTrainingLoadDTO") or {}).get("acwrPercent"),
            "dailyTrainingLoadAcute":          (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyTrainingLoadAcute"),
            "dailyTrainingLoadChronic":        (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyTrainingLoadChronic"),
            "maxTrainingLoadChronic":          (ts_dict.get("acuteTrainingLoadDTO") or {}).get("maxTrainingLoadChronic"),
            "minTrainingLoadChronic":          (ts_dict.get("acuteTrainingLoadDTO") or {}).get("minTrainingLoadChronic"),
            "dailyAcuteChronicWorkloadRatio":  (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyAcuteChronicWorkloadRatio"),
        }
```

**Resolution.** A6: VERIFIED at HIGH confidence. GARMIN-01 spec:

```python
def fetch_training_status(date_str: str) -> dict | None:
    raw = api.get_training_status(date_str)
    latest = (raw.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData", {})
    if not latest:
        return None
    # Multi-device users have multiple entries — take the most recent timestamp.
    ts_dict = max(latest.values(), key=lambda d: d.get("timestamp", 0))
    atl = ts_dict.get("acuteTrainingLoadDTO") or {}
    return {
        "training_status":         ts_dict.get("trainingStatus"),
        "status_phrase":           ts_dict.get("trainingStatusFeedbackPhrase"),
        "weekly_training_load":    ts_dict.get("weeklyTrainingLoad"),
        "fitness_trend":           ts_dict.get("fitnessTrend"),
        "acwr_ratio":              atl.get("dailyAcuteChronicWorkloadRatio"),
        "daily_load_acute":        atl.get("dailyTrainingLoadAcute"),
        "daily_load_chronic":      atl.get("dailyTrainingLoadChronic"),
    }
```

**Bonus finding (high-impact).** Garmin's API **already computes ACWR**
(`dailyAcuteChronicWorkloadRatio`). Phase 19's GARMIN-03 (`compute_acwr`)
should prefer this Garmin-computed value when source is the live API, and
fall back to our own `compute_acwr_from_db` only when reading from
Postgres history. Suggested precedence order in
`gather_situation`/morning_briefing:

1. If `fetch_training_status` returns a ratio → use it (Garmin's own).
2. Else if `compute_acwr_from_db` returns a ratio → use it (our computation).
3. Else → emit `{"ratio": None, "reason": "..."}`.

This change keeps `compute_acwr` in the codebase (needed for the 3-year
historical backfill ACWR queries against Postgres) but defers to Garmin's
canonical number for "today."

**`get_training_readiness` shape (Source: garmin-grafana
`garmin_fetch.py:1342-1370`):** Returns a `list` of dicts with keys
`level`, `score`, `sleepScore`, `sleepScoreFactorPercent`, `recoveryTime`,
`recoveryTimeFactorPercent`, `acwrFactorPercent`, `acuteLoad`,
`stressHistoryFactorPercent`, `hrvFactorPercent`, `timestamp`. The
top-level is a list, not a dict — caller must handle list[0] or iterate.

**`get_max_metrics` shape (Source: garmin-grafana `garmin_fetch.py:1447-1467`):**
Returns a list. `max_metrics[0]` has nested keys `"generic"` (running VO2)
and `"cycling"`, each containing `"vo2MaxPreciseValue"`. The "precise" suffix
distinguishes the float value from the integer displayed in the UI.

**A9 verified.** Klaus's `requirements.txt:34` pins `garminconnect>=0.2`.
Latest PyPI version is **0.3.3** (released 2026-04-22, per
https://pypi.org/project/garminconnect/). All four methods exist in the
0.3.x source (confirmed by reading
`python-garminconnect-master/garminconnect/__init__.py:1300, 1687, 1855,
2253`). **Recommendation:** bump pin to `garminconnect>=0.3.3` to
guarantee the methods exist; add a Wave-0 task:

```bash
pip install -U "garminconnect>=0.3.3"
pip show garminconnect  # confirm
```

---

### §3 — Google Fit Nutrition Rate Limits (A8)

**Original assumption:** "Generous enough for 43 ticks/day × 2 calls."

**What I found.**

| Quota Tier | Limit | Source |
|-----------|-------|--------|
| Project-level | **86,400 requests/day** | openmhealth/shimmer Google-Fit.md (cites Google Fit API console default) |
| Per-user-per-second | **5 req/s** | Same source |

Source: https://github.com/openmhealth/shimmer/blob/master/shim-server/src/main/java/org/openmhealth/shim/googlefit/Google-Fit.md

Cross-reference: Google API Console "Quotas" page for the Fit API
exposes the same numbers in the developer console under Klaus's project
(operator can verify in-console post-deploy).

**Cron schedule:** `*/20 7-21` (CLAUDE.md §5) = 3 ticks/hour × 15 hours =
**45 ticks/day max**. With NUTR-04 making 2 Fit calls per tick (one for
the last 24h aggregate, one for an optional finer-grain window), that's
**90 calls/day**.

90 / 86,400 = **0.1% of project quota**. The per-user limit (5 req/s)
is not even close to threatened — Klaus's calls are spread across the day,
not bursted.

**Resolution.** A8: VERIFIED at HIGH confidence. Cache-for-1-tick is
**not** recommended on quota grounds. (May still be worth it for
latency, but quota is a non-issue.)

**Note — deprecation horizon.** The Google Fit REST API was announced
deprecated effective **June 30, 2025**, with Health Connect as the
successor. As of 2026-05-26 the Fit API still works (no shutdown date
announced), but new projects can't sign up. Klaus's project was
provisioned pre-deprecation, so the API is available. Add to Phase 20+
risk register: monitor Google's announcements; long-term plan should
migrate to a Health Connect-aware path (the user is on Android and
already uses Health Connect as the Lifesum→Fit conduit, so this is
likely a glue-code change, not an architectural overhaul). Reference:
https://developers.google.com/fit/improvements

---

### §4 — Lifesum → Google Fit Timing (A5) + `food_item` (Open Q #2)

**Original assumptions:**
- A5: "~30 min" general Health Connect propagation
- Open Q #2: whether `food_item` (food name) is populated

**What I found.**

1. **Lifesum's own docs** (https://help.lifesum.com/en/article/how-to-connect-to-and-sync-with-health-connect-android-1ws4g93/)
   confirm the Lifesum→Health Connect path for nutrition, but **publish
   no SLA**: there is no documented sync interval, no statement of
   "real-time vs. batched," and no statement on whether food names
   cross the boundary.

2. **Constraint surfaced** (https://help.lifesum.com/...
   referenced in WebSearch results): food logged via Lifesum's
   "Multimodal Tracking" (camera-based food recognition) is **explicitly
   not** sent to Health Connect. Standard logging (search-and-add) does
   sync.

3. **Health Connect → Google Fit** is itself a separate sync hop in
   the chain. Health Connect's own documentation does not pin an
   interval; community reports range from "near-real-time" to "next
   app-open."

**Resolution.**
- **A5:** STILL UNRESOLVED. Lifesum publishes no sync interval. The
  "~30 min" anchor is unsubstantiated by an authoritative source. Plan
  recommendation: **keep it as a soft latency target in success
  criterion 2 for v3.0 launch, then measure empirically** (operator logs
  a meal at known T₀, Klaus's NUTR-04 gather logs the time the meal
  first surfaces — `T_observed − T₀` is the de-facto SLO). Tighten or
  loosen the success criterion based on a week of observation.
- **Open Q #2 (food names):** STILL UNRESOLVED, but the plan is correct
  as-is: the Google Fit nutrition data type *supports* `food_item` as
  a string field. Whether Lifesum populates it is invisible until the
  operator actually logs a meal and observes. **Plan code path remains
  unchanged**: extract `food_item` when present, treat as `None`
  otherwise.
- **Operator-facing instruction (NEW):** add to Phase 19 deploy notes:
  "First meal after deploy — please log a known meal, note the
  timestamp, and on the next autonomous tick observe what Klaus surfaces.
  This gives us our first SLO data point on Lifesum→Fit latency and on
  whether food names propagate."

---

### §5 — ACWR Insufficient-Baseline Threshold (A7)

**Original assumption:** `chronic_baseline_days < 14` → return `None`.

**What I found.**

| Source | Threshold | Reasoning |
|--------|-----------|-----------|
| **Catapult PlayerTek Plus** (commercial tool used by elite teams) | **21 days** for full calculation, dotted line if less | https://playertekplus.catapultsports.com/hc/en-us/articles/7443928371471 |
| **Garmin's own UI** | "1-2 weeks recorded activities" required for training status to appear | https://support.garmin.com/.../?faq=VxKazDQ2mkAmDoQbJriEBA |
| **Athlytics R package** (open-source sports-science library) | Returns `NA` for "roughly the first 333 day(s)" only if the EWMA half-life is set to a very long window; with default 28-day chronic, ramps in over the first ~21 days | https://docs.ropensci.org/Athlytics/reference/calculate_acwr.html |

**Resolution.** A7: REVISED. Raise threshold from **14 → 21 days**.
This aligns with Catapult (the de-facto commercial standard) and
matches Garmin's own "1-2 weeks" minimum. 14 days was a researcher's
guess; 21 days is citation-backed.

**Plan correction for GARMIN-03 (`compute_acwr`):** when
`len(chronic_days_with_data) < 21`, return:

```python
{"ratio": None, "reason": "baseline_too_short", "days_with_data": N, "min_days_required": 21}
```

The `reason` field is new — it lets the brain decide how to phrase its
output ("Not enough data yet — we'll have ACWR available after about a
month of activity history").

---

### §6 — `garminconnect` Library Version

Covered in §2 above. Summary:
- **Pinned:** `garminconnect>=0.2` (`requirements.txt:34`)
- **Latest:** 0.3.3 (PyPI, 2026-04-22)
- **All four required methods exist** in 0.3.x master:
  `get_training_status` (line 1855), `get_training_readiness` (1687),
  `get_max_metrics` (1300), `get_activities_by_date` (2253).
- **Recommendation:** bump pin to `garminconnect>=0.3.3`. Wave-0 task:
  `pip install -U garminconnect && pip show garminconnect`.

---

### §7 — Rolling-Average vs. EWMA ACWR

**Question:** is EWMA-ACWR (exponentially weighted moving average) the
new state of the art? Should Phase 19 ship it?

**What I found.**

| Method | Strengths | Weaknesses | Citations |
|--------|-----------|-----------|-----------|
| **Rolling-window (Banister, 7-day acute / 28-day chronic)** | Industry default; what Catapult, Garmin, TrainingPeaks all expose; simple to explain | Treats each day in the window as equal weight — does not model fitness decay | https://www.scienceforsport.com/acutechronic-workload-ratio/ |
| **EWMA-ACWR (Williams et al. 2017)** | More sensitive to injury risk in research studies (relative risk 13.43 vs. 5.87 in one cited study); accounts for fitness decay | More complex; less intuitive; requires choosing decay constants; not exposed by Garmin/TrainingPeaks UIs | https://link.springer.com/article/10.1186/s13102-025-01332-x (2025 meta-analysis) |

**Resolution.** Phase 19 should **stay with rolling-window**. Reasons:
1. Matches what Garmin's own `dailyAcuteChronicWorkloadRatio` exposes (so
   Klaus's number agrees with what Amit sees in the Garmin app).
2. Industry standard — easier to communicate ("acute = last 7 days,
   chronic = last 28 days").
3. The Athlytics package exposes both — switching is a future drop-in if
   we want it.

**Add to roadmap (Phase 20+):** evaluate EWMA-ACWR once Klaus has ~90
days of activity history. Run both side-by-side, compare against
self-reported injury / soreness events from the user. If EWMA-ACWR's
sensitivity advantage materializes for Amit specifically, switch.

This is a **new open question (#6 in the updated list)**, not a Phase
19 scope change.

---

### §8 — `meal_audit.md` Wiring (Open Q #4)

**Question:** How does NUTR-08's standalone prompt get loaded into
`core/autonomous.py` and `core/morning_briefing.py`?

**What I found.**

Both files already use a single `_load_prompt(relative_path)` helper:

| File | Existing call site | Loaded prompt |
|------|--------------------|---------------|
| `core/autonomous.py:512` | `smart_system_template = _load_prompt("prompts/autonomous.md")` | brain compose prompt |
| `core/autonomous.py:548` | `smart_system_template = _load_prompt("prompts/autonomous.md")` | (second entry point) |
| `core/autonomous.py:769` | `triage_system = _load_prompt("prompts/autonomous_triage.md")` | tick-brain triage |
| `core/morning_briefing.py:239-245` | `prompt_path = Path(__file__).parent.parent / "prompts" / "morning_briefing.md"` then `prompt_path.read_text()` | briefing compose |

Note: `morning_briefing.py` does **not** use the `_load_prompt` helper;
it builds the path manually with `Path(__file__).parent.parent / "prompts" / ...`.
NUTR-08's wiring in `morning_briefing.py` should follow the local
convention (Path-based read), and in `autonomous.py` should use
`_load_prompt`.

**Resolution.** Open Q #4: RESOLVED. NUTR-08 plan:

```python
# core/autonomous.py — inside the same scope as smart_system_template
meal_audit = _load_prompt("prompts/meal_audit.md")
smart_system_template = smart_system_template + "

" + meal_audit
```

```python
# core/morning_briefing.py — alongside the existing prompt load at :239
meal_audit_path = Path(__file__).parent.parent / "prompts" / "meal_audit.md"
meal_audit = meal_audit_path.read_text() if meal_audit_path.exists() else ""
prompt_text = base_prompt + ("

" + meal_audit if meal_audit else "")
```

Same load-and-append pattern as `autonomous_triage.md` is loaded by
the autonomous triage stage. NUTR-08 spec: append at the **end** of the
existing system prompt so the brain's existing persona/instruction
ordering is preserved.

---

### §9 — `UserProfileStore` Validation Precedent (Open Q #3)

**Question:** Should `UserProfileStore.update` accept arbitrary keys, or
validate against a fixed schema?

**Precedent in `memory/firestore_db.py`.** Klaus's Firestore stores
follow two patterns:

| Pattern | Examples | Validation behavior |
|---------|----------|--------------------|
| **Accept-any-dict (write-through)** | `SelfStateStore.update`, `JournalStore.write_entry`, `OutreachLogStore.append` | Pass dict straight to Firestore `.set(..., merge=True)` or `.add(...)`. No schema validation. Firestore stores anything. |
| **Validated** | `RosterStore.upsert` (enforces `name`, `phone`, `active`), `AttendanceStore.record` (enforces `practice_id`, `attendee_ids`) | Explicit `if not isinstance(value, expected_type): raise` checks. |

The two validated stores both back **user-facing features with shared
data semantics** (the five-fingers practice attendance list — multiple
writers, strict shape). The accept-any stores all back **internal
agent state** with one writer (Klaus's own brain).

**`UserProfileStore` is internal agent state** — written by the brain
(via `update_user_profile` tool) and read by the brain (via the
`{training_profile}` placeholder in `smart_agent.md`). It matches the
SelfStateStore / JournalStore semantic class.

**Resolution.** Open Q #3: NARROWED with stronger argument. PROFILE-02
should follow the `SelfStateStore.update` precedent:

```python
# memory/firestore_db.py — modeled exactly on SelfStateStore.update
class UserProfileStore:
    def update(self, fields: dict) -> None:
        if not isinstance(fields, dict):
            raise TypeError("UserProfileStore.update requires a dict")
        fields["updated_at"] = firestore.SERVER_TIMESTAMP
        self._client.collection("user_profile").document("amit").set(fields, merge=True)
```

No key-by-key validation. The brain self-disciplines via the
`update_user_profile` tool's JSON-schema, which the brain itself sees
during tool selection. Phase 20 can layer validation in if usage
patterns surface needs.

---

### Updated Confidence Summary

| Item | Before | After |
|------|--------|-------|
| A1 Garmin training_load key | LOW | HIGH |
| A2 Garmin RPE key | LOW | HIGH (REVISED) |
| A3 Garmin feel key | LOW | HIGH |
| A4 Garmin VO2 max key + location | LOW | HIGH (REVISED) |
| A5 Lifesum sync timing | LOW | UNRESOLVED (no auth source) |
| A6 `get_training_status` shape | LOW | HIGH |
| A7 ACWR baseline threshold | LOW | HIGH (REVISED 14→21) |
| A8 Google Fit rate limits | MEDIUM | HIGH |
| A9 `garminconnect` lib version | MEDIUM | HIGH |
| Open Q #1 export key probe blocker | OPEN | RESOLVED |
| Open Q #2 `food_item` populated | OPEN | UNRESOLVED (no auth source) |
| Open Q #3 profile validation policy | OPEN | NARROWED |
| Open Q #4 meal_audit.md wiring | OPEN | RESOLVED |
| Open Q #5 ACWR cache | OPEN | (unchanged — don't cache) |
| Open Q #6 EWMA-ACWR (NEW) | — | OPEN, deferred to Phase 20 |

**Overall Phase 19 confidence: HIGH** (was: MEDIUM-LOW pending Wave-0
probe). The 3-year Garmin backfill can proceed without blocking on
operator-side probing.

---

## Sources

### Primary (HIGH confidence)
- `core/auth_google.py` — `[VERIFIED]` Google OAuth pattern, SCOPES list, token storage backends
- `core/autonomous.py` — `[VERIFIED]` 3-layer pipeline, gather_situation, empty-signals gate
- `core/main.py` — `[VERIFIED]` render_smart_system, placeholder set, MAX_TOOL_ITERATIONS
- `core/morning_briefing.py` — `[VERIFIED]` state machine, _gather_data sources
- `core/tools.py` — `[VERIFIED]` SMART_AGENT_DIRECT_TOOLS, TOOL_SCHEMAS, WORKER_TOOL_SCHEMAS, _HANDLERS
- `core/self_manifest.py` — `[VERIFIED]` SHA computation, schemas → SELF.md
- `memory/firestore_db.py` — `[VERIFIED]` lazy-singleton store pattern across 8 stores; UserProfileStore stub at :391
- `mcp_tools/garmin_tool.py` — `[VERIFIED]` token cache pattern, fetch_garmin_today shape
- `mcp_tools/database_tool.py` — `[VERIFIED]` read-only enforcement, SELECT/WITH allowlist
- `scripts/ingest_garmin_zip.py` — `[VERIFIED]` SCHEMA_DDL, parser pattern, UPSERT shape
- `prompts/smart_agent.md`, `prompts/autonomous_triage.md`, `prompts/morning_briefing.md` — `[VERIFIED]`
- [.planning/ROADMAP.md](.planning/ROADMAP.md), [.planning/REQUIREMENTS.md](.planning/REQUIREMENTS.md), [.planning/STATE.md](.planning/STATE.md) — `[VERIFIED]`
- [Google Fit nutrition data type](https://developers.google.com/fit/datatypes/nutrition) — `[CITED]` exact scope strings, nutrient keys, meal_type enum
- [Google Fit dataset.aggregate](https://developers.google.com/fit/rest/v1/reference/users/dataset/aggregate) — `[CITED]` endpoint + request shape
- [Google OAuth incremental authorization](https://developers.google.com/identity/protocols/oauth2/web-server) — `[CITED]` `include_granted_scopes`, refresh-token-only-on-first-grant
- [python-garminconnect source](https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py) — `[CITED]` method signatures: `get_training_status`, `get_training_readiness`, `get_max_metrics`, `get_activities`, `get_activities_by_date`

### Secondary (MEDIUM confidence)
- [ACWR systematic review (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7047972/) — sweet spot 0.8–1.3, spike ≥ 1.5
- [Science for Sport — ACWR](https://www.scienceforsport.com/acutechronic-workload-ratio/) — 7-day acute / 28-day chronic standard
- [Lifesum Help — Connect Google Fit](https://lifesum.helpshift.com/hc/en/3-lifesum/faq/38-how-do-i-connect-to-google-fit/) — confirms Lifesum→Health Connect→Fit path

### Tertiary (LOW confidence)
- Lifesum-to-Fit sync timing ("~30 min") — `[ASSUMED]` based on general
  Health Connect propagation; not officially documented. Confirmed
  unresolvable via doc search in Deep Research §4 — requires empirical
  operator measurement.
- Whether Lifesum populates the Google Fit `food_item` field (Open Q #2)
  — `[ASSUMED]` unknown. Plan code path is correct either way.

### Added 2026-05-26 (Deep Research round)
- [GarminDB — Tom Goetz](https://github.com/tcgoetz/GarminDB/blob/master/garmindb/garmin_json_data.py)
  `[VERIFIED]` field names `activityTrainingLoad` (:321), `directWorkoutRpe`
  (:314), `directWorkoutFeel` (:313), `vO2MaxValue` (:121, :181) — A1–A4.
- [garmin-grafana — Arpan Ghosh](https://github.com/arpanghosh8453/garmin-grafana/blob/main/src/garmin_grafana/garmin_fetch.py)
  `[VERIFIED]` `get_training_status` payload shape (:1308-1339),
  `get_training_readiness` (:1342-1370), `get_max_metrics` (:1447-1467),
  activity-level `activityTrainingLoad` (:726), `vO2MaxValue` (:711) — A6.
- [python-garminconnect master `__init__.py`](https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py)
  `[VERIFIED]` method line numbers: `get_max_metrics` (:1300),
  `get_training_readiness` (:1687), `get_training_status` (:1855),
  `get_activities_by_date` (:2253) — A9.
- [garminconnect PyPI](https://pypi.org/project/garminconnect/) `[VERIFIED]`
  latest version 0.3.3 (released 2026-04-22) — A9 pin bump recommendation.
- [openmhealth/shimmer Google-Fit.md](https://github.com/openmhealth/shimmer/blob/master/shim-server/src/main/java/org/openmhealth/shim/googlefit/Google-Fit.md)
  `[CITED]` Google Fit REST quota: 86,400 req/day project, 5 req/s/user — A8.
- [Catapult PlayerTek ACWR Season Chart](https://playertekplus.catapultsports.com/hc/en-us/articles/7443928371471-Acute-Chronic-Workload-Ratio-Season-Chart)
  `[CITED]` 21-day minimum for full ACWR calculation — A7.
- [Athlytics `calculate_acwr` documentation](https://docs.ropensci.org/Athlytics/reference/calculate_acwr.html)
  `[CITED]` baseline ramp-in and EWMA alternative — A7, Open Q #6.
- [Williams et al. 2017 — EWMA-ACWR vs. rolling average](https://link.springer.com/article/10.1186/s13102-025-01332-x)
  (2025 meta-analysis) `[CITED]` — Open Q #6 (deferred).
- [Lifesum Help — Health Connect Android](https://help.lifesum.com/en/article/how-to-connect-to-and-sync-with-health-connect-android-1ws4g93/)
  `[CITED]` confirms nutrition path exists; no sync-interval SLA — A5, A11.
- [Garmin Customer Support — Training Status FAQ](https://support.garmin.com/en-US/?faq=VxKazDQ2mkAmDoQbJriEBA)
  `[CITED]` Garmin's own 1-2 week minimum for Training Status — A7.
- [Google Fit REST API deprecation announcement](https://developers.google.com/fit/improvements)
  `[CITED]` REST API deprecated 2025-06-30; Health Connect successor — A8 risk register.
- `requirements.txt:34` `[VERIFIED]` current pin `garminconnect>=0.2` — A9.
- `core/autonomous.py:512, 548, 769` and `core/morning_briefing.py:239` `[VERIFIED]`
  existing prompt-loading sites for NUTR-08 wiring — Open Q #4.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use; no new dependencies.
- Architecture: HIGH — patterns lifted verbatim from existing stores / handlers / gather extensions.
- Pitfalls: HIGH — OAuth scope handling and idempotency are well-understood; Garmin field names are the only meaningful uncertainty, locked behind a Wave-0 probe task.
- Google Fit shape: HIGH — verified against official Google docs.
- Garmin export shape: LOW — A1–A4 require physical inspection of the export.

**Research date:** 2026-05-25
**Valid until:** 2026-06-25 (30 days; longer because the Klaus codebase has
shipped stably for 7 days post-v2.0 and the external surfaces — Google Fit,
garminconnect lib — are slow-moving).
