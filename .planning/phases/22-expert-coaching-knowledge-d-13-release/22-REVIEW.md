---
phase: 22-expert-coaching-knowledge-d-13-release
reviewed: 2026-06-05T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - core/main.py
  - core/tools.py
  - core/morning_briefing.py
  - core/proactive_alerts.py
  - tests/test_main_render_smart_system.py
  - tests/test_tools.py
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 22: Code Review Report

**Reviewed:** 2026-06-05
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Phase 22 adds a coaching-guide knowledge layer: a slim-core loader injected as a
stable cached prefix in `render_smart_system`, a brain-direct `read_coaching_guide`
tool with slug→anchor lookup, and compose-time `{coaching_guide}` injection into the
morning-briefing and proactive-alert cron paths.

The headline security concern — path traversal via the `topic` argument — is **clean**.
The handler never concatenates `topic` into a filesystem path; the file path is hardcoded
(`docs/COACHING_GUIDE.md`), and `topic` is normalized to a slug and used only inside an
`re.escape`-wrapped regex against authored `<!-- SECTION: slug -->` anchors. `..`, `/`,
and absolute paths simply fail to match and return error JSON. No traversal is possible.
The brain-direct/worker-exclusion partition is also correct and verified at all four
registration sites, with the worker prompt carrying no `{coaching_guide}` placeholder.

The defects found are not security holes but real correctness gaps: the two cron compose
functions catch only `OSError` while the new `_get_orchestrator()` call inside the same
`try` can raise `KeyError`/other exceptions; the fuzzy fallback in `read_coaching_guide`
can return a confidently-wrong section for a single-common-word topic; and the slim-core
size guard is warn-only with no enforcement, contradicting the test's hard limits.

## Warnings

### WR-01: Cron compose functions catch only `OSError`, but `_get_orchestrator()` in the same `try` can raise other exceptions

**File:** `core/morning_briefing.py:283-296`, `core/proactive_alerts.py:374-385`
**Issue:** Phase 22 moved `from core.autonomous import _get_orchestrator` and
`_get_orchestrator()._coaching_guide_content` *inside* the existing `try` block whose
sole handler is `except OSError`. Pre-Phase-22 the `try` body was only
`prompt_path.read_text(...)`, for which `OSError` was the complete failure set.
`_get_orchestrator()` constructs `AgentOrchestrator()` on first call, which executes
`os.environ["SMART_AGENT_BACKEND"]`, `os.environ["SMART_AGENT_MODEL"]`,
`os.environ["SMART_AGENT_API_KEY"]`, `os.environ["WORKER_AGENT_*"]` (all `KeyError` on
absence), plus LLMClient/Firestore construction. None of those raise `OSError`. If the
singleton is not already built (e.g. a cron fires on a fresh Cloud Run instance before the
webhook path warmed the singleton, or an env var is missing), `_compose_briefing` will
propagate an uncaught `KeyError` instead of degrading to `_plain_text_fallback`, and
`_compose_alert` will propagate instead of degrading to its inline fallback string. The
briefing/alert then fails hard rather than sending degraded output — the exact failure mode
the `except` clause was written to prevent.

In `proactive_alerts.py` the blast radius is larger: `_compose_alert` is called at
line 170 of `run_proactive_alerts` with no surrounding try, so an uncaught raise aborts the
whole alert send (and the `_mark_processed` dedup write never happens).

**Fix:** Broaden the handler so orchestrator-construction failures also fall through to the
fallback. Either widen the except, or isolate the orchestrator access:
```python
# core/morning_briefing.py _compose_briefing
try:
    from core.autonomous import _get_orchestrator
    coaching_guide_content = _get_orchestrator()._coaching_guide_content
except Exception:
    logger.warning("morning_briefing: coaching guide unavailable", exc_info=True)
    coaching_guide_content = ""
try:
    system_prompt = (
        prompt_path.read_text(encoding="utf-8")
        .replace("{coaching_guide}", coaching_guide_content)
        .replace("{today_date}", today_iso)
    )
except OSError:
    logger.warning("morning_briefing: prompt file missing — using fallback")
    return _plain_text_fallback(today_data, today_iso)
```
Apply the same split in `core/proactive_alerts.py:_compose_alert`. Note the existing tests
(`test_briefing_no_literal_placeholder`, `test_alert_no_literal_placeholder`) patch
`_get_orchestrator` to a `SimpleNamespace`, so they never exercise the construction-failure
path and give false confidence here.

