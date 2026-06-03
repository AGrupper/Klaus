# Stack Research

**Domain:** Expert coaching knowledge layer + living training plan + block/benchmark tracking for a personal AI agent
**Researched:** 2026-06-03
**Confidence:** HIGH — all decisions are pure extensions of existing, validated infrastructure; no genuinely new technology domains introduced

---

## Executive Context

v4.0 adds three capabilities to an already-running system:

1. **Curated coaching knowledge** — expert hybrid-athlete content the brain reasons over
2. **Living plan in UserProfileStore** — Amit's blueprint as a structured-but-flexible Firestore doc
3. **Training block + benchmark tracking** — block state and per-facet improvement records

The guiding constraint: **every decision must reuse existing infra unless a genuinely new capability is needed.** The existing stack (Firestore, Pinecone 768-dim cosine, Postgres activities/biometrics, Gemini brain, TrainingLogStore, MealStore) is already wired and working. The question is how to extend it, not what to replace it with.

---

## Recommended Stack

### Core Technologies

All existing — no new core frameworks.

| Technology | Version | Purpose | Why Keep It |
|------------|---------|---------|-------------|
| Firestore (`users/amit`) | existing | Living plan + block state | UserProfileStore scaffold already exists; merge-patch discipline established; no new DB needed |
| Postgres (`activities`, `daily_biometrics`) | existing | Benchmark result queries + trend analytics | 3yr backfill lives here; `compute_acwr` already reads it; benchmark snapshots fit as additional columns on `activities` or a thin new table |
| Pinecone `klaus-memory` (768-dim, cosine) | existing | Optional: coaching knowledge RAG namespace | Index already live; adding a `kind="coaching"` namespace costs zero infra |
| `prompts/*.md` + `docs/` flat files | existing | Primary vehicle for curated coaching knowledge | Brain context window can hold the full blueprint + principles doc; no retrieval plumbing needed for a single well-structured document |
| TrainingLogStore (Firestore `training_log`) | existing | Session-level log with RPE/feel/notes | Already logs sessions; add `benchmark: bool` flag + facet fields to existing schema via merge-patch |

### Supporting Libraries

No new dependencies required. All of the following already exist in the project:

| Library | Already In Project | Purpose in v4.0 | Notes |
|---------|-------------------|----------------|-------|
| `google-cloud-firestore` | yes | UserProfileStore extended schema | Use `merge=True` upserts — same discipline as all other stores |
| `psycopg2` | yes | Benchmark queries + trend queries against Postgres | `database_tool.py` already wraps this with read-only guard |
| `pinecone` | yes | `kind="coaching"` namespace if RAG path chosen | Only needed if RAG path is taken (see decision below) |
| `google-genai` (embedding) | yes | Embed coaching content for RAG | Only needed if RAG path taken; `MemoryStore._embed` already handles this |

### Development Tools

No changes — existing `pytest`, `ruff`, and Cloud Run deploy pipeline remain unchanged.

---

## The Three Key Design Decisions

### Decision 1: Coaching Knowledge — Prompt-Injected Doc, NOT RAG

**Recommendation: a single `docs/COACHING.md` flat file injected into the smart agent system prompt at render time, NOT Pinecone RAG.**

Why prompt injection wins for this use case:

- The coaching knowledge corpus is small and bounded. The hybrid-athlete blueprint is ~1,500 words. A distilled coaching principles doc (interference effect, block periodization, session execution, fueling science) will be another ~2,000-3,000 words. Total: comfortably under 6,000 tokens — well within Gemini flash's context window, and always present.
- The brain needs the full coaching context on every coaching-related exchange, not just when a specific query triggers retrieval. A Telegram message like "how did I do this week?" requires access to all facets simultaneously — RAG would need to retrieve the right chunks without knowing which ones are needed.
- RAG introduces retrieval latency + embedding cost on every coaching turn. At a single-user scale with bounded knowledge, this is pure overhead.
- A flat file in `docs/` is editable, version-controlled, and self-documenting. When Amit updates the blueprint, the coaching doc updates in a single edit + deploy.
- The `render_smart_system` function in `core/main.py` already injects `{self_md}`, `{self_state}`, and `{journal_digest}`. Adding `{coaching_knowledge}` is a two-line change.

