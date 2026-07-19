/**
 * ChatWindow.tsx — Full chat experience: message list + typing indicator + input.
 *
 * Behaviors (CHAT-03/04, D-08/10/11, UAT gap-closure 2026-07):
 *   - Renders the windowed message list from useChat (server-side windowing —
 *     the client no longer slices a full-history fetch; see useChat.ts).
 *   - Shows TypingIndicator when isKlausThinking (a turn is in flight).
 *   - Auto-scrolls to bottom when a NEW Klaus message arrives ONLY if the user
 *     was already at/near the bottom (does not yank if reading history).
 *   - Opens at the LATEST message on mount (WhatsApp-style). The message list
 *     is its own bounded scroll region (`flex-1 min-h-0 overflow-y-auto`) —
 *     see AppShell.tsx for why the ancestor height chain matters here: on
 *     phone the ancestor chain previously had no definite height, so this
 *     container's scrollHeight was always == clientHeight and the
 *     initial-scroll jump silently never had anywhere to scroll to.
 *   - On reaching (near) the top, automatically fetches one older page
 *     (`before=<oldest loaded seq>`) and prepends it, preserving the user's
 *     visual scroll position (classic prepend-anchoring: adjust scrollTop by
 *     the height delta the new content added above the fold).
 *   - Attaches IntersectionObserver to the last rendered message; when it
 *     becomes visible, calls markAllSeen() to clear the unread badge (D-10).
 *   - Empty state: "Say hello to Klaus." (Copywriting Contract).
 *   - 2.5s polling while mounted (isVisible=true passed to useChat).
 *   - Badge wiring (D-18, Phase 29): useAppBadge(unreadCount) reconciles the
 *     installed icon badge whenever unreadCount changes. Viewing chat (the
 *     markAllSeen path below) ALSO clears both badges directly — the tab
 *     badge (via markAllSeen's localStorage write) and the icon badge (via
 *     an explicit navigator.clearAppBadge() + RESET_BADGE post) — so the
 *     icon badge clears immediately rather than waiting for the next poll
 *     tick to re-render with unreadCount 0.
 *
 * Security note (T-26-08-01): All message content rendered via
 * MessageBubble which uses text nodes only, never dangerouslySetInnerHTML.
 */
import { useEffect, useLayoutEffect, useRef, useCallback } from 'react'
import { useChat, latestKnownSeq } from '../../hooks/useChat'
import { useUnread } from '../../hooks/useUnread'
import { useAppBadge } from '../../hooks/useAppBadge'
import { MessageBubble } from './MessageBubble'
import { TypingIndicator } from './TypingIndicator'
import { ChatInput } from './ChatInput'
import { dominant, textSecondary, typography, fontFamily } from '../../tokens'

// "Near bottom" threshold: if the user is within this many px of the bottom,
// consider them "at the bottom" and auto-scroll on new Klaus messages.
const NEAR_BOTTOM_PX = 80

// "Near top" threshold: reaching within this many px of the top triggers an
// automatic "load earlier messages" fetch (UAT gap-closure — WhatsApp-style
// infinite scroll-up).
const NEAR_TOP_PX = 60

interface ChatWindowProps {
  /** True when this ChatWindow is visible (controls polling — T-26-08-02). */
  isVisible?: boolean
}

