---
phase: 29-web-push-transition
plan: 08
subsystem: notifications
tags: [web-push, telegram, fastapi, react-query, run_in_executor, vapid]

requires:
  - phase: 29-04
    provides: "core/push_sender.py::send_push_to_all (sync, VAPID webpush fan-out)"
  - phase: 29-06
    provides: "HubSettingsStore (telegram_mirror_enabled), toggle_telegram_mirror tool"

provides:
  - "send_and_inject extended with message_class/push kwargs; push fans out via run_in_executor unless the hub chat was recently visible (D-02); Telegram mirror gated on HubSettingsStore.telegram_mirror_enabled at full volume (D-10); push failures logged+swallowed (D-04)"
  - "mark_chat_visible()/is_chat_visible() in-process D-02 visibility gate + lazy _get_bot() singleton for bot-less callers (hub replies)"
  - "interfaces/_router.py Telegram-turn replies also push (chat_reply class) after the native reply_text — deliberate double-buzz"
  - "interfaces/web_server.py internal_process_hub_message pushes + mirrors hub replies via send_and_inject(bot=None, ...)"
  - "GET /api/chat/messages accepts ?chat_visible=1 and calls mark_chat_visible() — server-side D-02 gate input"
  - "frontend fetchMessages(chatVisible)/useChat(isVisible) thread chat_visible=1 into the existing 2.5s poll — client half of D-02, zero new polling"

affects: [29-09, 29-10, 30]

tech-stack:
  added: []
  patterns:
    - "Push-before-mirror ordering inside send_and_inject: settings lookup -> push (run_in_executor, D-02-gated) -> Telegram mirror (flag-gated, full volume) -> conversation inject"
    - "Lazy module-level singleton (_get_bot) mirrors the existing lazy-import discipline for callers with no Bot instance of their own"

key-files:
  created: []
  modified:
    - core/scheduled_message.py
    - tests/test_scheduled_message.py
    - interfaces/_router.py
    - interfaces/web_server.py
    - frontend/src/api/chat.ts
    - frontend/src/hooks/useChat.ts
    - frontend/src/hooks/useChat.test.tsx

key-decisions:
  - "bot=None is a first-class send_and_inject caller shape (hub replies) — resolved lazily via a process-wide _get_bot() Bot singleton, never rebuilt per call"
  - "Push happens before the Telegram mirror inside send_and_inject so a push failure never blocks/skips the mirror, and vice versa"
  - "HubSettingsStore.get() failure fails open to mirror ON (never silently goes Telegram-dark) — logged, not raised"
  - "Telegram-turn replies (interfaces/_router.py) push unconditionally after reply_text with no visibility gate — the hub chat view is not the source of that send path (Open Question 1, deliberate double-buzz)"

patterns-established:
  - "D-02 chat-visibility gate: in-process module float (core.scheduled_message._chat_visible_until), refreshed by the existing chat poll via ?chat_visible=1 — no new endpoint, no Firestore persistence (single Cloud Run instance, RESEARCH A5)"

requirements-completed: [PUSH-02, PUSH-03]

duration: 35min
completed: 2026-07-04
---

# Phase 29 Plan 08: Route All Send Paths Through Push Summary

**All three Klaus send paths (proactive crons, hub chat replies, Telegram-turn replies) now fan out a Web Push behind a server-side chat-visibility gate, while `send_and_inject` keeps mirroring to Telegram at full volume behind the `telegram_mirror_enabled` flag.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-04
- **Tasks:** 3/3
- **Files modified:** 7

## Accomplishments

- `send_and_inject` (core/scheduled_message.py) now reads `HubSettingsStore.get()`, fans a push out via `run_in_executor` unless the hub chat was reported visible in the last ~8s (D-02), and only sends the Telegram message while the mirror flag is on — at full volume, no `disable_notification` (D-10). Push failures are logged and swallowed, never raised (D-04); Telegram send keeps its raise-on-failure contract.
- Added `mark_chat_visible()`/`is_chat_visible()` module-level D-02 gate and a lazy `_get_bot()` singleton so callers with no `Bot` instance of their own (hub replies) can reuse the same delivery path.
- `interfaces/_router.py`: after the native `reply_text` on a Telegram turn, also fans out a push (`chat_reply` class) — the deliberate double-buzz called out in the plan's Open Question 1.
- `interfaces/web_server.py::internal_process_hub_message`: captures the orchestrator's reply text and delivers it through `send_and_inject(None, reply_text, message_class="chat_reply", inject_into_conversation=False)`, so hub chat replies now push + mirror to Telegram without double-writing the conversation (handle_message already appended it — CR-03 guard preserved).
- `GET /api/chat/messages` accepts `?chat_visible=1` and calls `mark_chat_visible()` — the server-side half of the D-02 gate. The route remains read-only; it never pushes itself.
- Frontend: `fetchMessages(chatVisible)` appends `?chat_visible=1` when true; `useChat(isVisible)`'s poll `queryFn` closure threads `isVisible` through, so every 2.5s poll while the hub chat is genuinely on-screen reports visibility with zero new polling. `ChatWindow.tsx` was left untouched (already threads `isVisible` into `useChat`; owned by Plan 10).