**The right use of `kind="coaching"` in Pinecone would be** for storing individual benchmark results or weekly narrative summaries that should be semantically searchable over time — not for the expert principles doc. Do NOT embed and RAG the static principles doc.

**What the `docs/COACHING.md` should contain:**
- Distilled hybrid-athlete principles: concurrent training interference effect, how to manage it (run AM / lift PM with ≥6h gap, sequence runs before lifts on the same day only when unavoidable)
- Block periodization: what a block is, how to identify block transitions, what benchmark tests map to which facets
- Session execution notes: specific coaching cues for the blueprint's sessions (what "heavy, driving toward 120kg" means in practice, fatigue squeeze protocol, threshold run structure)
- Fueling science: the 6-part timeline from the blueprint with reasoning (why post-run carb reload matters, beta-alanine timing, creatine protocol)
- The full AM/PM weekly split table verbatim
- The 16-week aerobic progression table verbatim
- Dated goals verbatim (October / November peaks)

This document is the "coaching brain" — inject it, don't retrieve it.

### Decision 2: Living Plan — Extended UserProfileStore in Firestore

**Recommendation: extend the existing `users/amit` Firestore document with a richer schema. Do NOT create a separate collection.**

The current scaffold has `athletic_goals: []`, `training_constraints: []`, `recovery_preferences: {}`, `schema_version: 1`. This is intentionally minimal and was designed to be extended.

**Extended schema for v4.0** (merged via `UserProfileStore.update()` with `merge=True`):

```python
{
    # --- existing fields (preserved) ---
    "schema_version": 2,
    "updated_at": SERVER_TIMESTAMP,

    # --- dated goals (from blueprint §1) ---
    "goals": {
        "october": {
            "bench_kg": 100,
            "squat_kg": 120,
            "half_marathon_time": "1:25:00",
            "deadline": "2026-10-31"
        },
        "november": {
            "push_ups": 125,
            "pull_ups": 35,
            "run_3k_time": "9:30",
            "run_400m_time": "0:55",
            "deadline": "2026-11-30"
        }
    },

    # --- weekly training template (from blueprint §2) ---
    "weekly_template": {
        "sunday":    {"am": "rest_or_sleep", "pm": "mixed_practice"},
        "monday":    {"am": "easy_run", "pm": "lower_body_a"},
        "tuesday":   {"am": "medium_long_run_strides", "pm": "upper_body_a"},
        "wednesday": {"am": "threshold_run", "pm": "lower_body_b"},
        "thursday":  {"am": "easy_run", "pm": "upper_body_b"},
        "friday":    {"am": "long_run", "pm": "mobility_sauna"},
        "saturday":  {"am": "rest", "pm": "rest"}
    },

    # --- nutrition framework (from blueprint §6) ---
    "nutrition": {
        "daily_targets": {"protein_g": 150, "carbs_g": 350},
        "fueling_timeline": [
            {"slot": "pre_am_run", "content": "30-50g simple carbs + coffee"},
            {"slot": "post_am_run", "content": "oats/rice/sourdough + 3-4 eggs. Vitamin D3+K2 + Omega-3"},
            {"slot": "midday", "content": "lean beef/steak + complex carbs + greens"},
            {"slot": "pm_pre_lift", "content": "30-60min prior: electrofuel or fruit. Beta-Alanine"},
            {"slot": "pm_post_lift", "content": "high protein + digestible carbs + Creatine"},
            {"slot": "pre_bed", "content": "Magnesium Glycinate + Zinc + Copper 30-60min before sleep"}
        ]
    },

    # --- supplement schedule ---
    "supplements": [
        {"name": "Vitamin D3+K2", "timing": "post_am_run"},
        {"name": "Omega-3", "timing": "post_am_run"},
        {"name": "Beta-Alanine", "timing": "pm_pre_lift"},
        {"name": "Creatine", "timing": "pm_post_lift"},
        {"name": "Magnesium Glycinate", "timing": "pre_bed"},
        {"name": "Zinc", "timing": "pre_bed"},
        {"name": "Copper", "timing": "pre_bed"}
    ],

    # --- aerobic progression (from blueprint §4) ---
    "aerobic_plan": {
        "goal_hm_pace_per_km": "4:01",
        "zone2_range": {"min_pace": "4:50", "max_pace": "5:30"},
        "weeks": [
            {"week": 1, "phase": "aerobic_base", "long_run_km": 16, "threshold_vol_km": 6, "threshold_pace": "3:55"},
            # ... all 16 weeks; store as array of dicts
        ]
    },

    # --- per-facet current state (populated incrementally by Klaus from data) ---
    "current_state": {
        "bench_1rm_kg": null,           # updated after benchmark sessions
        "squat_1rm_kg": null,
        "push_up_max": null,
        "pull_up_max": null,
        "run_3k_best": null,
        "run_400m_best": null,
        "hm_threshold_pace": null,
        "last_assessed": null
    },

    # --- current training block ---
    "current_block": {
        "block_id": "block-1",          # e.g. "block-1", "block-2"
        "start_date": "2026-06-03",
        "target_end_date": "2026-07-28",  # ~8 weeks typical block
        "phase": "aerobic_base",         # maps to aerobic_plan.weeks phase
        "week_in_block": 1,              # incremented weekly
        "benchmark_due": false,
        "benchmark_session_date": null
    }
}
```

