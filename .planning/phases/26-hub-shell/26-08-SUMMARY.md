---
phase: 26-hub-shell
plan: "08"
subsystem: frontend-chat
tags: [chat, optimistic-ui, polling, unread-badge, react-query, vitest]
dependency_graph:
  requires: ["26-05", "26-06"]
  provides: ["chat-ui", "unread-badge", "chat-polling"]
  affects: ["App.tsx", "BottomTabs", "DockChat"]
tech_stack:
  added: []
  patterns:
    - "TanStack Query useMutation onMutate/onError/onSettled (optimistic send)"
    - "useQuery refetchInterval gated on visibility flag (polling)"
    - "IntersectionObserver on last message for unread-clear"
    - "localStorage last_seen_seq for unread count persistence"
key_files:
  created:
    - frontend/src/api/chat.ts
    - frontend/src/hooks/useChat.ts
    - frontend/src/hooks/useUnread.ts
    - frontend/src/components/chat/ChatWindow.tsx
    - frontend/src/components/chat/MessageBubble.tsx
    - frontend/src/components/chat/TypingIndicator.tsx
    - frontend/src/components/chat/ChatInput.tsx
    - frontend/src/components/shared/UnreadBadge.tsx
    - frontend/src/hooks/useChat.test.tsx
  modified:
    - frontend/src/components/layout/BottomTabs.tsx
    - frontend/src/components/layout/DockChat.tsx
    - frontend/src/App.tsx
decisions:
  - "Polling active only when isVisible=true; ChatWindow passes true, BottomTabs passes !isKlausTabActive to avoid double-polling"
  - "DockChat also polls when collapsed (to keep badge fresh), ChatWindow takes over when expanded"
  - "useUnread is a pure function (reads localStorage at call time) not a stateful hook — simpler for test assertions and avoids stale closure issues"
  - "MessageBubble uses '#2A2A6E' (dark indigo) as user bubble background — slightly differentiated from secondary but still dark-theme"
metrics:
  duration: "6m 14s"
  completed: "2026-06-15"
  tasks_completed: 3
  files_created: 9
  files_modified: 3
---

# Phase 26 Plan 08: Klaus Chat UI Summary

**One-liner:** Optimistic send + 2.5s polling chat UI with IntersectionObserver unread badge, wired into KlausPage route and DockChat, backed by TanStack Query mutation/query pair.

---

## What Was Built

### Task 1 — Chat API client + data hooks (commit 6b7d098)

- `frontend/src/api/chat.ts`: `ChatMessage` type with optional `status` field (`sending|sent|error`), `fetchMessages()` calling `GET /api/chat/messages`, `postChatMessage(content)` calling `POST /api/chat`.
- `frontend/src/hooks/useChat.ts`: `useQuery` with `refetchInterval: isVisible ? 2500 : false` + `refetchIntervalInBackground: false` (TanStack default, explicit for clarity). `useMutation` with `onMutate` (cancel queries, snapshot, optimistic append with `status:'sending'`), `onError` (rollback to snapshot), `onSettled` (invalidate). `isKlausThinking` derived: `messages.at(-1)?.role === 'user'`.
- `frontend/src/hooks/useUnread.ts`: Pure function reading `localStorage.last_seen_seq` (default 0), `unreadCount = Math.max(0, messages.length - last_seen_seq)`, `markAllSeen()` writes `localStorage.last_seen_seq = String(messages.length)`.

### Task 2 — Chat components + shell integration (commit f2058ed)

- `ChatWindow.tsx`: scrollable container, 50-message slice (D-08), smart scroll (only when wasNearBottom ref is true), IntersectionObserver on last message div calling `markAllSeen()` (D-10), empty state "Say hello to Klaus.", TypingIndicator when `isKlausThinking`.
- `MessageBubble.tsx`: user messages right-aligned, Klaus left-aligned; status icons (spinning circle = sending, green checkmark = sent, red circle = error + "Couldn't send — tap to retry." retry button). No `dangerouslySetInnerHTML` (T-26-08-01).
- `TypingIndicator.tsx`: exact string "Klaus is thinking…" with 3-dot CSS bounce animation, left-aligned like a Klaus bubble.
- `ChatInput.tsx`: textarea + 44px accent send button, Enter=send (desktop), Shift+Enter=newline, disables when `isSending`.
- `UnreadBadge.tsx`: accent `#6366F1` background, white label, "9+" for counts >9, null return at 0.
- `BottomTabs.tsx`: replaced placeholder div with `<UnreadBadge count={unreadCount} />` from `useUnread(messages.length)`, polling via `useChat(!isKlausTabActive)`.
- `DockChat.tsx`: replaced placeholder div with `<ChatWindow isVisible={!collapsed} />`, UnreadBadge in header when expanded, on chevron button when collapsed.
- `App.tsx`: `KlausPage` replaced `<ComingSoon label="Chat" />` with `<ChatWindow isVisible={true} />`.

