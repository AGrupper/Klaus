---
phase: 18
reviewed_date: 2026-05-23
files_reviewed: 7
total_findings: 11
critical: 0
high: 1
medium: 5
low: 5
status: issues
---

# Phase 18 — Code Review (autonomous-engine)

**Scope:** `core/autonomous.py` (new), `scripts/eval_tick_brain.py` (new), Phase 18 deltas in `memory/firestore_db.py`, `memory/firestore_conversation.py`, `core/tick_brain.py`, `core/tools.py`, `core/main.py`, `interfaces/web_server.py`, `core/heartbeat.py`. Depth: standard with cross-file checks on the autonomous tick path.

**Bottom line:** the 3-layer pipeline is well-defended (OIDC at the route, sentinel detection, per-source isolation, success-gated `outreach_log` writes, D-14 force-fire, render-before-loop). One contract drift between docstring and behavior, plus a handful of cleanup items. No security holes; no critical bugs.

## Findings

### High

#### H-1 — `run_autonomous_tick` docstring says follow-ups skip tick-brain, but Layer 1 still runs after follow-up firing
**File:** `core/autonomous.py:725-732` (also module docstring `:6-22` and `:695`).
**Category:** Correctness / contract.
**Description:** Module docstring and `run_autonomous_tick` step list both say D-13 "skips tick-brain" for follow-ups. The code does skip tick-brain for the *follow-up compose* (Layer 2 only), but after firing follow-ups the function **falls through** to Layer 1 triage on the same tick (the inline comment confirms this is intentional). A reader who trusts the docstring will think "if `due_followups` is non-empty, the tick exits after the follow-up loop" — wrong. This will eventually cause a double-send (one follow-up + one triage outreach) that surprises the user and burns Groq budget twice per tick.
**Fix:** Either (a) make the docstring/comments match the code ("follow-up firing does NOT preclude same-tick triage; both paths can fire on one tick"), or (b) actually `return` after the follow-up loop. (a) seems intentional — adjust the docstring.

### Medium

#### M-1 — `_get_orchestrator()` singleton has a TOCTOU race
**File:** `core/autonomous.py:390-407`.
**Category:** Bug (low-likelihood concurrency).
**Description:** Cloud Run instance can serve concurrent requests (`--concurrency` not pinned in `.github/workflows/deploy.yml`). Two coincident `/cron/autonomous-tick` calls (or one cron + one webhook touching `core.main` lazily) could both pass `if _orchestrator_singleton is None` and construct two `AgentOrchestrator()` instances. The second one wins and gets stored, but the first is leaked with its own `SelfStateStore` Firestore client and 3 LLMClients. Not data-corrupting (orchestrator has no mutable shared state beyond what `SelfStateStore` already handles), but wasteful and confusing if it ever shows up in logs.
**Fix:** Wrap with `threading.Lock`:
```python
_orch_lock = threading.Lock()
def _get_orchestrator():
    global _orchestrator_singleton
    if _orchestrator_singleton is None:
        with _orch_lock:
            if _orchestrator_singleton is None:
                from core.main import AgentOrchestrator
                _orchestrator_singleton = AgentOrchestrator()
    return _orchestrator_singleton
```

#### M-2 — `_compose_followup` parses `followup["due_at"]` without guarding `None` / `Z` suffix
**File:** `core/autonomous.py:645`.
**Category:** Bug.
**Description:** `original_due = datetime.fromisoformat(followup.get("due_at"))`. If `due_at` is missing (`None`) or written by an older path with a `Z` suffix, this raises (`TypeError` for `None`; `ValueError` for `Z` on Python < 3.11 — Python 3.11 in the Dockerfile is fine *today*). The exception is caught by the outer `try`, so the follow-up is marked `"failed"` and silently skipped — but a misformed doc is then never deferred and will keep re-firing every tick until it's cancelled by hand. Doc shape is enforced inside `FollowupStore.add` (writes ISO from `astimezone(utc).isoformat()`), so this is defensive only.
**Fix:** Mirror `gather_situation`'s `s_raw.replace("Z", "+00:00")` trick and fall back to "defer by 1 hour from now" if the stored timestamp is unparseable.

