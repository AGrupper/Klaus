# Task 1 — Deterministic Claude-First Runtime Cutover

## Implementation

- Added `POST /cron/deterministic-alerts` as the canonical scheduler endpoint.
  It verifies the scheduler request, calls only `core.deterministic_alerts`, and
  records its deterministic run outcome. `POST /cron/autonomous-tick` is a
  `410 Gone` tombstone.
- Replaced the heartbeat's model/cost/deployment polling implementation with
  retained-only health checks: scheduler ledger freshness, Claude MCP/Routine
  readiness, Web Push health, and Cloud Run deployment identity. It has no
  model client, model meter, GitHub polling, Groq ledger, cost-tripwire,
  Telegram, or autonomous-outreach path.
- Removed Telegram and agent-runtime imports/startup from the FastAPI boundary.
  Startup opens only retained Claude MCP session managers. Telegram, Cloud
  Tasks agent/review processors, standalone reflection, proactive review,
  autonomous tick, and chat-ingest triggers are explicit `410` tombstones.
- Made Hub AI chat a hard `410` tombstone even if an old environment flag is
  set. Dashboard/auth/reviews/settings/Web Push/Ask Claude routes are retained.
- Made all three Morning/Nightly/Weekly Claude Routines live. Routine trigger
  routes now return `503` if the Claude cutover is unavailable rather than
  falling through to the retired in-process composer. Existing routine tests
  verify review persistence, Web Push review deep links, and stored sanitized
  Claude session URLs.
- Made Things the sole task authority. `get_task_store` ignores `TASK_BACKEND`;
  Things outages raise instead of returning Firestore mirror data. Firestore
  remains only a mirror/sidecar/outbox.
- Updated deployment/example configuration and v7 architecture documentation
  to make the Claude-first defaults explicit.

## Files changed

`interfaces/web_server.py`, `core/deterministic_alerts.py`, `core/heartbeat.py`,
`core/tools.py`, `memory/firestore_db.py`, `memory/things_store.py`,
`.env.example`, `.github/workflows/deploy.yml`, `docs/V7_ARCHITECTURE.md`, and
the focused/rebaselined Python tests listed in the commit.

## TDD evidence

- RED: `/Users/amitgrupper/Desktop/Klaus/.venv/bin/pytest -q tests/test_claude_first_cutover.py`
  before implementation: **12 failed** (missing deterministic endpoint and
  tombstones, weekly disabled, Firestore fallback, stale Things fallback).
- GREEN (initial cutover): the same focused cutover/rules/routines/Things group:
  **65 passed**.
- GREEN (final focused cutover):
  `pytest -q tests/test_claude_first_cutover.py tests/test_heartbeat.py tests/test_deterministic_alerts.py tests/test_subscription_routines.py tests/test_things_store.py tests/test_tools.py tests/test_web_server.py`:
  **235 passed, 63 skipped**. Skips are assertions for deliberately retired
  Telegram, Hub chat, and Cloud Tasks composer behavior; equivalent new
  cutover coverage is in `test_claude_first_cutover.py` and routine tests.

## Verification

- Focused lifecycle/MCP/main group: **218 passed in 16.16s**.
- Scheduler/Things/routine group: **379 passed, 7 subtests passed in 26.95s**.
- Frontend: `npm test -- --run && npm run build`: **29 files, 196 passed; build
  succeeded**. Existing React `act` and Workbox test warnings remain non-fatal.
- `python -m compileall -q` on changed runtime modules and `git diff --check`:
  passed.
- A whole-Python-suite `pytest -q` attempt reached 48% with no failure before
  the existing runner hang/process persistence recurred; its test process was
  terminated after 40 seconds. The focused groups above cover this task's
  changed surfaces and completed cleanly.

## Self-review

- Confirmed deterministic endpoint source has no imports of autonomous engine,
  LLM client, pricing/meter, scheduled-message delivery, or Telegram runtime.
- Confirmed no production command was run; only local source/config/test work
  occurred.
- Confirmed retained routine test coverage checks canonical Hub review storage,
  Web Push destination `/klaus/reviews/<routine>/<date>`, and sanitized Claude
  session/deep links.

## Concerns

- Retired legacy tests are skipped rather than deleted to document the removed
  contracts; a later cleanup task can remove their unreachable implementation
  bodies and test blocks wholesale.
- The full Python runner has a pre-existing process-persistence/hang around
  48%; no task regression was observed before termination.
