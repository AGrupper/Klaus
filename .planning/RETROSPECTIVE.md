# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v4.0 — Specific Training & Nutrition Coaching

**Shipped:** 2026-06-08
**Phases:** 5 (21–25) | **Plans:** 20 | **Timeline:** 4 days (2026-06-04 → 2026-06-08)

### What Was Built
- Living-plan ingestion: Amit's Hybrid Athlete blueprint as structured `UserProfileStore` fields, editable via the `update_plan` tool (PLAN-01/02/03).
- Expert coaching knowledge (`docs/COACHING_GUIDE.md` slim core + `read_coaching_guide`) and the D-13 no-fabrication guard released under a Tier A/B data-presence contract (COACH-01/02/06/07).
- Block + benchmark tracking: `BlockStore` (date-range `get_current`) + `BenchmarkStore` (5-facet closed set), block-end benchmark state machine behind an HRV/ACWR gate, all on the existing 21:30 cron (BLOCK-01/02/03).
- Strict coaching + nutrition accountability: `CoachingTopicStore` cross-cron dedup, macro/fueling-slot/supplement checks, derived session quality (COACH-03/04/05, NUTR-01/02/03, PROG-01/03/04).
- Deterministic goal projection: `core/projection.py` LSQ helper + `get_goal_projection` tool + dense Garmin pace history, surfaced in the Sunday weekly review (PROG-02).

