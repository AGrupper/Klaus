---
phase: 22
slug: expert-coaching-knowledge-d-13-release
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-05
---

# Phase 22 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Coaching-knowledge core + `read_coaching_guide` tool + D-13 fabrication-guard removal (Tier A/B contract).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| coaching-guide content → system prefix | Slim core injected verbatim into every brain system prompt (and cron compose prompts). | Author-controlled prose (committed, PR-reviewed) — no runtime user input |
| brain tool args → `read_coaching_guide(topic)` | `topic` is an LLM-supplied string; must resolve to an authored section anchor, never a filesystem path. | LLM-supplied slug string |
| brain ↔ worker tool partition | `read_coaching_guide` must stay brain-direct; worker must never gain it. | Tool-schema visibility |
| coaching slim core → cron compose | Briefing/alert/autonomous prompts interpolate the slim core to drive autonomous outbound messages. | Author-controlled prose |
| prompt contract → model output | Tier A/B contract is the ONLY mechanism preventing fabricated training/medical numbers after D-13 guard removal. | Model-generated numeric claims |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-22-01 | Tampering / Info Disclosure | `docs/COACHING_GUIDE.md` slim-core marker pair | mitigate | `core/main.py:800-810` — regex extracts only `SLIM_CORE_START…END`; missing markers → `""` + `logger.warning`. Markers present; 143 lines / 7709 chars (budget 350 / 15000). | closed |
| T-22-02 | Spoofing (prompt injection) | coaching-guide prose in system prefix | accept | `docs/COACHING_GUIDE.md` has zero `{…}` template vars; static prose loaded at startup from hardcoded path. No runtime user input interpolated. | closed |
| T-22-03 | Information Disclosure | `read_coaching_guide(topic)` anchors | mitigate | `core/tools.py:1388-1408` — regex matches only `<!-- SECTION: slug -->` anchors; `topic` never joined into a path. 10 authored slugs, no sensitive content. | closed |
| T-22-04 | Info Disclosure / Path Traversal | `_handle_read_coaching_guide(topic)` | mitigate | `core/tools.py:1385-1408` — `topic` normalized to slug, used only inside `re.escape(slug)` against authored anchors. `..`, `/`, absolute paths fail to match → error JSON. Test `test_handle_read_coaching_guide_unknown_topic` (`tests/test_tools.py:685`). | closed |
| T-22-05 | Elevation of Privilege | worker gaining `read_coaching_guide` | mitigate | `core/tools.py:61` in `SMART_AGENT_DIRECT_TOOLS`; `core/tools.py:915` in `WORKER_TOOL_SCHEMAS` exclusion. Test `test_read_coaching_guide_not_in_worker_schemas` (`tests/test_tools.py:643`). | closed |
| T-22-06 | Denial of Service | oversized slim-core injection every call | mitigate | `core/main.py:813-818` — `len(slim) > 10_000` warns. `tests/test_main_render_smart_system.py:510-522` size guard (`< 350 lines / < 15000 chars`) against real guide. | closed |
| T-22-07 | Tampering | missing/malformed guide file at runtime | accept | `core/main.py:793-810` — `OSError`/missing markers → `""` + warning; `render_smart_system:421` `getattr(..., "")` fallback. Graceful degrade. | closed |
| T-22-08 | Information Disclosure | unresolved `{coaching_guide}` literal leaking into outbound cron message | mitigate | `tests/test_main_render_smart_system.py:616-709` — `test_briefing_no_literal_placeholder` + `test_alert_no_literal_placeholder` assert no literal token survives and slim core present. Injection at `core/morning_briefing.py:298`, `core/proactive_alerts.py:389`. | closed |
| T-22-09 | DoS / cost | crons calling deep `read_coaching_guide` on every high-freq tick | mitigate | `prompts/morning_briefing.md:11` + `prompts/autonomous.md:11` — D-05 cost-bias steer ("only call if Sir asks 'why?' or a precise protocol isn't covered by the core"). Prompt-level, no hard block by design. | closed |
| T-22-10 | Tampering | missing orchestrator attribute if Plan 02 incomplete | accept | `core/main.py:224` — `_coaching_guide_content` set unconditionally in `__init__`; depends_on 22-02 wave gate enforces ordering; `getattr` fallback in render. | closed |
| T-22-11 | Spoofing / Repudiation (fabricated data) | D-13 guard removal opening path to invented training numbers | mitigate (HIGH) | `prompts/smart_agent.md:107-133` — full Tier A/B recency-windowed contract (14/7/2d + Garmin always-fresh; 3x upper bounds 42/21/6d; no-data fallback "I don't have a recent X logged, Sir"; staleness caveat). Old blanket guard confirmed **replaced, not just deleted** (grep: removed phrases absent), single atomic edit (commit 45b4d9c). Live SC-1 gate approved by Amit 2026-06-05, zero fabricated numbers. | closed |
| T-22-12 | Tampering | autonomous/silent plan rewrite under new critique posture | mitigate | `prompts/smart_agent.md:157-170` — critique posture forbids silent rewrites; `update_plan`/`update_training_profile` fire only on explicit confirmation (D-12); structural-only scope; once-per-conversation suppression. SC-4 live verify confirmed. | closed |
| T-22-13 | Spoofing (prompt injection) | coaching-guide content in system prefix steering behavior | accept | `prompts/smart_agent.md` contract block has no `{runtime_var}` interpolation; author-controlled static prose, PR-reviewed. | closed |
| T-22-SC | Tampering | npm/pip/cargo installs | n/a | No package installs across all four plans — stdlib `re`/`json`/`pathlib` only. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-22-1 | T-22-02 | Coaching-guide prose in system prefix is author-controlled, PR-reviewed, committed to repo. No runtime user data interpolated into the guide at any point in the injection chain. | Amit Grupper | 2026-06-05 |
| AR-22-2 | T-22-07 | Missing/malformed `COACHING_GUIDE.md` at runtime → loader returns `""` + warning. Coaching injection degrades gracefully; orchestrator does not crash. | Amit Grupper | 2026-06-05 |
| AR-22-3 | T-22-10 | Missing orchestrator attribute only possible if Plan 02 incomplete; depends_on 22-02 wave gate enforces ordering and `_coaching_guide_content` is set unconditionally, with `getattr(..., "")` belt-and-suspenders in render. | Amit Grupper | 2026-06-05 |
| AR-22-4 | T-22-13 | Coaching-guide content steering behavior is author-controlled and PR-reviewed; no untrusted runtime input interpolated into the Tier A/B contract or guide. | Amit Grupper | 2026-06-05 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-05 | 14 | 14 | 0 | gsd-security-auditor (sonnet) |

### Test Evidence

All coaching-guide security tests verified green in project venv:

- `tests/test_tools.py` — 7 coaching-guide tests: **7 passed**
- `tests/test_main_render_smart_system.py` — 9 coaching-guide / render tests: **9 passed**

| Test | Threat Covered |
|------|---------------|
| `test_load_coaching_guide_slim_missing_markers` | T-22-01 |
| `test_handle_read_coaching_guide_unknown_topic` | T-22-04 |
| `test_read_coaching_guide_not_in_worker_schemas` | T-22-05 |
| `test_load_coaching_guide_slim_size_guard` | T-22-06 |
| `test_briefing_no_literal_placeholder` | T-22-08 |
| `test_alert_no_literal_placeholder` | T-22-08 |
| `test_render_no_unresolved_placeholders_includes_coaching_guide` | T-22-08 |

### Unregistered Flags

None. All four SUMMARY.md `## Threat Flags` sections report no new attack surface. The Plan 03 `_get_orchestrator` import-source correction (`core.main` → `core.autonomous`) was an incorrect plan interface, not a new trust boundary — it prevents a runtime `ImportError` and carries no security implication.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-05
