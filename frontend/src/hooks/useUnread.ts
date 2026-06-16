/**
 * useUnread.ts — Unread badge logic (CHAT-04 / D-10 / D-11).
 *
 * Implements RESEARCH Pattern 7:
 *   - `last_seen_seq` stored in localStorage (integer = messages.length the
 *     last time the user saw the bottom of the conversation).
 *   - `unreadCount = max(0, messages.length - last_seen_seq)` counts ALL
 *     unseen messages including Telegram-originated outreach (D-11) because
 *     the shared conversation history is one stream.
 *   - `markAllSeen()` sets localStorage.last_seen_seq = messages.length
 *     (called by ChatWindow's IntersectionObserver on the last message — D-10).
 *
 * Security note (T-26-08-03): unreadCount is derived from the authed
 * /api/chat/messages poll; a 401 redirects to sign-in before this runs.
 */

import { useCallback, useRef } from 'react'

const STORAGE_KEY = 'last_seen_seq'

/**
 * Returns the unread badge count and a function to clear it.
 *
 * @param messageCount - The current total number of messages (messages.length).
 */
export function useUnread(messageCount: number): {
  unreadCount: number
  markAllSeen: () => void
} {
  const lastSeen = parseInt(localStorage.getItem(STORAGE_KEY) ?? '0', 10)
  const unreadCount = Math.max(0, messageCount - lastSeen)

  // Render-stable: reads the live message count via the ref at call time
  // instead of closing over the `messageCount` value from the render in
  // which the callback was created. This keeps the function identity
  // stable across renders (safe as an effect dependency, e.g. the
  // IntersectionObserver effect in ChatWindow) while still always
  // persisting the truly-current count, not a stale snapshot.
  const messageCountRef = useRef(messageCount)
  messageCountRef.current = messageCount

  const markAllSeen = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, String(messageCountRef.current))
  }, [])

  return { unreadCount, markAllSeen }
}
