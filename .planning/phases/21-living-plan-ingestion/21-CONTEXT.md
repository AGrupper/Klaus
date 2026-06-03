# Phase 21: Living Plan Ingestion - Context

**Gathered:** 2026-06-03
**Status:** Ready for planning
**Source:** Synthesized from v4.0 kickoff record (REQUIREMENTS.md, ROADMAP.md, `docs/hybrid_athlete_blueprint.md`, and the 5 locked architectural decisions reached during milestone kickoff). No discuss-phase run — kickoff already gathered strong context and the user confirmed "plan from existing context."

<domain>
## Phase Boundary

**What this phase delivers (PLAN-01, PLAN-02, PLAN-03):**

Amit's Hybrid Athlete blueprint must live in `UserProfileStore` (Firestore `users/amit`) as **structured fields** that every cron and the brain can read — never a raw markdown blob, never per-session boolean attendance flags. The plan is a **flexible weekly template** (volume/trend targets, session priorities), and Amit can update any field at any time and have Klaus reason against the updated plan on the very next turn.

**In scope:**
1. **Schema expansion** of `UserProfileStore` from the current generic scaffold (`athletic_goals`, `training_constraints`, `recovery_preferences`) to the v4.0 structured fields: `dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, `plan_start_date`.
2. **Blueprint ingest** — populate `users/amit` from `docs/hybrid_athlete_blueprint.md` into those structured fields (a one-time seeding mechanism — script or bootstrap path).
3. **Update path (PLAN-03)** — Amit can say "update my bench goal to 105kg" or "change Thursday to rest day" and Klaus reasons against the updated plan on the next turn. Likely extends the existing `update_training_profile` tool (or adds an `update_plan` alias) to recognize the new structured keys.
4. **Prompt reframe** — the `{training_profile}` rendering in `render_smart_system` (core/main.py) frames the structured fields as a **coaching reference guide**, not a rigid contract.

**Out of scope (later v4.0 phases — do NOT build here):**
- Expert coaching knowledge / `COACHING_GUIDE.md` injection → Phase 22 (COACH).
- Block tracking, week numbers, benchmark testing, `BlockStore`/`BenchmarkStore` → Phase 23 (BLOCK).
- Cross-cron coaching message dedup → Phase 24.
- Any new crons, backends, or dependencies.
</domain>

<decisions>
## Implementation Decisions

### Structured schema (LOCKED — success criterion 1)
- `UserProfileStore.load()` must return non-empty `dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, and `plan_start_date` after ingest — structured fields, not a markdown blob.
- `plan_start_date` / block anchor = **Sunday 2026-06-21** (Block Week 1 start). Store this so Phase 23 can derive block boundaries from it.

### Flexible template, NOT attendance contract (LOCKED — PLAN-02, success criterion 2)
- `weekly_split` is stored as a **template** with session priorities and block-level volume targets — NOT per-session boolean attendance flags.
- Regression test framing: "did Klaus nag about a single missed session?" must stay answerable as NO. The schema must make per-session attendance-nagging structurally impossible (rigidity-drift pitfall — owned by this phase).
- The blueprint's AM/PM split (Section 2 of the blueprint) is the *shape* to encode: session names + priority + modality, not a checklist.

### Two kickoff narrowings (LOCKED — Amit explicit 2026-06-03, PLAN-01)
1. **Do NOT ingest the 16-week aerobic pace/volume table (blueprint Section 4) as a tracked target structure.** Amit: "just a general idea, I'll change pretty much everything." Store it as **loose directional reference at most** — its paces (3:55/km, 3:52/km, etc.) and weekly volumes are NEVER treated as contracts/targets. Durable content = dated goals + rough AM/PM split shape + fueling architecture + supplement schedule.
2. **Never hand-seed current performance baselines.** No "current bench" / "current pace" field populated by Amit typing a number. The profile holds **Tier A targets only**. Klaus derives **current performance (Tier B)** from real Garmin / `TrainingLogStore` data at read time. (Consequence for Phase 23: block boundaries anchor to `plan_start_date` + configurable block length, NOT to fixed table rows / hardcoded deload weeks.)

### Update path (LOCKED — PLAN-03)
- Amit updates goals/split/targets/dates conversationally; Klaus reasons against the updated plan on the **next turn** (the brain re-reads the profile each turn via `render_smart_system`, so a merge-write is sufficient — no cache invalidation needed).
- Klaus **recommends** structural changes when the plan is suboptimal (COACH-07 lives in Phase 22) but **never silently rewrites** — Amit adopts changes via this update path.

### Reuse existing plumbing (LOCKED — kickoff arch decision #2)
- **No new dependencies, crons, or backends.** Reuse Firestore (`UserProfileStore`), prompt-injection, and the existing LLM pipeline.
- The `{training_profile}` placeholder rendering already exists in `render_smart_system` (core/main.py:287–305) and in `prompts/smart_agent.md:7`. This phase **expands the schema + ingests data + reframes the rendering** — it does NOT add new plumbing.