**Why this lives in `users/amit` (not a sub-collection):**
- The brain reads the entire profile doc on every coaching-relevant call (morning briefing, evening check-in, weekly review). A single document read is one Firestore RPC; a sub-collection read is multiple RPCs plus a collection stream.
- The data is not write-heavy at the field level — it's updated by Klaus once per session at most. Firestore's 1MB doc limit is nowhere near a concern here (this schema is ~5KB).
- `UserProfileStore.load()` already returns the full dict; all callers get the full context with zero changes.
- `merge=True` upserts mean Klaus can update individual nested paths (`current_state.bench_1rm_kg`) without overwriting the rest of the doc.

**One caveat on nested object updates in Firestore:** To update a single field inside a nested map (e.g. `current_state.bench_1rm_kg`) without clearing sibling keys, use dotted-path notation: `{"current_state.bench_1rm_kg": value}` with `merge=True`. This is existing Firestore behavior — no new library capability needed.

### Decision 3: Block/Benchmark Tracking — Split Between Firestore and Postgres

**Recommendation:**
- Block state (current block metadata, week number, benchmark due flag) lives in `users/amit` (see `current_block` above).
- Benchmark test **results** are recorded as a new Postgres table `benchmark_results`.
- TrainingLogStore gets a `benchmark: bool` flag added (merge-patch compatible, backward safe) to mark which sessions were benchmark tests.

**Why NOT a new Firestore `BlockStore` collection:**
- Block metadata is just a handful of scalar fields that belong logically alongside the user profile. A separate collection adds a second RPC and a second store class for no structural gain.
- There will be at most ~6-10 blocks over the Oct/Nov training horizon. This is not a collection-scale problem.

**Why a new Postgres table for benchmark results (instead of TrainingLogStore):**
- Benchmark results need to be queried as a time series for trend analysis: "show bench 1RM progression across blocks". SQL is the right tool for this — `SELECT facet, result_value, tested_at FROM benchmark_results ORDER BY tested_at`.
- The existing `database_tool.py` read-only query interface already provides this to the brain — no new tool needed, brain can issue SQL.
- Benchmark results are structured tabular data (facet, value, units, block_id, tested_at), not the session-level narrative that TrainingLogStore holds.
- Firestore's TrainingLogStore stream-and-filter approach (no composite index for cross-session analytics) would make trend queries ugly.

