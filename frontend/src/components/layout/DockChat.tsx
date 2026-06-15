/**
 * DockChat.tsx — Desktop collapsible chat panel (right-most column).
 *
 * UI-SPEC constraints:
 *   - Desktop only: hidden md:flex (flex-col)
 *   - 360px wide; collapses to 48px header strip via chevron toggle
 *   - Header strip (48px) always visible (contains chevron + "Klaus" label)
 *   - Expanded state: full-height ChatWindow (26-08)
 *   - Accent #6366F1 used only for: send button, unread badge (CHAT-04)
 *     NOT for the header chevron button
 */
import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { ChatWindow } from '../chat/ChatWindow'
import { UnreadBadge } from '../shared/UnreadBadge'
import { useChat } from '../../hooks/useChat'
import { useUnread } from '../../hooks/useUnread'

export function DockChat() {
  const [collapsed, setCollapsed] = useState(false)

  // Poll only when collapsed (badge still needs updating); ChatWindow owns
  // polling when expanded (isVisible=true is the default in useChat).
  const { messages } = useChat(collapsed)
  const { unreadCount } = useUnread(messages.length)

  return (
    /*
     * hidden md:flex — desktop only.
     * flex-col: header strip on top, chat content below.
     * Width transitions between 360px (expanded) and 48px (collapsed).
     */
    <div
      className="hidden md:flex flex-col"
      style={{
        width: collapsed ? '48px' : '360px',
        flexShrink: 0,
        borderLeft: '1px solid #2A2A2A',
        backgroundColor: '#1A1A1A',
        transition: 'width 0.2s ease',
        overflow: 'hidden',
        position: 'relative',
      }}
      aria-label="Chat panel"
    >
      {/* 48px header strip — always visible */}
      <div
        style={{
          height: '48px',
          minHeight: '48px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'space-between',
          padding: collapsed ? '0' : '0 12px',
          borderBottom: collapsed ? 'none' : '1px solid #2A2A2A',
          flexShrink: 0,
        }}
      >
        {/* "Klaus" label + unread badge — only visible when expanded */}
        {!collapsed && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              style={{
                fontSize: '16px',
                fontWeight: 600,
                lineHeight: 1.2,
                color: '#F9FAFB',
                fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
                letterSpacing: '-0.01em',
              }}
            >
              Klaus
            </span>
            {/* UnreadBadge in the header (CHAT-04) */}
            <UnreadBadge count={unreadCount} />
          </div>
        )}

        {/* Chevron toggle button */}
        <button
          onClick={() => setCollapsed((prev) => !prev)}
          title={collapsed ? 'Expand chat' : 'Collapse chat'}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '32px',
            height: '32px',
            borderRadius: '6px',
            border: 'none',
            backgroundColor: 'transparent',
            color: '#9CA3AF',
            cursor: 'pointer',
            flexShrink: 0,
            transition: 'color 0.15s',
            position: 'relative',
          }}
          aria-expanded={!collapsed}
          aria-controls="dock-chat-content"
        >
          {collapsed ? (
            <>
              <ChevronLeft size={18} strokeWidth={1.75} aria-hidden="true" />
              {/* Badge on chevron when collapsed (still visible) */}
              {unreadCount > 0 && (
                <div style={{ position: 'absolute', top: '-2px', right: '-4px' }}>
                  <UnreadBadge count={unreadCount} />
                </div>
              )}
            </>
          ) : (
            <ChevronRight size={18} strokeWidth={1.75} aria-hidden="true" />
          )}
          <span className="sr-only">{collapsed ? 'Expand chat' : 'Collapse chat'}</span>
        </button>
      </div>

      {/* Chat panel content — ChatWindow (26-08) */}
      {!collapsed && (
        <div
          id="dock-chat-content"
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          <ChatWindow isVisible={!collapsed} />
        </div>
      )}
    </div>
  )
}