### Claude's Discretion
- Exact Firestore field shapes (nested dicts vs. lists) for `weekly_split`, `nutrition_targets`, etc.
- Whether the update tool is a renamed/extended `update_training_profile` or a new `update_plan` tool name (success criterion 3 + roadmap goal both name `update_plan`; reconcile with the existing `update_training_profile` tool — prefer extending the existing one and/or adding `update_plan` as the user-facing name).
- Ingest mechanism: a `scripts/` seed script vs. an enhanced `bootstrap_if_empty`. Prefer an idempotent script that reads `docs/hybrid_athlete_blueprint.md` so re-ingest is safe and the blueprint stays the source of truth.
- How the `{training_profile}` snippet formats structured fields into readable coaching-reference prose (current code dumps raw `k: v`; this needs richer rendering — success criterion 4).
- `schema_version` bump strategy.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Blueprint source (the data to ingest)
- `docs/hybrid_athlete_blueprint.md` — the in-repo stable copy (committed `df696c4`): Oct/Nov dated goals (Section 1), AM/PM split (Section 2), strength protocol (Section 3), 16-week aerobic table (Section 4 — **loose reference only**, narrowing #1), mobility (Section 5), 6-slot fueling architecture + supplements (Section 6).

### Existing code to modify
- `memory/firestore_db.py:93` — `class UserProfileStore` (load/update/bootstrap_if_empty). Current scaffold (lines 113–118): `athletic_goals`, `training_constraints`, `recovery_preferences`, `schema_version`. Reads never raise, writes re-raise, every write stamps `updated_at: SERVER_TIMESTAMP`. **Note the recalled feedback:** Firestore `SERVER_TIMESTAMP` → `DatetimeWithNanoseconds` breaks `json.dumps` in read tools — ISO-convert / strip `updated_at` in any new read path that serializes to JSON.
- `core/main.py:287–305` — `render_smart_system` builds `training_profile_snippet` by dumping every non-empty `k: v`; reframe for coaching-reference prose. Profile is loaded fresh every turn (line 289) so updates take effect next turn with no cache work.
- `prompts/smart_agent.md:7` — `{training_profile}` placeholder; lines 77–95 — the TRAINING & ATHLETIC COACHING section that references `get_training_profile` / `update_training_profile` and the "if profile empty, don't invent" discipline.
- `core/tools.py:653` — `get_training_profile` schema; `core/tools.py:666` — `update_training_profile` schema (recognized keys listed in the description — must be expanded for the new structured keys); `core/tools.py:1286–1307` — the two handlers; `core/tools.py:1455–1456` — `_HANDLERS` dispatch entries.

### Phase governance
- `.planning/REQUIREMENTS.md` — PLAN-01/02/03 full text + the "Out of Scope" table (rows: silent plan modification, real-time HR monitoring, injury diagnosis, chat meal parsing).
- `.planning/ROADMAP.md` — Phase 21 section + the 4 success criteria.
- `.planning/research/` — `ARCHITECTURE.md`, `FEATURES.md`, `PITFALLS.md`, `STACK.md`, `SUMMARY.md` (v4.0 kickoff research; architecture already verified the wiring exists).
</canonical_refs>

<specifics>
## Specific Ideas

- **Fabrication regression is owned partly here**: the D-13 release / Tier A-vs-Tier B data-presence contract starts shipping in Phases 21–22. This phase establishes that the profile holds **targets only (Tier A)** and never measured baselines (Tier B). Keep the existing `smart_agent.md` discipline ("if profile empty, do NOT invent thresholds") intact and extend it to the structured fields.
- **v3.0 cron regression gate**: any change touching how `{training_profile}` renders must not break `morning_briefing`, the 21:30 `proactive_alerts`, or weekly training review consumers. Verify those crons still render cleanly with the expanded profile.
- Encode the AM/PM split (blueprint Section 2) as session priorities/modalities, e.g. each day → AM + PM entries with a session label, modality (run/lift/calisthenics/rest), and priority — never an attendance boolean.
- `dated_goals` should carry the Oct peak (100kg bench, 120kg squat, 1:25 HM) and Nov peak (125 push-ups, 35 pull-ups, 9:30 3k, 55s 400m) with their target dates.
</specifics>

<deferred>
## Deferred Ideas

- Expert coaching knowledge substrate (`docs/COACHING_GUIDE.md` prompt-injection) → Phase 22.
- Block/week tracking + benchmark testing (`BlockStore`, `BenchmarkStore`) → Phase 23. (This phase only stores `plan_start_date`; it does NOT compute week numbers or phase names.)
- Cross-cron nagging dedup store → Phase 24.
- Migrating block/benchmark trend queries to Postgres → only if Firestore outgrows it after 3+ blocks (Phase 23+ concern).
</deferred>

---

*Phase: 21-living-plan-ingestion*
*Context synthesized 2026-06-03 from v4.0 kickoff record*
