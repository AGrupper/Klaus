# Requirements: Klaus v7.0 — Subscription-First Personal OS

**Rebaselined:** 2026-08-08
**Status reconciled:** 2026-08-15 against the live cutover

The 2026-08-08 rebaseline was written before the cutover ran. Between 2026-08-09
and 2026-08-14 the Claude-first runtime went live, the legacy generative runtime
was removed, and the retired credentials were revoked. The statuses below are
reconciled against that reality; the original gate wording is preserved in the
notes where it no longer describes the world.

Verified on 2026-08-15 by a read-only `scripts/audit_production_drift.py` run
against the live service. One genuine drift remains, recorded under CUT-02.

## v7 delivery requirements

- [x] **SUB-01:** Dark-shipped, strict read-only MCP capability probe; no unsupported subscription-token bridge
- [x] **SUB-02:** OAuth 2.1 authorization code + PKCE S256, resource binding, revocation, and distinct interactive/routine scopes
- [x] **SUB-03:** Provider-neutral tasks, memory, directives, self-state, reviews, approvals, feedback, and portfolio state
- [x] **SUB-04:** Versioned live/daily/weekly Claude skills with deterministic ZIP drift tests and evaluation scenarios
- [x] **SUB-05:** Subscription Remote Routine trigger, atomic correlation, ten-minute deterministic fallback, late silent upgrade, and shadow mode
- [x] **SUB-06:** Server-side idempotency/audit, protected user calendar events, training recommendation-only routines, untrusted retrieved content, and prepared high-risk confirmation
- [x] **SUB-07:** Hub review/activity/approval/portfolio/status contracts and Ask Claude launch surface; legacy Hub chat independently fail-closed
- [x] **SUB-08:** No-model daytime evaluator limited to timed follow-ups, hard deadlines, calendar/travel conflicts, and critical automation failures
- [x] **SUB-09:** Dedicated Gemini embedding credential and usage meter; no invented Claude subscription cost
- [x] **SUB-10:** Capability/cutover/rollback flags, least-privilege Calendar-only post-legacy OAuth, architecture/security/deployment docs, and first-use checklist
- [x] **UAT-01:** Real Claude Pro connector reads Klaus — proved during the read-only probe phase; `KLAUS_CAPABILITY_MCP_VERIFIED=true`. The surface has since been opened to read/write (`KLAUS_MCP_READ_ONLY_MODE=false`), so the original "while the MCP surface is read-only" clause describes a phase that has passed, not an outstanding condition
- [x] **UAT-02:** Uploaded private skill loads and reports its version — proved at 7.0.0; `KLAUS_CAPABILITY_SKILL_VERIFIED=true`. The suite has since shipped 7.1.0, 7.2.0 and 7.3.0, so the pinned "7.0.0" is historical
- [x] **UAT-03:** API-triggered Remote Routine runs with the computer off, calls Klaus MCP, and publishes a validated result — `KLAUS_CAPABILITY_ROUTINE_VERIFIED=true` and `KLAUS_CAPABILITY_PUBLISH_VERIFIED=true`
- [ ] **UAT-04:** Morning/nightly/weekly shadow and live flows, iOS triggers, Hub push, memory/actions, directives, portfolio, and seven-day observation pass — **the one genuinely open gate.** All three routines are live and cut over; the observation window closes 2026-08-20
- [x] **CUT-01:** Telegram/Gmail/Readwise/chat-ingest/tick-brain/cascade/worker/generative SDKs and secrets removed without deleting historical data — executed 2026-08-12/13. **Ordering deviation:** the original text said "after UAT only"; the subtraction was taken before UAT-04 closed, on the reasoning that retired code left running was itself a risk. Retired infrastructure is quarantined rather than deleted, so the decision remains reversible until the 2026-08-20 audit. Historical Firestore documents, vectors, logs and reviews were preserved
- [ ] **CUT-02:** `CLAUDE_PROJECT_URL` is absent from the live service, so `/api/agent/status` returns an empty `project_url` and the Hub's Ask Claude page shows its setup notice instead of a launch link. The GitHub Actions repository variable is unset, so the deploy expanded it to an empty string and dropped the key — the same silent failure as the `KLAUS_USER_ID` incident of 2026-08-14. Needs the variable set and a redeploy

The unfinished v6 requirements `WB-01..04` and `HARD-01..05` were carried into
v7. Their status is reconciled below: the write-back obligations are delivered,
and the hardening obligations are either delivered or made void by the removal
of the runtime they were written to harden.

---

## Superseded v6.0 requirement archive