#### M-3 — `gather_situation` silently treats Firestore/Calendar outage as "empty" → tick is suppressed
**File:** `core/autonomous.py:174-305`.
**Category:** Bug / observability.
**Description:** Each source's `except Exception` keeps the sentinel (`[]`, `None`, …). If Firestore (or Calendar API) is down, all signal sources fall back to `[]` → `_is_empty_signals` returns `True` → tick returns `skipped: "empty"`. The user sees no outreach AND no error; the heartbeat liveness ledger records `ok=True` because `run_autonomous_tick` returned normally. The 1h staleness check on `autonomous-tick` (heartbeat.py) won't catch this — the cron is firing, it's just degraded.
**Fix:** Add a `gathered["source_errors"]: list[str]` and append the source name on each `except`; downgrade `empty` to `False` if any source erred (or at minimum log `WARNING "autonomous: degraded gather, %d sources failed"` with the list, and surface it in `decision["trail"]`).

#### M-4 — `_handle_cancel_followup(id: str)` shadows the Python builtin `id`
**File:** `core/tools.py:1321-1333`.
**Category:** Quality (CODING_STANDARDS.md §3 "Be highly descriptive").
**Description:** Function parameter named `id` shadows `builtins.id`. Linter (ruff A002) flags this; the tool schema field is also literally `"id"` which constrains the lambda dispatch (`**args` keyword expansion).
**Fix:** Rename the schema property + handler parameter to `followup_id` (must change in three places: `TOOL_SCHEMAS` schema for `cancel_followup`, the handler signature, and the prompts/smart_agent.md advertised arg name).

#### M-5 — `_SMART_LOOP_ERROR_SENTINELS` is fragile string-match — drifts silently if `core/main.py` copy changes
**File:** `core/autonomous.py:47-49` referencing `core/main.py:417, 422`.
**Category:** Bug-risk (coupling).
**Description:** The Layer-2 failure detection (BLOCKER 3) keys on the literal substring `"I'm afraid I encountered a connectivity"`. If anyone edits the canned message in `core/main.py:417` or `:422` (e.g. switches to "Sorry, the connection dropped"), Layer 2's sentinel detection silently breaks — the broken message ships to Telegram as the final answer (D-19 fallback never engages). There is no compile-time check, no test of the actual string from main.py.
**Fix:** Export the constant from `core/main.py` (`_CONNECTIVITY_ERROR_TEXT = "I'm afraid I encountered..."`) and have both `main.py` and `autonomous.py` reference it. Add a unit test that imports both and asserts the substring containment.

### Low

#### L-1 — `core/autonomous.py` is 825 lines — past the comfortable single-file limit
**File:** `core/autonomous.py` (whole file).
**Category:** Quality.
**Description:** Mixes 3 concerns: Layer-0 gather, Layer-2 compose, executor orchestration. The single-file constraint isn't a defect (cohesion is reasonable), but splitting `gather_situation` + `_calendar_has_gap_or_overload` into `core/autonomous_gather.py` would drop the orchestrator to ~500 LOC and unblock future Layer-0 source additions without churning the orchestrator.
**Fix:** Defer; split when the next Layer-0 source is added.

#### L-2 — `_synthesize_topic_key` produces unstable slugs from titles
**File:** `core/autonomous.py:308-337`.
**Category:** Quality.
**Description:** The fallback slug is computed from `title.lower()` → 30 char trim. Two overdue tasks with the same 30-char prefix produce identical `topic_key`s, so the second one is silently suppressed by D-06 dedup. Real-world TickTick titles usually diverge in the first 30 chars, so low impact, but the algorithm depends on title uniqueness without saying so.
**Fix:** Append a short hash of the task id (`f"{slug}-{task_id[:6]}"`) for collision-resistance.

#### L-3 — `_TICK_TOTAL_PER_DAY = 43` hard-coded; will silently lie if cron schedule changes
**File:** `core/autonomous.py:39`.
**Category:** Quality.
**Description:** If the Cloud Scheduler cron is changed (e.g. `*/15` instead of `*/20`), the prompt and `tick_index`/`tick_total` math will be wrong until someone updates this constant. The schedule lives in deployment docs and Cloud Scheduler config, not here.
**Fix:** Derive from `now`'s position in the day window, or document the cron contract in a comment at the constant.

