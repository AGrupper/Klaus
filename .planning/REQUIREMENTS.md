# Requirements: Klaus v6.0 — Klaus Becomes an Agent

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

- [ ] **OCC-01**: The nightly review runs as `occasion="nightly"` through the 3-layer cascade — fully skippable by judgment (silence = decision, recorded as `skipped_by_judgment`); total infra failure still sends the deterministic plain-text fallback (failure-skip ≠ judgment-skip)
- [ ] **OCC-02**: The morning briefing runs as `occasion="morning"` through the cascade — Garmin wake-up anchor and 10:15 cutoff kept; `structured` snapshot + `daily_note` written only on actual send (hub `/api/today` contract); skips recorded
- [ ] **OCC-03**: The Sunday weekly training review runs as `occasion="weekly_review"` through the cascade — the last legacy composer retired
- [ ] **OCC-04**: Occasions bypass the empty gate (an occasion always gets a free triage judgment) with short occasion-guidance prompts — no mandated sections, no scheduling scripts; OutreachLog topic keys `nightly:<date>` / `morning:<date>` / `weekly:<date>`, append still gated on send success (D-10)
- [ ] **OCC-05**: Layer 2 is agentic within a bounded tool-call budget; directive-gated proactive calendar writes check for an existing planned row / Training-calendar event for that date+slot before creating (idempotent under compose-retry)
- [ ] **OCC-06**: Rollout behind `OCCASION_CASCADE=1` for one deploy cycle with no Cloud Scheduler changes; after a 3-4 day observation window, legacy composers + `prompts/nightly_review.md` / `morning_briefing.md` / `weekly_training_review.md` + the flag are deleted
- [ ] **OCC-07**: Klaus can explain his own decisions — brain-direct `get_recent_decisions(days)` returns recent tick/occasion verdicts, triage reasoning, and outreach topics from `TickLogStore` + `OutreachLogStore` ("why didn't you message me yesterday?" gets a real answer)

### Write-Backs (Phase 34)

- [ ] **WB-01**: Creating a workout calendar event (`is_workout=True`) best-effort writes a planned `TrainingLogStore` row (`planned=True`, `source="calendar"`) — never fails the calendar create
- [ ] **WB-02**: Moving or deleting a workout event updates reality symmetrically — move merges a new-date row and marks the old one `skipped_reason="moved"`; delete removes/marks the planned row
- [ ] **WB-03**: When Amit says he did/moved/skipped a session in chat, Klaus logs it before replying ("X today instead of tomorrow" logs today AND notes the swap); chat-created planned rows merge idempotently with later Garmin/Hevy completion on the same `{date}_{slot}` doc
- [ ] **WB-04**: The weekly review and cascade read the shared `training_reality` window instead of raw split-vs-log guesswork

### Hardening & Subtraction (Phase 35)

- [ ] **HARD-01**: ≥6 new eval fixtures pass via `scripts/eval_tick_brain.py`: vacation suppression, directive-expiry resumption, moved-session no-re-ask, nightly judgment-skip, nightly fold, follow-up cancelled by directive
- [ ] **HARD-02**: Dead-code sweep — `core/proactive_alerts.py` + tests + route + prompt (~2,850 LOC), TickTick residue (script, env vars, token file, `ticktick_overdue`→`native_overdue` rename), `.venv.py314.bak/` (348MB), `.claude/worktrees/` residue (per runbook: mv out, never straight rm), stray root scripts, Google Fit scope constant, seed/backfill scripts archived
- [ ] **HARD-03**: Chat-ingest (04:00) and chat-export-ingest (04:30) Cloud Scheduler jobs paused — code kept, resumable anytime (Amit stopped uploading)
- [ ] **HARD-04**: Worker-layer verdict recorded — LLMUsage delegation volume measured post-Sonnet, retirement decision for v6.1 documented in PROJECT.md Key Decisions
- [ ] **HARD-05**: Docs + invariants updated (CLAUDE.md §3/§5/§6: directives-in-every-path invariant, Groq per-request budget invariant; TECHNICAL_PLAN; DEPLOYMENT: no new jobs/indexes) and phase-pinned tool-registration tests consolidated into one current-invariant test

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
| OCC-01 | Phase 33 | Pending |
| OCC-02 | Phase 33 | Pending |
| OCC-03 | Phase 33 | Pending |
| OCC-04 | Phase 33 | Pending |
| OCC-05 | Phase 33 | Pending |
| OCC-06 | Phase 33 | Pending |
| OCC-07 | Phase 33 | Pending |
| WB-01 | Phase 34 | Pending |
| WB-02 | Phase 34 | Pending |
| WB-03 | Phase 34 | Pending |
| WB-04 | Phase 34 | Pending |
| HARD-01 | Phase 35 | Pending |
| HARD-02 | Phase 35 | Pending |
| HARD-03 | Phase 35 | Pending |
| HARD-04 | Phase 35 | Pending |
| HARD-05 | Phase 35 | Pending |

**Coverage:**
- v6.0 requirements: 37 total
- Mapped to phases: 37/37 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-17*
*Last updated: 2026-07-17 after roadmap creation — 37/37 requirements mapped to Phases 30.5, 31, 32, 33, 34, 35 (100% coverage)*
