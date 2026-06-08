---
phase: 25
slug: progress-projection-benchmark-trend-reporting
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-08
---

# Phase 25 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register authored at plan time (3 PLAN `<threat_model>` blocks); auditor verified mitigations against implementation.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| caller → project_goal_progress | facet + today_iso strings arrive from a tool handler (LLM-influenced) or a cron (server-controlled) | facet key, ISO date, history list |
| brain (LLM) → get_goal_projection handler | facet argument chosen by the LLM, may be malformed/out-of-set | facet key |
| handler/gather → Firestore (BenchmarkStore / UserProfileStore) | read-only; reuses existing credentials | benchmark history, dated goals |
| handler/gather → Postgres (activities, threshold_pace dense path) | read-only; SQL is hardcoded literals + server-side NOW() only | run duration/distance rows |
| Cloud Scheduler → run_weekly_review | server-controlled cron; facet loop is a hardcoded literal | none (no user input) |
| review/handler output → Telegram | deterministic numbers framed by the brain, sent via send_and_inject | projection figures |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-25-01 | Tampering | project_goal_progress(today_iso) | mitigate | Function body in `try/except`; `date.fromisoformat(today_iso)` (projection.py:271) inside try → malformed date returns no_data (projection.py:317–332) | closed |
| T-25-02 | Tampering | _linear_project denominator | mitigate | `slope = num / den if den != 0 else 0.0` (projection.py:118) + same-date dedup (projection.py:210–218) | closed |
| T-25-03 | Information Disclosure | projected_value fabrication | mitigate | n==0 → `projected_value=None`, `confidence="no_data"` (projection.py:225–237); value from deterministic LSQ only (projection.py:274) | closed |
| T-25-04 | Tampering | facet not in FACET_DIRECTION | accept | Inner layer; handler validates against `_BENCHMARK_FACETS` first. Unmapped facet → `FACET_DIRECTION.get(facet, True)` default, no target, no store access (pure module) | closed |
| T-25-05 | Tampering | _handle_get_goal_projection(facet) | mitigate | `if facet not in _BENCHMARK_FACETS: return json.dumps({"error":...})` before any store access (tools.py:1837–1841) | closed |
| T-25-06 | Information Disclosure | dated_goals JSON serialization | mitigate | `_jsonsafe_doc(profiles.load())` (tools.py:1850) strips DatetimeWithNanoseconds | closed |
| T-25-07 | Information Disclosure | output number to Telegram | mitigate | Handler returns `project_goal_progress` dict verbatim (tools.py:1863–1864); brain frames, never recomputes (smart_agent.md:192–195) | closed |
| T-25-08 | Elevation of Privilege | worker calling the tool | mitigate | In `WORKER_TOOL_SCHEMAS` exclusion set (tools.py:1075–1076) + `SMART_AGENT_DIRECT_TOOLS` (tools.py:70) | closed |
| T-25-09 | Tampering | gather block #8 facet loop | mitigate | Hardcoded 5-facet list literal (weekly_training_review.py:259); no LLM/user input reaches the loop | closed |
| T-25-10 | Denial of Service | projection gather failure blocks cron | mitigate | Block #8 `try/except → projections={}` (weekly_training_review.py:249–271); pace fetch fails open to `[]`; `send_and_inject` unconditional (line 410) | closed |
| T-25-11 | Information Disclosure | fabricated convergence in review | mitigate | Numbers only from deterministic dict (weekly_training_review.py:267); 0-point → "no measured data" (weekly_training_review.md:37) | closed |
| T-25-12 | Repudiation | duplicate same-day nag across crons | mitigate | `structural-critique:projection:<facet>` written via `add_topic` only after `send_and_inject` succeeds (weekly_training_review.py:410 → 426) | closed |
| T-25-13 | Tampering | fetch_dense_pace_history SQL | mitigate | Window cutoff derived from `today_iso` and validated via `date.fromisoformat` before embedding — only a self-computed ISO date literal (digits + hyphens) reaches the SQL; a malformed/injection `today_iso` raises → caught → `[]` (regression test `test_malformed_today_iso_fails_open`). `isinstance(rows, list)` guard fails open to `[]`. (Post-review: NOW() replaced by validated cutoff per IN-01; injection surface unchanged — no LLM/user input) | closed |
| T-25-14 | Tampering | handler today_iso (deadline arithmetic) | mitigate | `datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()` (tools.py:1843–1847) — never `date.today()` (UTC) | closed |
| T-25-15 | Tampering | threshold_pace dense pace unit error | mitigate | Pace from `AVG(duration_sec / distance_m * 1000)` grouped per day (pace_history.py); ambiguous `avg_pace` column never read (only a warning comment) | closed |
| T-25-SC | Tampering | npm/pip/cargo installs | accept | No packages installed; projection.py stdlib-only; pace_history.py reuses existing `mcp_tools.database_tool` — supply-chain delta zero | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-25-01 | T-25-04 | Unmapped facet reaching `project_goal_progress` is the inner layer only. The tool handler (T-25-05) validates against `_BENCHMARK_FACETS` before calling; the Sunday cron path uses a hardcoded facet literal (T-25-09). An unmapped facet resolves to no target and returns `no_data` — no store access, no crash. | Amit Grupper | 2026-06-08 |
| AR-25-02 | T-25-SC | No packages installed this phase. `core/projection.py` is stdlib-only; `core/pace_history.py` reuses the existing `mcp_tools.database_tool` already in the dependency tree. Supply-chain surface delta is zero. | Amit Grupper | 2026-06-08 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-08 | 16 | 16 | 0 | gsd-security-auditor (claude-sonnet-4-6) |

**Unregistered flags:** None. All three SUMMARY.md `## Threat Flags` sections report no new attack surface — no new network endpoints, auth paths, or schema changes.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-08