**New Postgres table schema** (additive, idempotent DDL):
```sql
CREATE TABLE IF NOT EXISTS benchmark_results (
    id SERIAL PRIMARY KEY,
    tested_at DATE NOT NULL,
    block_id VARCHAR(20) NOT NULL,          -- e.g. "block-1"
    facet VARCHAR(50) NOT NULL,             -- "bench_1rm", "squat_1rm", "push_up_max", etc.
    result_value NUMERIC(8,2) NOT NULL,
    units VARCHAR(20) NOT NULL,             -- "kg", "reps", "seconds", "min:sec"
    notes TEXT,
    source VARCHAR(20) DEFAULT 'telegram'   -- "telegram" | "manual_chat" | "garmin"
);
CREATE INDEX IF NOT EXISTS idx_benchmark_facet_date ON benchmark_results (facet, tested_at);
```

**This DDL lives in** `scripts/` as a migration script (same pattern as `ingest_garmin_zip.py`'s SCHEMA_DDL). It runs once on deploy. No ORM needed — plain psycopg2 INSERT matches the existing pattern in `database_tool.py`.

**TrainingLogStore extension** — add `benchmark: bool | None` to the `log_session` call signature and payload dict. Because `merge=True` is used everywhere and existing docs don't have this field, it defaults to `None` (falsy) on all pre-existing sessions. No migration needed.

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| A dedicated `CoachingKnowledgeStore` Firestore collection | Over-engineered. The coaching knowledge is a bounded static doc, not per-session state. | `docs/COACHING.md` injected via `render_smart_system` |
| Pinecone RAG for the coaching principles doc | Adds retrieval latency + embedding cost with no benefit for a small, always-needed document | Direct prompt injection |
| A separate `BlockStore` Firestore collection | Adds a new store class + collection for what is 6-8 scalar fields | `current_block` map inside `users/amit` |
| Vector embeddings for benchmark results | Benchmark trends are structured numerical queries, not semantic search | Postgres `benchmark_results` table + existing `database_tool.py` |
| A new Python ORM (SQLAlchemy, etc.) | Existing project uses raw psycopg2 with `RealDictCursor` everywhere; adding an ORM for one table creates inconsistency | Raw psycopg2 INSERT, same pattern as ingestion scripts |
| A new `BenchmarkStore` Firestore class | Duplicates what Postgres does better for time-series data | `benchmark_results` Postgres table |
| Webhook or external API for blueprint ingestion | Blueprint is a one-time ingest; a `scripts/ingest_blueprint.py` script running locally is sufficient | One-shot CLI script |
| New LLM model or new API backend | Brain (Gemini flash) is fully capable of expert coaching reasoning when given the curated knowledge doc | Extend `docs/COACHING.md`, not the model |
| Pinecone namespace isolation for coaching | Pinecone serverless doesn't support namespaces for filtering — `kind` metadata filter is the existing isolation mechanism; adding `kind="coaching"` for dynamic benchmark summaries is valid but the static doc should NOT go here | `kind` metadata on dynamic content only |

---

## Integration with Existing Systems

### D-13 Guard Release

The D-13 "no-fabrication" guard in `prompts/morning_briefing.md` and `prompts/proactive_alert.md` is a conditional block checking whether `UserProfileStore` is populated. Once `users/amit` is populated with `goals`, `current_state`, and `current_block`, the brain can:
- Name specific target weights/paces from `goals`
- Compare current performance to `current_state.*_kg / *_best` fields
- Reference the specific session from `weekly_template` for today's day

The guard condition changes from "profile is empty" to "current_state has been assessed" — i.e., release the guard once at least one benchmark session has been recorded. This is a prompt change, not a code change.

### Cron Integration

No new cron jobs needed. v4.0 coaching is folded into:
- **Morning briefing** (`core/morning_briefing.py`): reads `UserProfileStore` (already does), now has nutrition targets + weekly template to compare against
- **Evening check-in** (`core/proactive_alerts.py`): already reads `UserProfileStore` for athletic_goals; extended schema gives it real targets
- **Weekly review** (`core/weekly_training_review.py`): already reads `UserProfileStore.athletic_goals`; extended schema + benchmark query gives it per-block trend data
- **Autonomous tick** (`core/autonomous.py`): already gathers `UserProfileStore`; gains supplement adherence checking, block-week awareness

### Brain Tool: `get_user_profile` (new or existing)

The brain needs a direct tool to read `UserProfileStore` on demand (outside cron flows). Check whether `tools.py` already exposes this as a direct tool; if not, add one. It is a thin wrapper over `UserProfileStore.load()` — no new logic.

### `render_smart_system` Change

`core/main.py` renders the brain system prompt with `{self_md}`, `{self_state}`, `{journal_digest}`. Add `{coaching_knowledge}` — loaded from `docs/COACHING.md` at startup (same pattern as SELF.md). This is the primary integration point for expert coaching capability.

---

## Installation

No new Python packages to install. All capabilities use existing dependencies:

```bash
# No new pip installs needed.
# Verify existing deps are present:
# - google-cloud-firestore (Firestore UserProfileStore)
# - psycopg2 (Postgres benchmark_results DDL + queries)
# - pinecone (if kind="coaching" RAG for benchmark summaries chosen)
# - google-genai (embedding, only if RAG path)
```

The one "installation" step is running the benchmark_results DDL migration — a one-line psycopg2 execute from a `scripts/create_benchmark_table.py` or appended to the existing `ingest_garmin_zip.py` SCHEMA_DDL string.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `docs/COACHING.md` injected into system prompt | `kind="coaching"` Pinecone RAG | If the corpus grows to >20K tokens and becomes a reference library queried selectively; not the case here |
| Extended `users/amit` single document | Sub-collections per concern (goals, nutrition, blocks) | If data grows to collection scale (>100 items per entity) or if concurrent writes from multiple processes become a concern; neither applies |
| `benchmark_results` Postgres table | `BenchmarkStore` Firestore collection | If the project ever drops Postgres; Firestore would work but loses the SQL trend query capability that `database_tool.py` already provides |
| `benchmark_results` Postgres table | Benchmark fields directly on `TrainingLogStore` docs | Would work for simple lookups but makes trend-across-blocks queries require streaming the entire `training_log` collection and filtering in Python |
| Prompt injection of coaching doc | Fine-tuning the brain model | Would be 100x cost + complexity for marginal gain; Gemini flash is capable of expert reasoning with good context |

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| Firestore UserProfileStore extension | HIGH | Direct read of existing code; merge-patch discipline already proven across SelfStateStore, MealStore, TrainingLogStore |
| Postgres benchmark table | HIGH | Schema follows exact pattern already in `ingest_garmin_zip.py`; `database_tool.py` provides brain access already |
| Prompt injection for coaching knowledge | HIGH | `render_smart_system` pattern is live; SELF.md injection proves the mechanism; token budget is not a concern for Gemini flash |
| No new dependency needed | HIGH | Exhaustive check of all three capability areas; every primitive is already imported and used |
| Pinecone `kind="coaching"` for dynamic summaries | MEDIUM | Valid but optional; only needed if benchmark narrative summaries need to be semantically searchable over time — can be deferred to a later phase |

---

## Sources

- `memory/firestore_db.py` — `UserProfileStore`, `TrainingLogStore`, `MealStore` — direct code read (HIGH)
- `memory/pinecone_db.py` — `MemoryStore` kinds, embedding, recall filter — direct code read (HIGH)
- `scripts/ingest_garmin_zip.py` — Postgres schema DDL and psycopg2 pattern — direct code read (HIGH)
- `mcp_tools/database_tool.py` — read-only Postgres query interface — direct code read (HIGH)
- `core/main.py` (partial) — `render_smart_system` injection pattern — inferred from CLAUDE.md description (MEDIUM, verify at implementation time)
- `prompts/morning_briefing.md`, `prompts/proactive_alert.md` — D-13 guard location — direct code read (HIGH)
- `/Users/amitgrupper/Downloads/Hybrid Athlete Master Blueprint_ Oct_Nov Peak V2.md` — blueprint content for schema design — direct file read (HIGH)

---
*Stack research for: Klaus v4.0 — Expert Coaching Knowledge Layer, Living Plan, Block/Benchmark Tracking*
*Researched: 2026-06-03*
