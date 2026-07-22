---
phase: 31-standing-directives
verified: 2026-07-20T14:57:23Z
status: gaps_found
score: 5/7 must-haves verified
overrides_applied: 0
gaps:
  - truth: "When a directive contradicts a baked-in persona routine, Klaus records the answer as a refined directive with a superseded_by link on the old one (SC-5 / DIR-05 / D-16)"
    status: failed
    reason: >
      No chat-reachable path ever writes superseded_by. The set_standing_directive
      tool/handler exposes only text/expires_at/condition_text — no old_id/supersede
      param — and there is no supersede tool. StandingDirectiveStore.supersede() exists
      and is unit-tested but has ZERO production callers (orphaned). smart_agent.md
      instructs the brain to "call set_standing_directive again ... then
      cancel_standing_directive the old one (or note the supersession)", which produces
      status="cancelled" on the old doc and a fresh unlinked new doc — the
      superseded_by audit link the roadmap contract explicitly names is never produced.
    artifacts:
      - path: "core/tools.py:867-892, 2158-2210"
        issue: "set_standing_directive schema + handler have no supersede/old_id parameter; no supersede_standing_directive tool registered"
      - path: "memory/firestore_db.py:2000-2027"
        issue: "supersede() method is orphaned — only tests/test_firestore_db.py:603 calls it; no core/ path does"
      - path: "prompts/smart_agent.md:381"
        issue: "Persona-conflict rule resolves via new-set + cancel-old, which writes 'cancelled' (no superseded_by link)"
    missing:
      - "Expose supersession to the brain: either add an old_directive_id param to set_standing_directive whose handler calls store.supersede(old_id, new_id) after add(), or add a supersede_standing_directive tool"
      - "A test asserting a chat-driven persona-conflict capture writes superseded_by on the old doc (not just status='cancelled')"
  - truth: "A vetoed self-directive proposal is kept (status vetoed) and is never re-proposed (31-06 must_have / DIR-07 durable anti-lesson / D-13)"
    status: failed
    reason: >
      The reflection anti-lesson guard collects only directives with status=="vetoed"
      (core/reflection.py:517-521), but no production path ever writes "vetoed". The
      only user-facing undo surface, cancel_standing_directive, writes "cancelled"
      (tools.py:2247-2261 -> firestore_db.py:1993). There is no veto() method and no
      veto tool. Consequence: a self-directive Amit explicitly rejects becomes
      "cancelled", vetoed_texts stays empty forever, and the exact directive
      (origin='klaus_self', active immediately) can be re-proposed on the next
      reflection run — defeating the primary safety net the plan relied on to justify
      single-signal adaptation (D-10). The passing test
      test_reflection_vetoed_directive_is_not_re_proposed seeds a status="vetoed" doc
      that no production code can ever create, so it is green while the real scenario
      is unguarded. The prompt backstop (reflection.md:33) is soft and is handed data
      (active_directives) that by definition excludes vetoed entries.
    artifacts:
      - path: "core/reflection.py:514-531"
        issue: "vetoed_texts filters status=='vetoed', a status no code writes; guard is unreachable"
      - path: "memory/firestore_db.py:1975-1998"
        issue: "cancel() writes status='cancelled'; no veto()/'vetoed' writer exists anywhere"
      - path: "tests/test_reflection.py:650-683"
        issue: "Test seeds an unreachable status='vetoed' doc, so it passes without exercising the real cancel->re-propose path"
    missing:
      - "Make the guard reachable: either add a veto path that writes status='vetoed', OR treat cancelled klaus_self directives as the anti-lesson set (status=='cancelled' and origin=='klaus_self')"
      - "A test proving a directive rejected via cancel_standing_directive is NOT re-proposed on the next reflection run"
human_verification:
  - test: "State a lasting wish in chat (e.g. 'stop nagging me about training while I'm in France') and observe Klaus's ack"
    expected: "A one-line JARVIS-register ack echoing the wish + understood duration ('Standing order, Sir: no training nudges until you're back from France.')"
    why_human: "Ack wording is LLM-generated; only the capture machinery + prompt rule are code-verifiable"
  - test: "State a wish that conflicts with a baked-in persona routine and answer 'which wins?'"
    expected: "Klaus asks which wins in the same exchange, then keeps only the resolved directive"
    why_human: "Conflict-surfacing is prompt-driven; note that even when this works, no superseded_by link is written (see gap 1)"
