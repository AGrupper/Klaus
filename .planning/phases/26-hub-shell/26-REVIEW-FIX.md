---
phase: 26-hub-shell
fixed_at: 2026-06-16T14:42:50Z
review_path: .planning/phases/26-hub-shell/26-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 7
skipped: 4
status: partial
---

# Phase 26: Code Review Fix Report

**Fixed at:** 2026-06-16T14:42:50Z
**Source review:** .planning/phases/26-hub-shell/26-REVIEW.md
**Iteration:** 1
**Fix scope:** critical_warning (Critical + Warning; Info findings IN-01..05 excluded — re-run with `--fix --all` to include them)

**Summary:**
- Findings in scope: 11 (4 Critical + 7 Warning)
- Fixed: 7 (all warnings, this run)
- Skipped: 4 (all criticals — already resolved in a prior session)

## Fixed Issues

### WR-01: `useUnread` reads `localStorage` on every render and `markAllSeen` captures a stale `messageCount`
**Files modified:** `frontend/src/hooks/useUnread.ts`
**Commit:** `4c17e9b`
**Applied fix:** Stabilized `markAllSeen` identity and read the latest message count via a ref so the callback no longer closes over a stale `messageCount`; avoids redundant `localStorage` reads on every render.

### WR-02: Assistant/server messages render the green "sent" checkmark intended only for the user's own optimistic state
**Files modified:** `frontend/src/components/chat/MessageBubble.tsx`
**Commit:** `b344b5b`
**Applied fix:** `StatusIcon` no longer treats a missing `status` field as `sent`. Historical user messages loaded from `/api/chat/messages` (which carry no client-only `status`) now render nothing instead of a misleading green delivery check; the checkmark shows only for this-session optimistic `sent` state.

### WR-03: `MealItem` type omits `slot_time`, and the server emits a field with no client contract
**Files modified:** `interfaces/web_server.py`
**Commit:** `2f8b8c7`
**Applied fix:** Dropped the `slot_time` field from the `/api/today` meal payload entirely. The client contract (`today.ts` `MealItem`) only declares `slot_label` + macros. This also *strengthens* the CLAUDE.md §6 eating-time invariant (T-26-04-03 / T-26-07-01) — the HH:MM slot identifier is no longer on the wire and cannot be re-framed as an eating time.

### WR-04: `int(request_json.get("user_id", 0))` in the hub worker can silently process a turn under user_id 0
**Files modified:** `interfaces/web_server.py`
**Commit:** `902de65`
**Applied fix:** `/internal/process-hub-message` now rejects a missing/zero/unparseable `user_id` (fails loudly) instead of defaulting to `0` and writing a turn into a phantom conversation document. Closes the latent correctness trap behind the OIDC gate.

### WR-05: Empty assistant reply from the orchestrator is appended verbatim, leaving the UI stuck "thinking"
**Files modified:** `core/main.py`
**Commit:** `ab8a6b9`
**Status:** fixed: **requires human verification**
**Applied fix:** `AgentOrchestrator.handle_message` now guards against an empty/whitespace-only `response_text` (e.g. an LLM failure path yielding `""`), logs a WARNING, and substitutes a short apology string before persisting. Prevents the hub UI from rendering a blank bubble with no retry affordance. **Human-verify:** this is a behavioral change on the shared Telegram + hub path — confirm the empty-reply detection and fallback semantics against real LLM-failure traces.

### WR-06: `_resolve_hub_user_id` runs a Firestore read on every `/api/chat` and `/api/chat/messages` call with no caching
**Files modified:** `interfaces/web_server.py`
**Commit:** `e9dd33f`
**Applied fix:** Memoized `_resolve_hub_user_id` for the process lifetime so the resolved hub user id is not re-read from Firestore on every chat poll; eliminates a per-request Firestore round-trip on the 2.5s polling path.

### WR-07: `SignInPage` `handleCredential` is reassigned to `window.handleGisCredential` each render but the GIS `initialize` callback captures the first closure
**Files modified:** `frontend/src/components/auth/SignInPage.tsx`
**Commit:** `aa46200`
**Applied fix:** Stabilized `handleCredential` with `useCallback` so the GIS `initialize` callback and the `window` handle reference the same current closure, removing the stale-closure mismatch on re-render.

## Skipped Issues

### CR-01: `/api/today` field-name contract break
**File:** `interfaces/web_server.py`
**Reason:** skipped: already fixed (code already matches desired state) — resolved in `c004f0e` (verification gap-closure; contract locked by helper tests in `tests/test_api_today.py`).

### CR-02: Hub conversation history silently empties after 6h idle
**File:** `memory/firestore_conversation.py`
**Reason:** skipped: already fixed — resolved in `ca9c40c` (decision: persist hub history for display; keep Telegram's bounded context). Covered by `tests/test_firestore_conversation.py`.

### CR-03: `/api/chat` appends user message before dispatch (orphan on enqueue failure / double-send on retry)
**File:** `interfaces/web_server.py`
**Reason:** skipped: already fixed — resolved in `ca9c40c` (enqueue-only; persist nothing if dispatch fails). Covered by `tests/test_hub_chat.py`.

### CR-04: `daily_note` coach note surfaced verbatim without length/format guard
**File:** `interfaces/web_server.py` / `core/morning_briefing.py`
**Reason:** skipped: already fixed — resolved in `ca9c40c` via `_sanitize_coach_note` (drops control/format chars, e.g. U+200E/U+200F). Covered by a coach-note sanitize test.

---

## Info Findings (follow-up — resolved 2026-06-16)

Iteration 1 scoped to `critical_warning`. The 5 Info findings were subsequently
cleared inline (trivial cosmetic/correctness nits):

| ID | Fix | Commit |
|----|-----|--------|
| IN-01 | Removed dead `_ChatBody` class (inline validation kept) | `5a0737f` |
| IN-02 | `@keyframes spin` defined once in `index.css`; per-component `<style>` injections removed (`MessageBubble.tsx`, `App.tsx`) | `20436c1` |
| IN-03 | `_routes_cache` now opportunistically evicts expired keys once per `/api/today` routes pass | `5a0737f` |
| IN-04 | No change needed — already resolved by the CR-01 fix; `_attach_leave_by` populates `leave_by`/`get_ready_at` (`web_server.py:1318-1319`), so the `today.ts` JSDoc is now accurate | — |
| IN-05 | Enter-to-send gated on `matchMedia('(pointer: fine)')` so phone soft keyboards insert a newline | `8dffde3` |

All 16 findings (4 Critical + 7 Warning + 5 Info) are now closed.

---

_Fixed: 2026-06-16T14:42:50Z (warnings) · 2026-06-16 (info follow-up)_
_Fixer: Claude (gsd-code-fixer iteration 1; orchestrator inline for info findings)_
_Iteration: 1_
