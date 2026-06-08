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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Key Change |
|-----------|--------|------------|
| v4.0 | 5 (21–25) | Strict dependency-ordered phasing; pre-deploy review-fix sweep + three-source requirements cross-check at close |

### Cumulative Quality

| Milestone | Tests (suite) | Notable |
|-----------|---------------|---------|
| v4.0 | 1058 passing / 3 skipped | All 10 Phase-25 code-review findings fixed pre-deploy; 16/16 threats secured; no new runtime deps |

### Top Lessons (Verified Across Milestones)

1. Flip status artifacts at the moment of truth, not at milestone close — drift is cheap to avoid and expensive to reconcile.
2. Make critical guarantees (no-fabrication, closed sets) structural rather than prompt-/discipline-dependent.