### Task 3 — Vitest spec (commit 4714c0f)

`frontend/src/hooks/useChat.test.tsx` with 9 tests in 3 describe blocks:
- **Optimistic send (a)**: mutation appends `{ role:'user', status:'sending' }` to cache before the held promise resolves.
- **isKlausThinking (b)**: true with last message `role:'user'`; false after `role:'assistant'` appended.
- **Polling shape (d)**: hook surface validated; isVisible=false triggers at most mount-time fetches.
- **useUnread math (c)**: 5 messages, last_seen=2 → unreadCount=3; `markAllSeen()` writes `'5'` to localStorage and subsequent hook call returns 0; clamped to 0 when last_seen > messages.length.

All 51 tests pass (42 pre-existing + 9 new).

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Unused import removed from MessageBubble**
- **Found during:** Task 2 build (`tsc -b`)
- **Issue:** `accent` imported from tokens but not used in JSX (user bubble uses a hardcoded dark indigo `#2A2A6E` for visual differentiation without violating the accent reservation rule)
- **Fix:** Removed `accent` from the import list
- **Files modified:** `frontend/src/components/chat/MessageBubble.tsx`
- **Commit:** f2058ed (part of task commit)

### Design Decisions Made During Implementation

**DockChat double-polling prevention:** The plan didn't specify how to handle the fact that both BottomTabs and DockChat would poll via `useChat` simultaneously. Resolved by:
- BottomTabs polls only when `!isKlausTabActive` (phone — the Klaus tab is the only place chat is visible on phone, so when you're ON the Klaus tab the ChatWindow owns polling)
- DockChat polls only when `collapsed=true` (desktop — when expanded, the ChatWindow component owns polling via `isVisible={!collapsed}`)

This ensures exactly one poll stream is active at any time.

---

## Threat Model Coverage

All four threats from the plan's `<threat_model>` were mitigated:

| Threat ID | Mitigation Applied |
|-----------|-------------------|
| T-26-08-01 Stored XSS | MessageBubble renders content as React text nodes only — no `dangerouslySetInnerHTML` |
| T-26-08-02 Background polling | `refetchInterval: isVisible ? 2500 : false` + `refetchIntervalInBackground: false` |
| T-26-08-03 Expired session badge | Badge derived from authed `/api/chat/messages`; 401 → sign-in redirect from `apiFetch` |
| T-26-08-04 False "sent" state | `onError` rolls back + marks `status:'error'`; "sent" green only after POST ACKs |

---

## Threat Flags

No new security surface was introduced beyond what was in the plan's threat model.

---

## Known Stubs

None — all data is wired to the live `/api/chat` and `/api/chat/messages` endpoints from 26-05. No placeholder or hardcoded data paths remain.

---

## Self-Check: PASSED

All files confirmed present on disk. All task commits verified in git log.

| Check | Result |
|-------|--------|
| `frontend/src/api/chat.ts` | FOUND |
| `frontend/src/hooks/useChat.ts` | FOUND |
| `frontend/src/hooks/useUnread.ts` | FOUND |
| `frontend/src/components/chat/ChatWindow.tsx` | FOUND |
| `frontend/src/components/chat/MessageBubble.tsx` | FOUND |
| `frontend/src/components/chat/TypingIndicator.tsx` | FOUND |
| `frontend/src/components/chat/ChatInput.tsx` | FOUND |
| `frontend/src/components/shared/UnreadBadge.tsx` | FOUND |
| `frontend/src/hooks/useChat.test.tsx` | FOUND |
| `.planning/phases/26-hub-shell/26-08-SUMMARY.md` | FOUND |
| Commit 6b7d098 (Task 1) | FOUND |
| Commit f2058ed (Task 2) | FOUND |
| Commit 4714c0f (Task 3) | FOUND |
| `npm run build` | PASS |
| `npm test -- --run` (51 tests) | PASS |