## Task Commits

1. **Task 1: Extend send_and_inject with push + mirror gate + visibility gate** - `7486d3d` (feat)
2. **Task 2: Wire hub-reply + Telegram-turn push paths + chat-visibility reporting** - `3b8e5f3` (feat)
3. **Task 3: Client reports chat visibility on the existing poll (D-02 trigger)** - `b681ef6` (test)

_Plan metadata commit (SUMMARY.md) follows this list per the worktree execution protocol._

## Files Created/Modified

- `core/scheduled_message.py` — push fan-out + mirror gate + D-02 visibility helpers + lazy `_get_bot()`
- `tests/test_scheduled_message.py` — extended with mirror on/off, visibility gate, push-failure-swallowed, settings-lookup-failure-fails-open, and lazy-Bot-singleton-reuse tests (13 tests total, all passing)
- `interfaces/_router.py` — push after the Telegram-turn `reply_text`
- `interfaces/web_server.py` — hub-reply push/mirror hook in `internal_process_hub_message`; `?chat_visible=1` handling in `GET /api/chat/messages`
- `frontend/src/api/chat.ts` — `fetchMessages(chatVisible)` param
- `frontend/src/hooks/useChat.ts` — `queryFn` closure threads `isVisible` into `fetchMessages`
- `frontend/src/hooks/useChat.test.tsx` — new `describe` block asserting `chat_visible=1` reporting per `isVisible`

## Decisions Made

- `bot=None` is a supported `send_and_inject` caller shape (hub replies have no `Bot` instance); resolved via a lazily-built, process-wide `_get_bot()` singleton rather than constructing a new `Bot` per call.
- Push fan-out happens *before* the Telegram mirror inside `send_and_inject` so neither channel's failure blocks the other; a `HubSettingsStore.get()` failure fails open to mirror ON (logged, never silently goes Telegram-dark).
- Telegram-turn replies in `interfaces/_router.py` push unconditionally after `reply_text` with no D-02 gate — the hub chat view is not the source of that send path, so the deliberate double-buzz stands (Open Question 1).
- `internal_process_hub_message` wraps its `send_and_inject` call in try/except so a Telegram-mirror failure never fails the hub-reply HTTP response — the Firestore write (the source of truth for the hub poll) already succeeded before this call.

## Deviations from Plan

None — plan executed as written. One clarification made where the plan left an explicit choice open ("None-or-`_get_bot()`", Open Question 2): resolved as `bot: Bot | None` accepted directly by `send_and_inject`, internally falling back to `_get_bot()` when `bot is None` and the mirror is enabled — callers pass `None` rather than pre-resolving the singleton themselves.

## Issues Encountered

- Running the full python test suite in one process surfaces known pre-existing cross-file test-isolation pollution (e.g. `google.cloud` namespace mutation from `test_push_api.py`'s Firestore mock breaking `google_auth_oauthlib`/`requests_oauthlib` import order when combined with other files in the same pytest process). Verified per-file per the project's documented convention (CLAUDE.md / STATE.md "Test env note") — every file touched by or related to this plan passes cleanly in isolation.
- `tests/test_autonomous.py::TestPhase28HabitGather::test_habit_gather_dedups_already_nudged` fails in this worktree — called out explicitly in the environment notes as a known pre-existing failure, not introduced by this plan and not fixed here (out of scope).
- The worktree's `frontend/node_modules` was absent (gitignored, not copied into the worktree checkout); ran `npm ci` inside `frontend/` to install before running vitest. This is a local dev-environment step, not a code or dependency change — nothing was added to `package.json`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All three Klaus send paths (proactive crons via `send_and_inject`, hub chat replies, Telegram-turn replies) now push, satisfying PUSH-02's "every send pushes" requirement and PUSH-03's mirror-flag gating.
- The D-02 visibility gate is fully wired end-to-end: client reports `chat_visible=1` on the existing poll -> server marks the in-process window -> `send_and_inject` reads it before pushing.
- Post-retirement follow-up tracked (not built this phase, per plan's `<output>` note): once the mirror is eventually disabled (D-21), `OutreachLogStore.append`'s gate-on-`send_and_inject`-success semantics should be redefined as "≥1 channel succeeded" rather than "Telegram succeeded" — currently the Telegram raise-on-failure contract is preserved because the mirror is still the primary during the transition week(s).
- Plan 29-09 (usePush/useAppBadge hooks) and Plan 29-10 (ChatWindow wiring, wave 4) can proceed independently — no shared frontend files were touched beyond the three explicitly scoped to this plan.

---
*Phase: 29-web-push-transition*
*Completed: 2026-07-04*