**Defined:** 2026-07-17
**Core Value:** Klaus should act as a genuinely intelligent, proactive companion that surfaces the right thing at the right time — while knowing exactly what he is and what he can do.

Source: approved implementation plan (`~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md`)
+ approved review amendments (`~/.claude/plans/mellow-puzzling-nest.md`) + 4-track research
(`.planning/research/`). Phase 0 (tick-brain → `openai/gpt-oss-120b`) shipped pre-milestone
2026-07-16 (commit `b784a1d`) and is not a requirement here.

## v6.0 Requirements

### Brain (Phase 30.5)

- [x] **BRAIN-01**: Every conversation turn and every paid proactive compose runs on `claude-sonnet-5`, with `gemini-3.5-flash` as the inline brain fallback
- [x] **BRAIN-02**: Anthropic prompt caching is active (cache_control on the stable system prefix, explicit 1h TTL), and LLMUsage records cache-read/cache-write tokens with `compute_cost` pricing them correctly — metering matches the Anthropic console within ~10%
- [x] **BRAIN-03**: Tick-brain fallback is decoupled from `SMART_AGENT_*` via explicit `TICK_BRAIN_FALLBACK_*` env (Gemini) — deployed BEFORE the brain model flip so Groq failures never bill at Sonnet rates
- [x] **BRAIN-04**: Heartbeat daily-spend tripwire — if yesterday's total LLM cost exceeds `KLAUS_DAILY_COST_ALERT` (default $5), Klaus tells Amit with a per-purpose breakdown and cache-hit rate
- [x] **BRAIN-05**: Sonnet-5 compatibility — no `temperature`/`top_p`/`top_k`/manual `thinking` sent on the Anthropic path; `max_tokens` policy set per call site with headroom for default-on adaptive thinking (module default 4096 revisited); `LLM_TIMEOUT_SECONDS` invariant kept and re-validated live
- [x] **BRAIN-06**: Always-on system prompt measurably slimmed — compact SELF.md manifest (per-tool + cron tables dropped) plus a light `smart_agent.md` de-prescription pass; target re-measured with the real Sonnet-5 tokenizer (`count_tokens`), not char estimates
- [x] **BRAIN-07**: `UserProfileStore` reads are TTL-cached (existing `_READ_CACHE` pattern) — no uncached Firestore read on every smart turn

### Standing Directives (Phase 31)

- [ ] **DIR-01**: Amit can state a lasting wish about Klaus's behavior in chat and Klaus stores it verbatim as a standing directive (origin, triggering-context quote) with a one-line ack — "I already told you…" is a named capture trigger
- [ ] **DIR-02**: Directives with a stated or implied end condition ("while I'm in France") expire on it; otherwise they persist until cancelled — no automatic TTL. Klaus may ask "until when?" only when genuinely unsure
- [ ] **DIR-03**: Active directives are injected verbatim into EVERY reasoning path (chat system prompt, tick triage as a Step-0 STANDING ORDERS veto above all other logic, Layer-2 compose, follow-up compose, interim cron gathers)
- [ ] **DIR-04**: Amit can list and cancel standing directives from chat
- [x] **DIR-05**: When a directive contradicts a baked-in persona routine, Klaus flags it and asks once which wins, recording the answer as a refined directive with a `superseded_by` link on the old one
- [ ] **DIR-06**: Nightly reflection reads a 24h conversation window (`get_recent_window`, built this phase) and extracts behavioral feedback — frustration, appreciation, corrections — pairing each Klaus-initiated outreach with Amit's reaction (replied / ignored / pushback)
- [x] **DIR-07**: Reflection may propose self-directives (`origin="klaus_self"`), surfaced to Amit in the nightly message with a one-line veto option

### Ambient Memory & Unified Situation (Phase 32)

- [x] **MEM-01**: Relevant Pinecone memories are auto-injected into every chat turn (score-thresholded, recency-weighted, k≈5) as a "Things you remember" block — best-effort with a short timeout; failure yields an empty block, never blocks the turn
- [x] **MEM-02**: When the active session is fresh/empty, the recent conversation tail is prepended so a morning "hey" after 6h idle doesn't meet an amnesiac
- [x] **MEM-03**: `forget_memory` tool (Pinecone delete by id) exists, and reflection flags memories contradicted by newer facts — deliberate-only forgetting, no auto-decay
- [x] **MEM-04**: The cascade sees the conversation tail (triage: 24h / ≤15 msgs / hard char cap; paid compose: 48h / ≤40 msgs) and a reconciled `training_reality` window (planned-from-split vs training_log vs Hevy/Garmin evidence vs calendar, today-3d..tomorrow) — a session completed or moved earlier satisfies its split slot, never re-asked
- [x] **MEM-05**: Every new gather (conversation_tail, standing_directives, training_reality, location) is context-only in `_is_empty_signals` — the free-tier empty gate is untouched; a token-budget guard test asserts the maximal rendered triage prompt + max_tokens fits the verified Groq per-request budget
- [x] **MEM-06**: A local Groq daily token ledger (Firestore counter — Groq exposes no daily-remaining header) alerts via heartbeat when approaching the 200K TPD cap or when `tick_fallback` purposes spike
- [x] **MEM-07**: The situation assembler derives `current_location` from calendar travel events + standing directives; weather and travel-time gathers use it — no more Tel Aviv forecasts delivered to Paris