---

# Phase 31: Standing Directives Verification Report

**Phase Goal:** Amit can state a lasting wish about Klaus's behavior once and have it honored everywhere, indefinitely or until it expires/is cancelled, with conflicts surfaced and Klaus able to learn new directives from how Amit reacts to his own outreach.
**Verified:** 2026-07-20T14:57:23Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Amit states a lasting wish in chat (incl. "I already told you…") → stored verbatim with origin + triggering-context quote + one-line ack (SC-1 / DIR-01) | ✓ VERIFIED | `set_standing_directive` tool at tools.py:867 stores `origin="user_chat"`, `context_quote=text` (2203-2209); STANDING DIRECTIVES + "I already told you" capture rule in smart_agent.md:353-364; 208 store/tool tests pass. Ack wording itself is behavioral (human-verify) |
| 2 | End-condition directives expire automatically; conditionless ones persist until cancel; "until when?" only when unsure (SC-2 / DIR-02) | ✓ VERIFIED | Store schema carries `expires_at`/`condition_text`/None (firestore_db.py:1912-1922); reflection judges event-based expiry via `expire()` (reflection.py:551-563); D-06 soft-ask in smart_agent.md; add-with-neither test asserts indefinite persistence |
| 3 | An active directive changes behavior everywhere — chat, tick triage Step-0 veto, Layer-2 compose, follow-up compose, interim crons, nightly (SC-3 / DIR-03) | ✓ VERIFIED | All 5+ injection sites wired: main.py:546 `{standing_directives}` (cache-safe, after training_profile before today_date); autonomous.py Step-0 triage (autonomous_triage.md:168) + Layer-2 (900) + follow-up (967); morning/weekly crons (05); nightly (nightly_review.py:267-279). `_is_empty_signals` correctly excludes directives (autonomous.py:220) |
| 4 | Amit can list and cancel standing directives from chat (SC-4 / DIR-04) | ✓ VERIFIED | `list_standing_directives` (include_history) + `cancel_standing_directive` brain-direct tools; registered in frozenset (83-85), worker-exclusion (1513-1515), _HANDLERS (3128-3130) |
| 5 | Persona conflict flagged, asked once "which wins", answer recorded as refined directive **with a `superseded_by` link on the old one** (SC-5 / DIR-05 / D-16) | ✗ FAILED | `superseded_by` is unreachable from chat: no supersede tool, `set_standing_directive` has no old_id param, `supersede()` is orphaned (only tests call it). Prompt resolves via new-set + cancel-old → old becomes `"cancelled"`, no link. See gap 1 |
| 6 | Nightly reflection reads full 24h window, pairs each outreach with a reaction, may propose self-directives with a one-line veto (SC-6 / DIR-06) | ✓ VERIFIED | reflection.py:178 reads `get_recent_window(user_id, hours=24)` (old `conv_store.get()` gone); OutreachLogStore.get_today read (419); reaction-pairing task (reflection.md:26-31); nightly one-line veto rendering (nightly_review.md:66-75) |
| 7 | A vetoed self-directive is kept (status vetoed) and never re-proposed — the D-13 durable anti-lesson that backs DIR-07's single-signal safety | ✗ FAILED | Guard reads `status=="vetoed"` but no code ever writes it; cancel writes `"cancelled"`. A rejected self-directive can be re-proposed verbatim next night. Passing test seeds an unreachable status. See gap 2 |

