# Phase 30: Health Pages - Context

**Gathered:** 2026-07-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Read-only health visualization pages in the Klaus Hub — the last phase of v5.0.
Delivers (HLTH-01..03) behind the existing `/health` route (currently a
`ComingSoon` placeholder, nav entries already in Sidebar/BottomTabs):

- **Training history:** a browsable, color-coded, mixed session log (Hevy
  strength sessions + Garmin run details + benchmark results) with full
  per-set / per-lap drill-down, weekly volume + pace trend charts, and
  training-block context woven in — from `StrengthSessionStore`,
  `RunDetailStore`, `BenchmarkStore`, `BlockStore`.
- **Nutrition detail:** daily macro trends (calories/protein/carbs/fat/fiber)
  vs `nutrition_targets`, a fueling-slot adherence grid over time, and
  tap-a-day meal drill-down — from `MealStore` (display-only; the
  Lifesum → HealthKit pipeline is untouched).
- **Sleep & recovery:** header stat row (last night) + three stacked trend
  charts — HRV (overnight vs 7-day baseline), sleep (score + duration), body
  battery — from Postgres `daily_biometrics` (fed by the new
  `/cron/biometric-sync` pipeline, `core/biometric_ingest.py`).

This phase introduces **charting to the hub for the first time** — the
frontend has NO chart library today (see D-04 + Claude's Discretion).

**NOT in this phase:** any data entry or editing (all three pages are
read-only visualizations); nutrition logging (locked milestone out-of-scope);
new Klaus tools or coaching behavior changes; changes to ingest crons.
**Visual/pixel design** is handled separately by `/gsd:ui-phase 30`
(UI hint = yes) — this file captures product/behavior, not layout.

</domain>

<decisions>
## Implementation Decisions

### Page structure & navigation
- **D-01:** **Segmented sub-tabs** inside the Health tab — Training /
  Nutrition / Sleep — mapping 1:1 to HLTH-01/02/03. No overview dashboard,
  no single long scroll.
- **D-02:** **Remember the last-visited sub-tab** (client-side state); default
  landing is Training on first visit.
- **D-03:** **Desktop keeps the standard frame** — Health renders in the same
  center column as Today/Tasks with the glance rail and collapsible docked
  chat intact. No full-width layout exception.
- **D-04:** **Chart interactivity = tap/hover for values** (tooltips showing
  the exact value per point) + the range toggles. No zoom/pan/scrubbing, not
  purely static either. Keep the bundle light and iOS-Safari-friendly —
  library choice → Claude's discretion.

### Time windows & history depth (cross-cutting, all three pages)
- **D-05:** **Preset range toggles only: 7d / 30d / 90d / 1y** — consistent
  across all three pages. No free date-range picker, no infinite scroll-back.
- **D-06:** **Default range = 30 days** on page open.
- **D-07:** **1 year is the deepest preset.** Ranges over ~90 days aggregate
  to **weekly points** (averages/totals as appropriate) so charts stay
  readable and queries cheap. The ~3-year Postgres Garmin history stays
  Klaus-chat territory — not surfaced in the hub this phase.
- **D-08:** **Missing days render as visible gaps** — never drawn as zero,
  never interpolated. Matches `fetch_nutrition_trend`'s `missing_dates`
  semantics (unlogged day ≠ zero-calorie day; watch-not-worn ≠ HRV of 0).

### Training history page (HLTH-01)
- **D-09:** **One mixed reverse-chronological session log** — strength
  sessions, runs, and benchmark results interleaved, **each modality
  color-coded** with its own accent color on cards/badges (Amit's explicit
  ask; exact colors → ui-phase).
- **D-10:** **Full detail drill-down on tap:** strength → complete per-set
  table (exercise, sets × reps × kg); runs → lap/split table with pace + HR
  per lap (lap data exists in `RunDetailStore`); benchmarks → measured result
  vs previous.
- **D-11:** **Two compact trend charts above the log:** weekly strength
  volume (tonnage or sets) and running pace/distance trend, both respecting
  the range toggle.
- **D-12:** **Block context + benchmarks woven into the log:** block
  boundaries render as labeled dividers ("Block 2 — Strength Focus", from
  `BlockStore`) and benchmark results appear as highlighted entries at their
  date — the log reads like the actual periodized plan.

### Nutrition detail page (HLTH-02)
- **D-13:** **Fueling-slot adherence = contribution-style slot-hit grid** —
  rows are fueling slots, columns are days, cells mark whether a meal was
  logged in that slot. Same visual language as the Phase-28 habit grid.
  Adherence keys off **slot labels only** — never inferred eating times
  (HealthKit/Lifesum canonical-slot-time invariant).
- **D-14:** **Macro trend = one main daily chart defaulting to calories, with
  a chip row toggling** the series to protein / carbs / fat / fiber.
- **D-15:** **Target line + averages:** the selected metric's target from
  `UserProfileStore.nutrition_targets` renders as a reference line on the
  chart; a summary row shows range average vs target, including protein g/kg
  bodyweight (mirroring `fetch_nutrition_trend`).
- **D-16:** **Day drill-down:** tapping a bar or grid cell opens that day's
  meal-by-meal breakdown by slot with per-meal macros (`MealStore.get_day`).
  Slot labels presented as slots, never as eating times.

### Sleep & recovery page (HLTH-03)
- **D-17:** **Three stacked charts** (not a single-toggle chart): HRV, sleep
  (score + duration), body battery — recovery is about seeing the metrics
  move together.
- **D-18:** **HRV chart overlays both series:** overnight HRV as the daily
  line/points + the rolling 7-day baseline as a smoother second line — the
  gap between them is the recovery signal Klaus's coaching already uses
  (`core/recovery_metrics.py`).
- **D-19:** **Header stat row** at the top with last night's numbers — HRV,
  sleep score, body battery, resting HR, training readiness. Resting HR and
  readiness get NO dedicated chart (they live only in the stat row).

### Claude's Discretion
- **Chart library choice** (constrained by D-04: tooltips + light bundle +
  iOS-Safari touch; e.g., Recharts vs a small custom-SVG layer — pick what
  fits the existing React 19 / Tailwind 4 / Vite 8 stack and PWA bundle
  budget).
- Backend API shape: new `/api/health/*` (or similar) session-auth endpoints;
  **server-computed aggregates** (follow the `fetch_nutrition_trend` /
  `get_day_aggregate` precedent — never ship raw docs for the client to sum);
  weekly-bucket aggregation mechanics for D-07; caching/react-query staleness.
- How the Postgres `daily_biometrics` reads are wired into a hub route
  (existing `mcp_tools/database_tool.py` / garmin_tool patterns; watch
  connection reuse + event-loop blocking — run DB calls in an executor).
- Strength "volume" metric definition for D-11 (tonnage vs hard-set count) —
  pick what `StrengthSessionStore` data computes most honestly.
- Which fueling slots the D-13 grid rows show (the 6-slot v4.0 fueling
  vocabulary vs the subset that actually appears in MealStore data).
- Skeleton/loading/empty states following existing hub patterns; per-chart
  empty-state wording when a range has no data.
- All visual/layout/animation/color specifics → `/gsd:ui-phase 30`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements (locked source of truth — with this session's decisions)
- `docs/superpowers/specs/2026-06-13-klaus-hub-design.md` — v5.0 design spec:
  § 3 Layout (Health in sidebar + bottom tabs), § 5 Build phases (Phase 5 =
  Health pages: training history from Hevy/Garmin stores, nutrition detail,
  sleep trends). Where it conflicts with the decisions above, **the decisions
  here win**.
- `.planning/REQUIREMENTS.md` — HLTH-01..03 + Out-of-Scope table (no
  nutrition data entry in the hub).
- `.planning/ROADMAP.md` § Phase 30 — goal + 3 success criteria (browsable by
  date range; macros distinguished with a slot view; visible patterns over
  days and weeks).

### Data sources (the stores these pages visualize)
- `memory/firestore_db.py` — `StrengthSessionStore` (≈ line 1087, full
  per-set Hevy workouts), `RunDetailStore` (≈ line 1226, per-run Garmin
  detail incl. lap splits), `BenchmarkStore` (≈ line 2263, 5-facet closed
  set), `BlockStore` (≈ line 2080, date-range block resolution), `MealStore`
  (≈ line 711, `get_day` / `get_day_aggregate` with dedup). All reads must go
  through `_jsonsafe_doc`-style ISO conversion before JSON.
- `core/tools.py::_handle_fetch_nutrition_trend` (≈ line 2302) — the
  server-computed nutrition series precedent: per-day series + averages +
  `missing_dates` + targets + protein g/kg. The nutrition page's API should
  mirror (or share) this logic, not reimplement its semantics.
- `scripts/ingest_garmin_zip.py` (≈ line 25) — `daily_biometrics` Postgres
  schema: date, resting_hr, hrv_baseline, hrv_overnight, sleep_score,
  sleep_duration, body_battery_max, training_readiness.
- `core/biometric_ingest.py` — the daily `/cron/biometric-sync` pipeline that
  keeps `daily_biometrics` filled (backfill→delta modes; today/yesterday
  always re-fetched). **Deploy dependency:** per project memory
  (2026-07-05), the Cloud Scheduler job for biometric-sync may still be
  pending — verify the cron is live before UAT of the Sleep page.
- `core/recovery_metrics.py` — how overnight-vs-baseline HRV is already
  interpreted (D-18 context).
- `mcp_tools/database_tool.py` + `mcp_tools/garmin_tool.py`
  (`write_biometrics_to_postgres`) — existing Postgres access patterns.

### Frontend integration points
- `frontend/src/App.tsx` — `/health` route is a `ComingSoon` placeholder
  (≈ line 96); replace with the real page. Sub-tab state per D-01/D-02.
- `frontend/src/components/layout/{Sidebar,BottomTabs}.tsx` — Health nav
  already exists; no nav changes expected.
- `frontend/src/api/client.ts` (`apiFetch`) + `frontend/src/hooks/*`
  (`useToday` etc.) — react-query data-fetching pattern to mirror.
- Phase-28 habit history grid component — visual + code precedent for the
  D-13 slot-hit contribution grid.
- `frontend/package.json` — NO chart library present; adding one is a
  deliberate act (D-04 constraints, bundle size vs the PWA precache).

### Backend integration points
- `interfaces/web_server.py` — new health endpoints go under `/api/*` with
  `require_hub_session`; do NOT touch OIDC `/cron|/internal|/trigger` routes
  (HUB-04 invariant).

### Prior-phase context (patterns to follow)
- `.planning/phases/28-habits-supplements/28-CONTEXT.md` — habit grid,
  Asia/Jerusalem date logic, store/API/react-query conventions.
- `.planning/phases/26-hub-shell/26-CONTEXT.md` — session auth, `/api/today`
  aggregator composition pattern (the health endpoints are its read-only
  siblings), skeleton/offline behavior.

### Project invariants
- `CLAUDE.md` § 6 Invariants — **HealthKit/Lifesum meal timestamps are
  canonical slot times, never eating times** (drives D-13/D-16); JSON-safe
  Firestore reads; lowercase `klaus-` naming; every external client carries
  explicit timeouts; never block the event loop in request handlers
  (Postgres reads → executor; weekly-review 500 incident class).
- `.planning/STATE.md` § Notes — Asia/Jerusalem for all date bucketing;
  Python 3.11/3.13 (NEVER 3.14); test baseline (1720 backend + 122 frontend)
  must hold; run pytest per-file (full-suite segfault).
- **Frontend gotchas (from memory):** inline `display` in `style={{}}`
  overrides Tailwind responsive classes (bit Phase-27 UAT 4×); iOS
  bottom-sheet z-index/keyboard traps; SPA/auth paths have NO CI coverage —
  smoke the deployed URL manually after deploy.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fetch_nutrition_trend` handler (`core/tools.py`) — ready-made per-day
  nutrition series + averages + targets + missing-dates semantics; the
  nutrition API endpoint should share/extract this logic.
- `MealStore.get_day_aggregate` / `get_day` — server-computed day totals +
  deduped per-meal reads for D-14/D-16.
- Postgres `daily_biometrics` (3-year backfill + daily biometric-sync cron) —
  the complete HLTH-03 data source; no new ingestion needed.
- `StrengthSessionStore` / `RunDetailStore` / `BenchmarkStore` / `BlockStore`
  — all HLTH-01 data already captured (per-set, per-lap, benchmarks, blocks).
- Phase-28 habit contribution grid — component precedent for the slot-hit
  grid (D-13).
- `/api/today` aggregator — composition pattern for multi-store read-only
  endpoints.

### Established Patterns
- `/api/*` = session-cookie auth (`require_hub_session`); `/cron|/internal|
  /trigger` = OIDC — new health routes must not weaken OIDC routes (HUB-04).
- Server computes aggregates, client renders — never ship raw docs for the
  LLM/client to sum (the drifting-numbers lesson behind `totals_by_day`).
- react-query + `apiFetch`, refresh-on-focus, skeletons on load — reuse for
  all three pages (read-only, so no optimistic updates needed this phase).
- All date bucketing in Asia/Jerusalem local time.

### Integration Points
- New read-only health endpoints under `/api/*` in
  `interfaces/web_server.py` (Firestore stores + one Postgres reader).
- `/health` route in `frontend/src/App.tsx` (ComingSoon → sub-tabbed page).
- New chart components + a first chart library (or custom SVG) in
  `frontend/src/components/` — the phase's only genuinely new frontend
  infrastructure.

</code_context>

<specifics>
## Specific Ideas

- **Color-coded mixed training log** — Amit's explicit ask: one interleaved
  stream, "each training modality a different color or something" (strength /
  run / benchmark visually distinct at a glance).
- **The log should read like the periodized plan** (D-12) — block dividers +
  benchmark highlights in the stream, echoing the "Week N of 16" framing his
  briefings already use.
- **Honest data presentation** carries over from coaching: gaps are gaps
  (D-08), targets are visible reference lines not buried numbers (D-15), and
  slot times are never presented as eating times (D-13/D-16).
- **HRV overnight-vs-baseline overlay** (D-18) mirrors how Klaus already
  reasons about recovery — the page visualizes the same signal the coach uses.

</specifics>

<deferred>
## Deferred Ideas

- **Custom date-range picker / arbitrary windows** — rejected for preset
  toggles only (D-05); revisit if a real "exactly Block 2" need appears.
- **Surfacing the full ~3-year Garmin history in the hub** — 1y is the
  deepest preset (D-07); deep history stays accessible via Klaus chat.
- **Fully interactive charts (zoom/pan/scrubbing)** — rejected (D-04) for
  bundle weight + iOS touch edge cases.
- **Overview/summary dashboard as the Health landing view** — rejected for
  direct sub-tabs (D-01); could return as a future glance surface.
- **Per-slot macro-depth adherence view** ("is the post-lift slot carrying
  protein") — the slot-hit grid (D-13) ships first; macro-per-slot depth is a
  natural v2 of the nutrition page.
- **Dedicated resting-HR / training-readiness trend charts** — stat-row only
  this phase (D-19).

</deferred>

---

*Phase: 30-Health Pages*
*Context gathered: 2026-07-06*