### Occasion Cascade (Phase 33)

- [x] **OCC-01**: The nightly review runs as `occasion="nightly"` through the 3-layer cascade — fully skippable by judgment (silence = decision, recorded as `skipped_by_judgment`); total infra failure still sends the deterministic plain-text fallback (failure-skip ≠ judgment-skip)
- [x] **OCC-02**: The morning briefing runs as `occasion="morning"` through the cascade — Garmin wake-up anchor and 10:15 cutoff kept; `structured` snapshot + `daily_note` written only on actual send (hub `/api/today` contract); skips recorded
- [x] **OCC-03**: The Sunday weekly training review runs as `occasion="weekly_review"` through the cascade — the last legacy composer retired
- [x] **OCC-04**: Occasions bypass the empty gate (an occasion always gets a free triage judgment) with short occasion-guidance prompts — no mandated sections, no scheduling scripts; OutreachLog topic keys `nightly:<date>` / `morning:<date>` / `weekly:<date>`, append still gated on send success (D-10)
- [x] **OCC-05**: Layer 2 is agentic within a bounded tool-call budget; directive-gated proactive calendar writes check for an existing planned row / Training-calendar event for that date+slot before creating (idempotent under compose-retry)
- [x] **OCC-06**: Rollout behind `OCCASION_CASCADE=1` for one deploy cycle with no Cloud Scheduler changes; after a 3-4 day observation window, legacy composers + `prompts/nightly_review.md` / `morning_briefing.md` / `weekly_training_review.md` + the flag are deleted
- [x] **OCC-07**: Klaus can explain his own decisions — brain-direct `get_recent_decisions(days)` returns recent tick/occasion verdicts, triage reasoning, and outreach topics from `TickLogStore` + `OutreachLogStore` ("why didn't you message me yesterday?" gets a real answer)

### Write-Backs (Phase 34)

- [x] **WB-01**: Creating a workout calendar event (`is_workout=True`) best-effort writes a planned `TrainingLogStore` row (`planned=True`, `source="calendar"`) — never fails the calendar create. Live via `_training_calendar_writeback` behind `KLAUS_TRAINING_WRITEBACK_ENABLED=true`
- [x] **WB-02**: Moving or deleting a workout event updates reality symmetrically — move marks the old row `plan_status="moved"` and merges a new-date planned row; delete marks the row `plan_status="deleted"`
- [x] **WB-03**: When Amit says he did/moved/skipped a session in chat, Klaus logs it. Reframed by the v7 architecture: the reasoning now lives in the Claude live-agent skill calling the `log_training` MCP tool, not in a Cloud Run composer. Chat-created rows still merge idempotently with later Garmin/Hevy completion on the same `{date}_{slot}` doc
- [x] **WB-04**: The reasoning surfaces read a reconciled planned-vs-actual window instead of raw split-vs-log guesswork — `core/training_reality.py`, exposed as the read-only `get_training_reality` tool on both MCP endpoints and consumed by the live-agent, nightly and weekly skills in suite 7.3.0 (2026-08-15). The original `training_reality` gather was deleted with the cascade; this is a deterministic rebuild, not a restoration

### Hardening & Subtraction (Phase 35)

- [~] **HARD-01**: VOID. The fixtures were to be run by `scripts/eval_tick_brain.py` against the tick-brain, which no longer exists; the `evals/tick_brain/` tree was removed with it. The one durable behaviour behind these fixtures — moved-session no-re-ask — is now covered deterministically by `tests/test_training_reality.py` rather than by model evaluation
- [x] **HARD-02**: Dead-code sweep — `core/proactive_alerts.py` and the whole legacy generative runtime removed 2026-08-12/13; `evals/tick_brain/` removed; `.venv.py314.bak/` (266MB) deleted 2026-08-15; retired TickTick token file and revoked Google token backups deleted 2026-08-15. Remaining TickTick references are historical docstrings recording lineage, not live code. `scripts/check_claude_first_runtime.py` now enforces the sweep in CI
- [x] **HARD-03**: Chat-ingest and chat-export-ingest Cloud Scheduler jobs are paused and listed in `ops/policies/quarantine.json`. Superseded in spirit: the routes are 410 tombstones and the code is gone, so they are pending deletion at the 2026-08-20 audit rather than being resumable
- [~] **HARD-04**: VOID. The worker layer was retired outright in the Claude-first cutover, so there is no delegation volume left to measure and no v6.1 retirement decision to record
- [x] **HARD-05**: Docs + invariants updated — `AGENTS.md`, `docs/V7_ARCHITECTURE.md`, `docs/CLAUDE_FIRST_USE.md`, `docs/SELF.md` and `docs/DEPLOYMENT.md` describe the current contract. The Groq and directives-in-every-path invariants are void with the runtime that carried them