**Score:** 5/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `memory/firestore_db.py` StandingDirectiveStore | add/list_active/list_all/cancel/supersede/expire, read-cached, never hard-delete | ✓ VERIFIED | Full lifecycle at 1841-2051; `_cache_invalidate_prefix(("standing_directives",))` in all writes; cached `list_active`; no `.delete(` on directive docs. `supersede()` present but ORPHANED (no prod caller) |
| `memory/firestore_conversation.py` get_recent_window + ts | 24h window, ts stamping, legacy tolerance, cap | ⚠️ WIRED (latent flaw) | Present at 205-248; `_txn_append` stamps tz-aware `ts` (57). WR-02: `ts >= cutoff` at line 246 sits OUTSIDE the try/except — a valid-but-tz-naive ts would raise; production writer is always tz-aware so it won't trip today |
| `core/tools.py` 3 tools + formatter | brain-direct set/list/cancel + render_standing_directives_block | ✓ VERIFIED | Handlers 2158-2261; formatter 2264 (prose+json); 3-site registration confirmed |
| `core/main.py` {standing_directives} | cache-safe placeholder | ✓ VERIFIED | Line 546, between training_profile (545) and today_date (547) |
| `core/autonomous.py` gather + injection | context-only gather, Step-0 veto, both composes | ✓ VERIFIED | `_gather_standing_directives` (338); jobs dict (644); triage/compose wiring; empty-gate exclusion documented (220) |
| `core/morning_briefing.py` / `core/weekly_training_review.py` | directive gather + skip verdict + skipped_by_directive | ✓ VERIFIED | `_parse_briefing_skip` (612) / `_parse_review_skip` (519); `skipped_by_directive` status; no structured/daily_note write on skip. WR-01: skip parsers can silently truncate a non-skip message on a stray JSON fence |
| `core/reflection.py` learning loop | get_recent_window read + proposal/expiry/prune writes | ⚠️ WIRED (dead guard) | 24h read + isolated per-write try/except present; but D-13 vetoed guard is inert (gap 2) |
| `core/nightly_review.py` | raw block + directive_items both reach compose | ✓ VERIFIED | `standing_directives_block` (268) + `directive_items` (279) as distinct payload keys; nightly exempt from veto |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| StandingDirectiveStore writes | _READ_CACHE | `_cache_invalidate_prefix(("standing_directives",))` | ✓ WIRED | In add/cancel/supersede/expire |
| set/list/cancel tools | SMART_AGENT_DIRECT_TOOLS + worker-exclusion + _HANDLERS | frozenset + dispatch | ✓ WIRED | All 3 sites |
| render_smart_system | render_standing_directives_block | `{standing_directives}` .replace after {training_profile} | ✓ WIRED | Cache-safe position |
| _build_triage_prompt | render_standing_directives_block | lazy import | ✓ WIRED | json snapshot + prose block |
| _gather_day | get_recent_window | replaces conv_store.get | ✓ WIRED | reflection.py:178 |
| **persona conflict capture** | **superseded_by on old doc** | **supersede() / linked write** | **✗ NOT_WIRED** | supersede() orphaned; no chat path reaches it (gap 1) |
| **reflection anti-lesson guard** | **vetoed directive set** | **status=="vetoed"** | **✗ NOT_WIRED** | No writer of "vetoed"; cancel writes "cancelled" (gap 2) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Phase store/tool/window tests | `pytest test_firestore_db/conversation/tools/main -k standing/recent_window` | 208 passed | ✓ PASS |
| Autonomous/cron/reflection/nightly tests (per-file) | `pytest test_reflection.py -q` (isolated) | 17 passed | ✓ PASS |
| `supersede()` has any production caller | `grep -rn "\.supersede(" core/ memory/ interfaces/` | 0 callers (only the def + its own log line) | ✗ FAIL (orphaned) |
| Any code writes `status="vetoed"` | `grep -rn '"vetoed"' core/ memory/` | only schema docstring + the read comparison | ✗ FAIL (dead guard) |