### WR-02: Fuzzy fallback in `read_coaching_guide` returns a confidently-wrong section on single-common-word topics

**File:** `core/tools.py:1397-1407`
**Issue:** When the exact anchor match fails, the handler splits the slug on `-` and, for
each word, runs `<!-- SECTION: [^>]*WORD[^>]* -->` and returns the **first** section whose
anchor merely *contains* that word as a substring. Two problems:

1. Short/common words match unintended sections. A topic like `"runs"` or
   `"strength"` or `"intervals"` is fine, but the first word of a multi-word free-text
   topic drives the match. e.g. topic `"protein for top sets"` → slug
   `protein-for-top-sets` → exact fails → first word `protein` matches `protein-timing`,
   which may or may not be what the user wanted — but a topic like `"set my interval pace"`
   → slug `set-my-interval-pace` → word `set` substring-matches `top-set-strength` and
   returns the strength section for an interval question. The handler then returns
   `{"topic": slug, "content": <wrong section>}` with no signal that this is a low-confidence
   fuzzy hit, so the brain treats it as authoritative.
2. Substring (not word-boundary) matching widens the false-match surface: `[^>]*WORD[^>]*`
   matches `WORD` anywhere inside the slug, so `set` matches `top-**set**-strength`.

This is a correctness/quality defect, not a crash — the handler never raises — but it can
feed the coaching brain the wrong knowledge section, which for a D-13 "no fabrication /
grounded coaching" release is a meaningful quality regression.

**Fix:** (a) Match whole slug-words, not substrings, by anchoring the word between slug
delimiters; (b) skip stop-words / very short tokens; and (c) tag fuzzy hits so the caller
knows it was approximate:
```python
_STOP = {"the", "a", "for", "of", "to", "and", "my", "set", "run"}
for word in slug.split("-"):
    if len(word) < 4 or word in _STOP:
        continue
    fallback = _re.compile(
        r"<!-- SECTION: [a-z0-9-]*\b" + _re.escape(word) + r"\b[a-z0-9-]* -->(.*?)(?=<!-- SECTION:|$)",
        _re.DOTALL | _re.IGNORECASE,
    )
    fm = fallback.search(content)
    if fm:
        return json.dumps({"topic": slug, "matched": "fuzzy", "content": fm.group(1).strip()})
```
At minimum, add `"matched": "fuzzy"` to the payload so the brain can hedge.

### WR-03: Slim-core size guard is warn-only — contradicts the test's hard limits and does not enforce the cached-prefix budget

**File:** `core/main.py:812-819`
**Issue:** `_load_coaching_guide_slim` only *logs a warning* when `len(slim) > 10_000`,
then returns the full slim block regardless of size. The stated intent (D-04, Pitfall 2)
is that only a ~200-300 line / ~4000 char slim core is injected as a stable prefix into
**every** brain system prompt, every morning briefing, and every evening alert. If an editor
moves or deletes the `SLIM_CORE_END` marker, or the slim block grows, the loader silently
ships an oversized prefix into every LLM call. Meanwhile `test_load_coaching_guide_slim_size_guard`
asserts a hard `< 350 lines` / `< 15000 chars` ceiling — so the test enforces a contract the
production code does not. The guard threshold (`10_000`) and the test threshold (`15_000`)
also disagree, so a 12k-char slim core passes the test while the code logs a warning yet
still injects it.

