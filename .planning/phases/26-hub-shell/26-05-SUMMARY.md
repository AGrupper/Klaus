---
phase: 26-hub-shell
plan: 05
subsystem: api
tags: [cloud-tasks, firestore-conversation, fastapi, oidc, chat]

requires:
  - phase: 26-hub-shell
    provides: require_hub_session (26-03), telegram_user_id bridge (26-02), enqueue_update pattern
provides:
  - POST /api/chat — appends user message to the shared FirestoreConversationStore + enqueues the agent turn
  - GET /api/chat/messages — polling window with stable seq indices (unread badge source)
  - POST /internal/process-hub-message — OIDC-gated Cloud Tasks full-CPU worker (one Klaus, no Telegram send)
  - enqueue_hub_message in core/task_dispatch.py
affects: [26-08]

tech-stack:
  added: []
  patterns: [hub chat shares one Firestore conversation keyed on telegram_user_id; agent turn runs in a tracked Cloud Tasks request, never a BackgroundTask]

key-files:
  created: []
  modified:
    - core/task_dispatch.py
    - interfaces/web_server.py
    - tests/test_hub_chat.py
    - tests/test_task_dispatch.py

key-decisions:
  - "Hub keys FirestoreConversationStore on telegram_user_id (26-02 bridge) so hub + Telegram are one continuous conversation."
  - "Agent turn enqueued via enqueue_hub_message → /internal/process-hub-message (full-CPU), never a Starlette BackgroundTask (D-09 / CLAUDE.md invariant — CPU throttling caused 18-min replies)."
  - "/internal/process-hub-message reuses _verify_cron_request OIDC gating exactly like /internal/process-update."

patterns-established:
  - "Hub chat backend mirrors the Telegram dispatch path; reply is appended to the shared conversation without a Telegram send (hub polls GET /api/chat/messages)."

requirements-completed: [CHAT-01, CHAT-02, CHAT-03, CHAT-04]

duration: ~7min (executor) + inline recovery
completed: 2026-06-15
---

# Phase 26 Plan 05: Hub Chat Backend Summary

**A dedicated Cloud Tasks full-CPU chat path so hub messages run the agent turn exactly like Telegram, sharing one continuous Firestore conversation.**

## Performance
- **Tasks:** 3
- **Completed:** 2026-06-15

## Accomplishments
- `enqueue_hub_message(content, user_id)` in `core/task_dispatch.py` targets the new full-CPU worker.
- `POST /api/chat` (require_hub_session): validates content, appends the user message to the shared `FirestoreConversationStore` keyed on `telegram_user_id`, enqueues the agent turn; 503 on enqueue failure.
- `GET /api/chat/messages` (require_hub_session): returns the conversation window with stable `seq` indices for the unread badge (D-11), JSON-safe via `_jsonsafe_doc`.
- `POST /internal/process-hub-message`: OIDC-gated; runs the agent turn via `asyncio.to_thread` inside the tracked request, appends the assistant reply (no Telegram send). SPA mount remains the last route.

## Task Commits
1. **Task 1: enqueue_hub_message + worker target** — `d297f0d` (feat) + `tests/test_task_dispatch.py`
2. **Task 2: /api/chat + /api/chat/messages + /internal/process-hub-message** — `bb7c691` (feat)
3. **Task 3: flip test_hub_chat skips → real assertions** — `834c8da` (test)

## Deviations from Plan
### Execution-recovery deviation (not a scope change)
**Executor truncated by session limit after Task 2.** The chat routes were written (uncommitted) but Task 3 (test_hub_chat) was not flipped. The orchestrator committed the routes and wrote the 5 real tests inline (CHAT-01 append, CHAT-02 enqueue, empty-content 400, CHAT-03 window+seq, CHAT-04 OIDC gate) via FastAPI `dependency_overrides` + mocked store/enqueue.
**Verification:** `pytest tests/test_hub_chat.py` → 5 passed; full suite 1410 passed.

## Issues Encountered
None beyond the session-limit truncation handled above.

## Next Phase Readiness
26-08 (chat UI) consumes POST /api/chat, GET /api/chat/messages, and the seq-based unread badge.

## Self-Check: PASSED

---
*Phase: 26-hub-shell*
*Completed: 2026-06-15*