Note: running the five behavior-test files in one pytest process shows one cross-file failure in `test_reflection.py`; each file passes in isolation (known grpc/protobuf test-isolation artifact in this repo — plans mandate per-file runs; full suite reportedly 2013 passed / 3 skipped). Not a code regression.

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| DIR-01 | 31-03 | ✓ SATISFIED | Verbatim capture tool + origin + context_quote + capture rule (incl. "I already told you") |
| DIR-02 | 31-01, 31-06 | ✓ SATISFIED | Hybrid expiry fields + judged nightly expiry (D-05/D-08) |
| DIR-03 | 31-03, 31-04, 31-05, 31-06 | ✓ SATISFIED | All injection sites (chat, tick Step-0 veto, Layer-2, follow-up, interim crons, nightly) |
| DIR-04 | 31-03 | ✓ SATISFIED | list/cancel brain-direct tools |
| DIR-05 | 31-01, 31-03 | ✗ BLOCKED | `superseded_by` link unreachable from chat; `supersede()` orphaned (gap 1) |
| DIR-06 | 31-02, 31-06 | ✓ SATISFIED | `get_recent_window` + reaction-pairing machinery |
| DIR-07 | 31-06 | ⚠️ PARTIAL | Self-directive proposals + one-line veto present, but the D-13 durable anti-lesson that backs it is inert — vetoed proposals can be re-proposed (gap 2) |

All 7 requirement IDs from PLAN frontmatter are accounted for. No orphaned requirements (REQUIREMENTS.md maps exactly DIR-01..07 to Phase 31).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| core/reflection.py | 514-531 | Guard keyed on a status (`"vetoed"`) no code writes — dead branch | 🛑 Blocker | D-13 anti-lesson never fires; rejected self-directives re-proposed |
| memory/firestore_db.py | 2000-2027 | `supersede()` orphaned (no production caller) | 🛑 Blocker | DIR-05 `superseded_by` audit link never produced |
| memory/firestore_conversation.py | 246 | tz-aware/naive comparison outside try/except | ⚠️ Warning | Latent; would drop the whole night's window on a naive ts (not produced today) |
| core/morning_briefing.py / core/weekly_training_review.py | 375-401 / 519-543 | Skip-parser truncates non-skip message at a stray ```json fence | ⚠️ Warning | Silent clipping of a briefing/review if LLM emits mid-body JSON |
| core/tools.py | 2158-2210 | Directive capture has no server-side provenance guard | ⚠️ Warning (accepted convention) | Prompt-only injection defense; blast radius = durable outreach suppression |

### Human Verification Required

Behavioral (LLM-driven) items — machinery is code-verified above, but final voice/judgment needs a human. These do NOT change the gaps_found status (blockers take priority):

1. **Capture ack voice** — State a wish in chat; expect a one-line JARVIS-register ack echoing wish + duration.
2. **Persona-conflict flow** — State a wish that conflicts with a persona routine; expect Klaus to ask "which wins?" in the same exchange. (Even when this works, gap 1 means no `superseded_by` link is written.)

### Gaps Summary

Two BLOCKERs prevent the phase goal from being fully achieved. Both are Level-3 wiring failures — the store method or guard exists and is unit-tested, but nothing production-reachable connects to it:

**Gap 1 (DIR-05 / SC-5 — superseded_by).** The roadmap contract explicitly requires persona-conflict resolution to record "a `superseded_by` link on the old one." The `supersede()` method exists and passes its own test, but no brain tool or handler ever calls it. The chat path is new-set + cancel-old, which writes `status="cancelled"` and produces no link. The conflict IS surfaced (the goal's "conflicts surfaced" clause is behaviorally met via the prompt), but the specific durable audit link that distinguishes DIR-05 from a plain cancel-and-recreate is unreachable.

**Gap 2 (DIR-07 / D-13 — vetoed anti-lesson, matches REVIEW CR-01).** Independently confirmed. The reflection guard filters on `status=="vetoed"`, a status no code path writes; the only undo surface (`cancel_standing_directive`) writes `"cancelled"`. A self-directive Amit rejects can therefore be re-proposed verbatim — active immediately — on the next reflection run. This directly compromises the phase goal's "learn new directives from how Amit reacts" clause: the single-signal adaptation (D-10) was justified by the veto being a durable anti-lesson, and that anti-lesson is inert. The green test seeds an unreachable state, masking the real cancel→re-propose scenario.

Neither gap is deferred: Phase 35 (Hardening & Subtraction) covers eval fixtures, cleanup, and docs — not these fixes.

---

_Verified: 2026-07-20T14:57:23Z_
_Verifier: Claude (gsd-verifier)_
