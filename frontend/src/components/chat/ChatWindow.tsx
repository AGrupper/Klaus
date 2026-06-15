/**
 * ChatWindow.tsx — Full chat experience: message list + typing indicator + input.
 *
 * Behaviors (CHAT-03/04, D-08/10/11):
 *   - Renders the most recent 50 messages from useChat (D-08 window slice).
 *   - Shows TypingIndicator when isKlausThinking (a turn is in flight).
 *   - Auto-scrolls to bottom when a NEW Klaus message arrives ONLY if the user
 *     was already at/near the bottom (does not yank if reading history).
 *   - Attaches IntersectionObserver to the last rendered message; when it
 *     becomes visible, calls markAllSeen() to clear the unread badge (D-10).
 *   - Empty state: "Say hello to Klaus." (Copywriting Contract).
 *   - 2.5s polling while mounted (isVisible=true passed to useChat).
 *
 * Security note (T-26-08-01): All message content rendered via
 * MessageBubble which uses text nodes only, never dangerouslySetInnerHTML.
 */
import { useEffect, useRef, useCallback } from 'react'
import { useChat } from '../../hooks/useChat'
import { useUnread } from '../../hooks/useUnread'
import { MessageBubble } from './MessageBubble'
import { TypingIndicator } from './TypingIndicator'
import { ChatInput } from './ChatInput'
import { dominant, textSecondary, typography, fontFamily } from '../../tokens'
import type { ChatMessage } from '../../api/chat'

// Display at most 50 messages on first paint (D-08 window).
const DISPLAY_LIMIT = 50

// "Near bottom" threshold: if the user is within this many px of the bottom,
// consider them "at the bottom" and auto-scroll on new Klaus messages.
const NEAR_BOTTOM_PX = 80

interface ChatWindowProps {
  /** True when this ChatWindow is visible (controls polling — T-26-08-02). */
  isVisible?: boolean
}

export function ChatWindow({ isVisible = true }: ChatWindowProps) {
  const { messages: allMessages, isKlausThinking, sendMessage, isSending } = useChat(isVisible)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const lastMessageRef = useRef<HTMLDivElement>(null)
  const wasNearBottomRef = useRef(true) // start "at bottom" on mount

  // Slice to the display window (D-08)
  const messages: ChatMessage[] = allMessages.slice(-DISPLAY_LIMIT)

  // -------------------------------------------------------------------------
  // Unread badge (CHAT-04 / D-10/D-11)
  // -------------------------------------------------------------------------
  const { markAllSeen } = useUnread(allMessages.length)

  // -------------------------------------------------------------------------
  // Track "near bottom" on scroll
  // -------------------------------------------------------------------------
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    wasNearBottomRef.current = distFromBottom <= NEAR_BOTTOM_PX
  }, [])

  // -------------------------------------------------------------------------
  // Auto-scroll when new messages arrive — only if near bottom
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

  // Initial scroll to bottom on mount
  useEffect(() => {
    const el = scrollContainerRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [])

  // -------------------------------------------------------------------------
  // IntersectionObserver on the last message → markAllSeen (D-10)
  // -------------------------------------------------------------------------
  useEffect(() => {
    const lastEl = lastMessageRef.current
    if (!lastEl) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          markAllSeen()
        }
      },
      {
        root: scrollContainerRef.current,
        threshold: 0.5,
      },
    )

    observer.observe(lastEl)
    return () => observer.disconnect()
  }, [messages.length, markAllSeen])

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
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: dominant,
        overflow: 'hidden',
      }}
    >
      {/* Message list */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          overflowY: 'auto',
          paddingTop: '16px',
          paddingBottom: '8px',
          // Smooth scrollbar on webkit
          scrollbarWidth: 'thin',
          scrollbarColor: '#2A2A2A transparent',
        }}
      >
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
            <div key={msg.id ?? `${msg.role}-${idx}`} ref={isLast ? lastMessageRef : undefined}>
              <MessageBubble message={msg} onRetry={handleRetry} />
            </div>
          )
        })}

        {/* Typing indicator (CHAT-03) */}
        {isKlausThinking && <TypingIndicator />}
      </div>

      {/* Input */}
      <ChatInput onSend={sendMessage} disabled={isSending} />
    </div>
  )
}