### What Worked
- **Strict dependency-ordered phasing.** 21 (data) → 22 (knowledge) → 23 (stores) → 24 (integration) → 25 (projection) meant each phase consumed a stable contract from the last; the integration checker found 0 broken cross-phase wiring at close.
- **Closed-set invariants paid off.** The 5-facet `_BENCHMARK_FACETS` frozenset defined once and validated at every caller meant zero facet drift across P23/P24/P25 — the audit confirmed it.
- **Fail-open gather discipline.** Every cron gather block is independent try/except → degrade to None/[]; later phases extended the gathers (block #8 projection) without ever risking the send path.
- **Deterministic-by-construction trust surface.** Making the projection a pure function the brain only *frames* (never computes) made the anti-fabrication guarantee structural, not prompt-dependent.

### What Was Inefficient
- **Metadata hygiene drifted from reality.** REQUIREMENTS.md traceability + checkboxes showed Phase 24 reqs `Pending`/`[ ]` despite shipping+deploying; SUMMARY `requirements_completed` frontmatter was left empty on most plans; Phase 21 verification stayed `human_needed` after the live UAT passed. All reconciled at milestone close, but it made the audit noisier than the actual state.
- **Code-review warnings deferred mid-run, then caught at the gate.** Phase 25 shipped with 6 warnings + 4 info documented-not-fixed (WR-02 nondeterministic pace dedup was a real deterministic-contract violation). Cheaper to have fixed inline during execution than to batch them pre-deploy.
- **Subagent flakiness (carried from v3.0).** Background/foreground executors stalled on watchdog timeouts in earlier phases; recovery was inline orchestration.

### Patterns Established
- **Pre-deploy review-fix sweep.** Before the milestone deploy, fix every documented code-review finding in the code being shipped, each with a regression test — don't let "advisory" findings ride into prod.
- **Direction-normalized output fields.** For any metric where "better" flips by facet (pace vs strength), expose a normalized field (`behind_by`, positive = behind everywhere) so the LLM never has to recover sign from two fields.
- **Validated-literal SQL over `NOW()`** when a caller-supplied date exists: derive + `date.fromisoformat`-validate the cutoff in Python, embed only the ISO literal — keeps the query injection-free *and* testable/back-fillable.
- **Three-source requirements cross-check at close** (traceability table + VERIFICATION evidence + SUMMARY frontmatter) catches the metadata drift above.

### Key Lessons
1. **Update status artifacts at the moment of truth, not at close.** Checkboxes, traceability, verification status, and SUMMARY frontmatter should flip when the thing actually happens (deploy, live UAT) — batching reconciliation to milestone-close inflates apparent debt.
2. **Fix code-review findings inline during the phase.** Deferring them to a pre-deploy sweep works but is more expensive and risks shipping a known-wrong number on the exact trust surface the phase exists to protect.
3. **Make safety guarantees structural where possible.** A deterministic pure function beats a prompt instruction for "never fabricate"; a single closed-set frozenset beats five hand-kept literals.
4. **Per-day aggregation belongs in SQL.** Same-day nondeterminism (WR-02) and `LIMIT` truncation (IN-02) both vanish when the query groups by calendar day instead of capping raw rows.

### Cost Observations
- Model mix: predominantly Opus orchestration with Sonnet subagents (security auditor, integration checker, code reviewer/fixer).
- Notable: the dual-model production architecture (Gemini brain / DeepSeek worker / free Groq tick-brain) is unchanged; this milestone added no new runtime dependencies or cron jobs.

---

## Milestone: v5.0 — Klaus Hub

**Shipped:** 2026-07-09
**Phases:** 5 (26–30) | **Plans:** 39 | **Timeline:** ~24 days (2026-06-15 → 2026-07-09)

### What Was Built
- **Hub Shell (P26):** a same-origin React/TS/Vite PWA served by FastAPI, Google session auth on every `/api/*`, a `/api/today` timeline aggregator, and a hub↔Telegram shared-conversation chat on the Cloud Tasks full-CPU path (HUB-01..05, CHAT-01..04, TIME-01..05/07/08).
- **Native Tasks (P27):** `TaskStore`/`TaskListStore` with recurrence, NL quick-add, undo, and a Klaus tool swap that fully retired TickTick (TASK-01..07).
- **Habits & Supplements (P28):** `HabitStore` with DST-safe streaks, contribution-grid history, and autonomous-tick adherence nudges (HABIT-01..05, TIME-06).
- **Web Push (P29):** VAPID fan-out behind a chat-visibility gate, injectManifest SW + IndexedDB unread badge, and a runtime Telegram-mirror toggle for a gradual transition (PUSH-01..04).
- **Health Pages (P30):** training/nutrition/sleep-recovery visualizations on a zero-dependency inline-SVG chart toolkit reading existing stores (HLTH-01..03).

### What Worked
- **Shell-first, then parallel-independent features.** P26 established the auth + shell + serving contract; P27/28/29/30 each depended only on P26, not each other — the integration checker found all 5 cross-phase seams wired at close with 0 rework.
- **Reusing the Cloud Tasks full-CPU path for hub chat.** The v3.0 slow-reply lesson (agent turns must run inside a tracked request) was applied from the start — hub chat and Telegram share one path, avoiding a re-discovery of the background-task CPU throttle.
- **Zero-dependency inline-SVG charts.** Following the ContributionGrid precedent kept the bundle lean and gave full control over D-08 gap-honest rendering — no chart-lib lock-in.
- **Same-origin PWA.** Serving the SPA from the existing container (mount-last catch-all) meant no CORS, one deploy, one session cookie — and no existing route was shadowed.

### What Was Inefficient
- **Metadata hygiene drifted again — the exact v4.0 lesson repeated.** At close, nyquist VALIDATION flags on P27/28/29 were still `draft`/`false` despite all Wave-0 tests existing and passing; P27 verification was still `human_needed` after its UAT passed; SUMMARY `requirements_completed` frontmatter was empty across all 12 P27/P28 plans. All reconciled at close — but this is the second milestone running where status artifacts lagged reality.
- **Frontend has no CI coverage of the SPA/auth paths.** The first hub deploy surfaced 5 latent bugs (SPA 500, reload loop, sign-in gate, dropped Set-Cookie, input behind tab bar) because `frontend/dist` is absent from CI — the deployed URL must be smoked manually.
- **Responsive-display + iOS-Safari sheet traps bit repeatedly.** Inline `display` overriding Tailwind `md:hidden`, z-index vs the fixed tab bar, soft-keyboard tracking — each cost a UAT round across P27/P28.

### Patterns Established
- **Shell-first, then independent feature phases** for a multi-surface milestone: build the auth/serving/shell contract as phase 1, then fan out features that depend only on it.
- **Apply the tracked-request rule to every new entry path.** Any new agent-invoking route goes through Cloud Tasks → `/internal/process-*`, never a Starlette BackgroundTask.
- **Smoke the deployed URL for frontend phases.** Bundle-hash polling and unit tests don't catch SPA/auth/cookie integration; hit the live URL.

### Key Lessons
1. **Enforce "flip status at the moment of truth" mechanically, not by intention.** Two milestones have now reconciled the same nyquist/verification/frontmatter drift at close. A per-phase gate that fails when Wave-0 tests pass but the VALIDATION flag is still false would kill it at the source.
2. **Frontend needs its own CI lane.** Build `frontend/dist` in CI and add SPA/auth smoke tests, or accept that every frontend deploy needs a manual live smoke.
3. **The shared full-CPU path is now a load-bearing invariant.** Both surfaces depend on it; keep it a documented, tested contract.

### Cost Observations
- Model mix: Opus orchestration with a Sonnet subagent (integration checker at the milestone audit).
- Notable: first milestone to add a **frontend** (Node build stage) and a new **outbound channel** (Web Push / VAPID), plus four new Firestore stores (`TaskStore`, `HabitStore`, `PushSubscriptionStore`, `HubSettingsStore`); the dual-model runtime is unchanged.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Key Change |
|-----------|--------|------------|
| v4.0 | 5 (21–25) | Strict dependency-ordered phasing; pre-deploy review-fix sweep + three-source requirements cross-check at close |
| v5.0 | 5 (26–30) | Shell-first then parallel-independent features; first frontend (PWA) + outbound channel (Web Push); integration-checker seam audit at close |

### Cumulative Quality

| Milestone | Tests (suite) | Notable |
|-----------|---------------|---------|
| v4.0 | 1058 passing / 3 skipped | All 10 Phase-25 code-review findings fixed pre-deploy; 16/16 threats secured; no new runtime deps |
| v5.0 | 1775 backend + 160 frontend | 36/36 requirements; audit passed (5/5 integration seams); P27/28/29 nyquist validated at close; frontend still has no CI lane |

### Top Lessons (Verified Across Milestones)

1. Flip status artifacts at the moment of truth, not at milestone close — drift is cheap to avoid and expensive to reconcile. **(Repeated in v4.0 and v5.0 — now a candidate for a mechanical per-phase gate.)**
2. Make critical guarantees (no-fabrication, closed sets) structural rather than prompt-/discipline-dependent.
3. New entry paths that invoke the agent must run inside a tracked Cloud Tasks request, never a BackgroundTask (CPU throttle) — verified v3.0 (Telegram) and v5.0 (hub chat).
