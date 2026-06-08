---
id: phase-22-code-review-advisory
status: pending
type: chore
priority: low
created: 2026-06-05
source: phase-22 code review (22-REVIEW.md) — advisory warnings not fixed inline
---

# Phase 22 code-review advisory items (WR-02, WR-03)

WR-01 (cron compose `_get_orchestrator()` crash path) was fixed inline during
phase close. These two lower-value warnings were deferred:

## WR-02 — read_coaching_guide fuzzy fallback can return the wrong section

`_handle_read_coaching_guide` (`core/tools.py`) falls back to substring-matching a
single word of the requested slug and returns the first hit with no confidence
signal — e.g. the word `set` matches `top-set-strength`. For a D-13 grounded-coaching
release this can feed the brain a wrong section as authoritative.

Fix options: require the fuzzy match to be unambiguous (single candidate) or
sufficiently specific; otherwise return the `{"error": ...}` not-found JSON so the
brain falls back to the slim core rather than a mis-matched deep section.

## WR-03 — slim-core size guard: code warns at 10k, test asserts hard 15k/350 lines

`_load_coaching_guide_slim` (`core/main.py`) only logs a warning above 10k chars and
never enforces, while `test_load_coaching_guide_slim_size_guard` asserts a hard
15k-char / 350-line ceiling on the committed guide. Code and test enforce different
contracts. Align them: either raise/return-truncate in the loader at the test's
ceiling, or document that the test is the enforcing gate and the loader warning is
advisory-only.

## Info items (IN-01/02/03, optional)
- Handler "never raises" guarantee leans on `dispatch()`'s blanket catch rather than
  being self-contained.
- Per-call `import re` inside the handler (move to module top).
- Compose-time injection block is duplicated across morning_briefing.py and
  proactive_alerts.py — could be a shared helper.

Full report: `.planning/phases/22-expert-coaching-knowledge-d-13-release/22-REVIEW.md`

---

## Resolution (2026-06-08)

- **WR-02** (read_coaching_guide wrong-section) — FIXED in Phase 24: the fuzzy
  fallback now requires an unambiguous single-anchor match, else returns the
  not-found JSON (`core/tools.py:1558-1571`).
- **WR-03** (slim-core size-guard mismatch) — RESOLVED: the two-tier contract is now
  explicit in `_load_coaching_guide_slim` (`core/main.py`) — 10k advisory warning
  (no runtime truncation, which would drop coaching content mid-section) + 15k/350
  hard ceiling enforced at build time by `test_load_coaching_guide_slim_size_guard`.
- **IN-01/02/03** (optional micro-chores: per-call `import re`, duplicated compose-time
  injection helper) — left as documented optional polish; no behavioral impact.