## Future Requirements (v6.1+)

### Judgment-Layer Visibility

- **VIS-01**: Hub page listing active standing directives with cancel buttons
- **VIS-02**: Hub view of recent tick/occasion decisions (reads the `get_recent_decisions` API)

### Ambient Inputs

- **AMB-01**: Real iOS location signal via Shortcut ping (HealthKit-sync pattern)
- **AMB-02**: Ambient-recall precision eval fixtures (if stale-memory injection shows up in practice)

### Architecture

- **ARCH-01**: Worker-layer retirement (executes the HARD-04 decision if delegation volume is low)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automatic memory decay/forgetting | Deliberate-only chosen — data volume doesn't justify tuning complexity (user decision 2026-07-17) |
| Directive default TTL | End-condition capture chosen — no auto-expiry of standing wishes (user decision 2026-07-17) |
| New plan-override store | Rejected in plan — planned rows in `TrainingLogStore` are the single source of truth |
| Batch API for offline crons | 50% off but low absolute savings; only if cost trends up |
| Behavior scripts / trigger checklists in prompts | Milestone philosophy — identity + values + full data, calibrated via directives + reactions |
| Email sending / WhatsApp outbound / multi-user / spend caps | Carried project exclusions (caps: tripwire alerts, never blocks) |
| Telegram mirror OFF | Precondition not met — physical-device push verification + mirror week (v5.0 deferred) must pass `get_push_health` first |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BRAIN-01 | Phase 30.5 | Complete |
| BRAIN-02 | Phase 30.5 | Complete |
| BRAIN-03 | Phase 30.5 | Complete |
| BRAIN-04 | Phase 30.5 | Complete |
| BRAIN-05 | Phase 30.5 | Complete |
| BRAIN-06 | Phase 30.5 | Complete |
| BRAIN-07 | Phase 30.5 | Complete |
| DIR-01 | Phase 31 | Pending |
| DIR-02 | Phase 31 | Pending |
| DIR-03 | Phase 31 | Pending |
| DIR-04 | Phase 31 | Pending |
| DIR-05 | Phase 31 | Complete |
| DIR-06 | Phase 31 | Pending |
| DIR-07 | Phase 31 | Complete |
| MEM-01 | Phase 32 | Complete |
| MEM-02 | Phase 32 | Complete |
| MEM-03 | Phase 32 | Complete |
| MEM-04 | Phase 32 | Complete |
| MEM-05 | Phase 32 | Complete |
| MEM-06 | Phase 32 | Complete |
| MEM-07 | Phase 32 | Complete |
| OCC-01 | Phase 33 | Complete |
| OCC-02 | Phase 33 | Complete |
| OCC-03 | Phase 33 | Complete |
| OCC-04 | Phase 33 | Complete |
| OCC-05 | Phase 33 | Complete |
| OCC-06 | Phase 33 | Complete |
| OCC-07 | Phase 33 | Complete |
| WB-01 | Phase 34 → v7 | Complete (v7) |
| WB-02 | Phase 34 → v7 | Complete (v7) |
| WB-03 | Phase 34 → v7 | Complete (v7, reframed) |
| WB-04 | Phase 34 → v7 | Complete (v7 rebuild) |
| HARD-01 | Phase 35 → v7 | Void — tick-brain retired |
| HARD-02 | Phase 35 → v7 | Complete (v7) |
| HARD-03 | Phase 35 → v7 | Complete (quarantined) |
| HARD-04 | Phase 35 → v7 | Void — worker retired |
| HARD-05 | Phase 35 → v7 | Complete (v7) |

**Coverage:**
- v6.0 requirements: 37 total
- Mapped to phases: 37/37 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-17*
*Last updated: 2026-07-17 after roadmap creation — 37/37 requirements mapped to Phases 30.5, 31, 32, 33, 34, 35 (100% coverage)*