#### L-4 — Logger inconsistency: `logger.warning` vs `logger.error` for similar failures
**File:** `core/autonomous.py:606, 617, 634, 653, 681, 743, 776, 792`.
**Category:** Quality / observability.
**Description:** `send_and_inject` failure (line 606, 792) uses `logger.error`; `mark_done` failure (617) uses `logger.warning`; `defer` failure (653) uses `logger.error`. The pattern is "side-effect failures = error, bookkeeping failures = warning" — mostly consistent, but `outreach_log append failed` (line 818) is warning despite being a side-effect-class failure (it just happens after the user-visible side-effect succeeded). Worth a comment explaining the convention so the next contributor doesn't reshuffle.
**Fix:** Add a top-of-file comment: "warning = bookkeeping failure, send already happened or won't happen; error = the call that mattered failed".

#### L-5 — `_compose_followup_layer2` snapshot drops `due_followups` & most context vs Layer 2 main compose
**File:** `core/autonomous.py:531-534`.
**Category:** Quality.
**Description:** Compose for a follow-up only shows the LLM `calendar` + `ticktick_overdue` — drops `unread_email_count`, `hours_since_contact`, `due_followups` (which would be recursive but at least the count would help). Layer 2's "is the moment wrong?" judgment for the defer/send decision is therefore working on less info than triage Layer 1. Probably fine for v1 but worth a TODO.
**Fix:** Add `unread_email_count` and `hours_since_contact` to the snap; intentionally exclude `due_followups` to avoid recursion.

## Architecture invariants check (vs CLAUDE.md + memory)

- GCP/Pinecone resource casing lowercase (`klaus-…`): **yes** — no `Klaus-` literal introduced in new code.
- `load_dotenv(override=True)` used on every new dotenv call: **yes** — `scripts/eval_tick_brain.py:321` uses `override=True`.
- No Vertex AI calls introduced (embeddings via AI Studio): **yes** — no `vertex`/`Vertex` import.
- Tick-brain backward compat: heartbeat still calls `think(prompt)` with no kwargs → defaults to `system_override=None` → preserves `purpose='tick'` / `tick_fallback`: **yes** (`core/tick_brain.py:128, 131`).
- `OutreachLogStore.append` gated on send success (D-10): **yes** — confirmed at `core/autonomous.py:789-816` (only reached after `send_and_inject` returns without exception); same gating in follow-up path `:598-637`.
- OIDC enforcement on `/cron/autonomous-tick`: **yes** — `_verify_cron_request` runs first (no bypass other than `CRON_DEV_BYPASS=true` env, which is documented and dev-only).
- `_handle_schedule_followup` catches `ImportError` on dateutil: **yes** (WARNING 7 fix verified at `core/tools.py:1280-1282`).
- `render_smart_system` substitutes all 4 placeholders: **yes** — `{self_md}`, `{self_state}`, `{journal_digest}`, `{today_date}`. `prompts/autonomous.md` placeholders `{situation_snapshot_summary}`, `{tick_brain_draft}`, `{tick_brain_reason}` are *documentation of the user message format*, not template variables — verified by reading the prompt body.

## Test coverage observations

- `_get_orchestrator()` singleton has no concurrency test — see M-1.
- `_SMART_LOOP_ERROR_SENTINELS` is not tested against the actual string in `core/main.py` — see M-5 (suggested test: `assert any(s in main._CONNECTIVITY_ERROR_TEXT for s in _SMART_LOOP_ERROR_SENTINELS)`).
- `gather_situation` per-source failure isolation appears well-mocked, but no test asserts that "all sources failing" does NOT silently mark the tick `empty` (M-3).
- `_compose_followup` "due_at unparseable" path (M-2) — no test fixture exercises a malformed timestamp.

## Recommendations

1. **Land now:** Fix H-1 docstring (5-min comment edit). It's the only finding that could mislead a future contributor into shipping a regression.
2. **Land in the next housekeeping commit:** M-1 (threading.Lock around singleton), M-4 (`id` → `followup_id`), M-5 (extract sentinel constant + import-time test).
3. **Defer to Phase 19 hardening sprint:** M-2 (`due_at` parse defense), M-3 (degraded-gather observability), L-1 (file split), L-2 (slug collision-resistance), L-3 (derive `tick_total`), L-4 (logger convention comment), L-5 (richer follow-up snapshot).
4. **No critical or high-severity security findings** — OIDC posture, success-gated writes, ImportError defense, sentinel-return detection are all in place.

---

_Reviewed: 2026-05-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