export function ChatWindow({ isVisible = true }: ChatWindowProps) {
  const {
    messages,
    isKlausThinking,
    streamingDraft,
    stopGeneration,
    sendMessage,
    isSending,
    loadOlder,
    hasMoreOlder,
    isLoadingOlder,
  } = useChat(isVisible)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const lastMessageRef = useRef<HTMLDivElement>(null)
  const wasNearBottomRef = useRef(true) // start "at bottom" on mount

  // -------------------------------------------------------------------------
  // Unread badge (CHAT-04 / D-10/D-11) + icon badge reconciliation (D-18)
  // latestKnownSeq (not messages.length): the tail poll only ever holds one
  // page, so once history exceeds that page the loaded array length is no
  // longer the true conversation size — the newest message's server-
  // assigned `seq` is (UAT gap-closure windowing, see useChat.ts).
  // -------------------------------------------------------------------------
  const { unreadCount, markAllSeen } = useUnread(latestKnownSeq(messages))

  // Reconciles the installed PWA icon badge to match unreadCount on every
  // change (and posts RESET_BADGE so the SW's IDB counter stays honest).
  useAppBadge(unreadCount)

  // Viewing chat clears BOTH badges together (D-18): markAllSeen() clears
  // the tab badge (localStorage write, read by useUnread on next render);
  // clearAppBadge() + the RESET_BADGE post clear the icon badge immediately
  // rather than waiting for the next poll tick's re-render.
  const clearBothBadges = useCallback(() => {
    markAllSeen()
    try {
      const nav = navigator as Navigator & { clearAppBadge?: () => Promise<void> }
      void nav.clearAppBadge?.()
      navigator.serviceWorker?.controller?.postMessage({ type: 'RESET_BADGE', count: 0 })
    } catch {
      // Defensive: badge API failures must never crash the app (D-18).
    }
  }, [markAllSeen])

  // -------------------------------------------------------------------------
  // Scroll-up pagination anchor (UAT gap-closure): captured just before an
  // older page is requested so the anchor-preservation effect below can
  // adjust scrollTop by exactly the height the prepended content added.
  // -------------------------------------------------------------------------
  const pendingAnchorRef = useRef(false)
  const prevScrollHeightRef = useRef(0)

  // -------------------------------------------------------------------------
  // Track "near bottom" on scroll + trigger "load earlier" near the top
  // -------------------------------------------------------------------------
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    wasNearBottomRef.current = distFromBottom <= NEAR_BOTTOM_PX

    // Only meaningful once the list actually overflows its box — otherwise
    // scrollTop is always 0 and there is nothing "above" to load.
    const canScroll = el.scrollHeight > el.clientHeight
    if (canScroll && el.scrollTop <= NEAR_TOP_PX && hasMoreOlder && !isLoadingOlder) {
      pendingAnchorRef.current = true
      prevScrollHeightRef.current = el.scrollHeight
      void loadOlder()
    }
  }, [hasMoreOlder, isLoadingOlder, loadOlder])

  // -------------------------------------------------------------------------
  // Auto-scroll when new messages arrive — only if near bottom. Does NOT
  // fire for a scroll-up "load earlier" prepend: wasNearBottomRef is false
  // whenever the user has scrolled away from the bottom to trigger one.
  // -------------------------------------------------------------------------
  const prevMessageCountRef = useRef(messages.length)
  useEffect(() => {
    const prevCount = prevMessageCountRef.current
    const newCount = messages.length
    prevMessageCountRef.current = newCount

    if (newCount > prevCount && wasNearBottomRef.current) {
      scrollContainerRef.current?.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
        behavior: 'smooth',
      })
    }
  }, [messages.length])

  // Keep the growing streaming-draft bubble in view while the user is at the
  // bottom (the message-count effect above never fires for draft growth).
  useEffect(() => {
    if (streamingDraft && wasNearBottomRef.current) {
      scrollContainerRef.current?.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
      })
    }
  }, [streamingDraft])

  // -------------------------------------------------------------------------
  // Preserve scroll position across a "load earlier messages" prepend
  // (UAT gap-closure): after older messages are merged in above the fold,
  // shift scrollTop by exactly the height the new content added so the
  // message the user was looking at stays under the viewport.
  // useLayoutEffect: runs before paint, so there is no visible jump.
  // -------------------------------------------------------------------------
  useLayoutEffect(() => {
    if (!pendingAnchorRef.current) return
    const el = scrollContainerRef.current
    if (!el) return
    const delta = el.scrollHeight - prevScrollHeightRef.current
    if (delta > 0) {
      el.scrollTop = el.scrollTop + delta
    }
    pendingAnchorRef.current = false
  }, [messages.length])

  // Land at the bottom whenever the chat (re)mounts — including when you
  // navigate away and back (WhatsApp-style "open at the latest message").
  //
  // UAT gap-closure (2026-07): this previously also required
  // `el.scrollHeight > el.clientHeight` before jumping. On phone that
  // ancestor height chain was unbounded (see AppShell.tsx), so
  // scrollHeight and clientHeight were always equal and this guard never
  // passed — the chat silently opened at the top of history instead of the
  // latest message. Setting scrollTop = scrollHeight is safe even when
  // there's nothing to scroll (the browser clamps it), so the guard added
  // no correctness value and only made the effect fragile to layout timing.
  // The real fix is the bounded height chain (AppShell); this effect now
  // just needs "some content exists" to do its job.
  const didInitialScrollRef = useRef(false)
  useLayoutEffect(() => {
    if (didInitialScrollRef.current) return
    if (messages.length === 0) return
    const el = scrollContainerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    wasNearBottomRef.current = true
    didInitialScrollRef.current = true
  }, [messages.length])

  // -------------------------------------------------------------------------
  // IntersectionObserver on the last message → markAllSeen (D-10)
  // -------------------------------------------------------------------------
  useEffect(() => {
    const lastEl = lastMessageRef.current
    if (!lastEl) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          clearBothBadges()
        }
      },
      {
        root: scrollContainerRef.current,
        threshold: 0.5,
      },
    )

    observer.observe(lastEl)
    return () => observer.disconnect()
  }, [messages.length, clearBothBadges])

  // -------------------------------------------------------------------------
  // Retry: re-send a failed message
  // -------------------------------------------------------------------------
  function handleRetry(content: string) {
    sendMessage(content)
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{ backgroundColor: dominant }}
    >
      {/*
       * Message list — the chat's own bounded scroll region.
       * `flex-1 min-h-0 overflow-y-auto`: flex-1 fills the remaining height
       * of the column above; min-h-0 overrides the flex default min-height
       * (auto), which would otherwise let this box grow to fit its content
       * instead of clipping/scrolling it; overflow-y-auto is what actually
       * makes THIS element (not the page) the scroller. This trio is the
       * "structural fix" — see AppShell.tsx for the matching ancestor fix.
       */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 overflow-y-auto"
        style={{
          paddingTop: '16px',
          paddingBottom: '8px',
          // Smooth scrollbar on webkit
          scrollbarWidth: 'thin',
          scrollbarColor: '#2A2A2A transparent',
        }}
      >
        {/* "Load earlier messages" affordance — automatic (WhatsApp-style),
            this is just the loading feedback while the fetch is in flight. */}
        {isLoadingOlder && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              padding: '8px',
              color: textSecondary,
              fontSize: typography.body.fontSize,
              fontFamily,
            }}
          >
            Loading earlier messages…
          </div>
        )}

        {/* Empty state — "Say hello to Klaus." (Copywriting Contract) */}
        {messages.length === 0 && !isKlausThinking && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              minHeight: '120px',
              color: textSecondary,
              fontSize: typography.body.fontSize,
              fontWeight: typography.body.fontWeight,
              lineHeight: String(typography.body.lineHeight),
              fontFamily,
            }}
          >
            Say hello to Klaus.
          </div>
        )}

        {/* Messages */}
        {messages.map((msg, idx) => {
          const isLast = idx === messages.length - 1
          return (
            <div
              key={msg.id ?? (msg.seq !== undefined ? `seq-${msg.seq}` : `${msg.role}-${idx}`)}
              ref={isLast ? lastMessageRef : undefined}
            >
              <MessageBubble message={msg} onRetry={handleRetry} />
            </div>
          )
        })}

        {/* Streaming draft bubble (hub streaming): once real text is coming
            in, render it as a live assistant bubble with a typing cursor;
            until then fall back to the classic dots indicator (CHAT-03). */}
        {streamingDraft ? (
          <MessageBubble
            message={{ id: 'streaming-draft', role: 'assistant', content: `${streamingDraft} ▍` }}
          />
        ) : (
          isKlausThinking && <TypingIndicator />
        )}
      </div>

      {/* Input */}
      <ChatInput
        onSend={sendMessage}
        disabled={isSending}
        generating={isKlausThinking}
        onStop={stopGeneration}
      />
    </div>
  )
}