**Fix:** Make the guard enforce, or align thresholds and document warn-only intent. If the
slim core exceeding the budget is a real problem, truncate or refuse:
```python
if len(slim) > 15_000:
    logger.error(
        "COACHING_GUIDE.md slim core is %d chars (>15000) — refusing oversized "
        "injection; check SLIM_CORE markers", len(slim),
    )
    return ""
```
If warn-only is genuinely intended, raise the warning threshold to match the 15k test ceiling
and add a comment stating the loader deliberately does not truncate.

### WR-04: `_handle_read_coaching_guide` reads `COACHING_GUIDE.md` from disk on every call, ignoring the already-loaded slim core, with no error catch beyond file-open

**File:** `core/tools.py:1366-1409`
**Issue:** The handler re-reads the entire `COACHING_GUIDE.md` (1000+ lines) from disk on
every invocation. That is acceptable for an on-demand deep lookup, but two robustness gaps
remain: (1) only the `read_text` call is wrapped in `try/except OSError` — the two `re.compile`
/ `search` passes run unguarded. A pathological `topic` cannot break `re.escape`, so this is
low-risk, but the broader `dispatch()` wrapper (`core/tools.py:1667`) is what actually saves it
from crashing, meaning this handler relies on the caller's safety net rather than its own.
(2) The exact-match regex `<!-- SECTION: slug -->(.*?)(?=<!-- SECTION:|$)` will also happily
match content that lives *before* the first section or inside the slim-core block if a slug
happens to collide — but since all authored anchors are distinct section markers this is latent,
not active. Flagging as a maintainability/robustness concern: the handler's contract ("never
raises") is only true because `dispatch()` catches everything; the docstring claims the handler
itself returns error JSON on failure, which is only true for the file-open path.

**Fix:** Either document that final-line safety depends on `dispatch()`'s blanket catch, or wrap
the regex/return in the handler's own `try/except Exception` returning structured error JSON, to
make the docstring's "never raises" guarantee self-contained and not caller-dependent.

## Info

### IN-01: `import re as _re` performed inside both `_load_coaching_guide_slim` and `_handle_read_coaching_guide` on every call

**File:** `core/main.py:788`, `core/tools.py:1377`
**Issue:** `re` is imported lazily inside the function bodies. `_load_coaching_guide_slim` runs
once at startup so it is harmless there, but `_handle_read_coaching_guide` re-imports `re` on
every tool call. `re` is a stdlib module (cached in `sys.modules`), so cost is negligible, but
it is inconsistent with the module already importing other stdlib at top level and adds noise.
**Fix:** Hoist `import re` to module top in both files (or rely on the existing top-level
imports), dropping the `_re` alias.

### IN-02: Fuzzy-fallback docstring promise vs. behavior drift

**File:** `core/tools.py:1370-1376`
**Issue:** The docstring says "Fuzzy fallback on partial word match," which undersells the
actual behavior (first-substring-wins across all sections, no confidence signal — see WR-02).
A reader trusting the docstring would not anticipate the wrong-section failure mode.
**Fix:** Update the docstring to describe the substring-first-match semantics and its
limitations, and reference the `matched: fuzzy` flag if WR-02 is adopted.

### IN-03: Duplicated compose-time injection block across the two cron files

**File:** `core/morning_briefing.py:284-293`, `core/proactive_alerts.py:375-383`
**Issue:** The `from core.autonomous import _get_orchestrator` →
`_get_orchestrator()._coaching_guide_content` → `.replace("{coaching_guide}", ...)` sequence is
copy-pasted verbatim into both compose functions. The WR-01 fix will have to be applied twice,
and any future change to how the slim core is fetched must be kept in sync manually.
**Fix:** Extract a tiny shared helper (e.g. `core/autonomous.get_slim_coaching_core() -> str`
that returns `_get_orchestrator()._coaching_guide_content` and swallows construction errors to
`""`) and call it from both compose paths.

---

_Reviewed: 2026-06-05_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
