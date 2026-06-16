/**
 * MessageBubble.tsx — Single chat message bubble.
 *
 * User messages: right-aligned, accent-tinted background.
 * Klaus messages: left-aligned, secondary surface background.
 *
 * User message status icons (CHAT-03):
 *   sending  → animated clock spinner
 *   sent     → green (#22C55E) checkmark
 *   error    → red (#EF4444) "Couldn't send — tap to retry." with retry tap
 *
 * Security note (T-26-08-01): content rendered as text only — never via
 * dangerouslySetInnerHTML. React escapes content by default.
 */
import type { ChatMessage } from '../../api/chat'
import {
  secondary,
  textPrimary,
  textSecondary,
  success,
  destructive,
  typography,
  fontFamily,
} from '../../tokens'

interface MessageBubbleProps {
  message: ChatMessage
  onRetry?: (content: string) => void
}

// ---------------------------------------------------------------------------
// Status indicator for user messages
// ---------------------------------------------------------------------------

function StatusIcon({ status }: { status: ChatMessage['status'] }) {
  // No status = a plain historical message (e.g. loaded from the server,
  // which never sets `status` — see chat.ts). Show nothing rather than a
  // misleading "just sent" checkmark on messages from a prior session.
  if (!status) {
    return null
  }

  if (status === 'sent') {
    // sent: green checkmark
    return (
      <svg
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-label="Sent"
        style={{ flexShrink: 0 }}
      >
        <path
          d="M2 6L5 9L10 3"
          stroke={success}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  if (status === 'sending') {
    // Animated spinner — small clock/hourglass feel
    return (
      <span
        aria-label="Sending"
        style={{
          display: 'inline-block',
          width: '10px',
          height: '10px',
          border: `1.5px solid ${textSecondary}`,
          borderTopColor: 'transparent',
          borderRadius: '50%',
          animation: 'spin 0.75s linear infinite',
          flexShrink: 0,
        }}
      />
    )
  }

  // error: red icon
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Send failed"
      style={{ flexShrink: 0 }}
    >
      <circle cx="6" cy="6" r="5" stroke={destructive} strokeWidth="1.5" />
      <path
        d="M6 3.5V6.5"
        stroke={destructive}
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <circle cx="6" cy="8.5" r="0.5" fill={destructive} />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MessageBubble({ message, onRetry }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isError = message.status === 'error'

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        marginBottom: '8px',
        padding: '0 16px',
      }}
    >
      {/* Bubble */}
      <div
        style={{
          maxWidth: '75%',
          backgroundColor: isUser ? '#2A2A6E' : secondary,
          borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
          padding: '10px 14px',
          position: 'relative',
        }}
      >
        {/* Message text — never dangerouslySetInnerHTML (T-26-08-01) */}
        <p
          style={{
            margin: 0,
            color: textPrimary,
            fontSize: typography.body.fontSize,
            fontWeight: typography.body.fontWeight,
            lineHeight: typography.body.lineHeight,
            fontFamily,
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap',
          }}
        >
          {message.content}
        </p>

        {/* Status row for user messages */}
        {isUser && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: '4px',
              marginTop: '4px',
            }}
          >
            <StatusIcon status={message.status} />
          </div>
        )}
      </div>

      {/* Error retry — below the bubble (CHAT-03) */}
      {isUser && isError && (
        <button
          onClick={() => onRetry?.(message.content)}
          style={{
            marginTop: '4px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: destructive,
            fontSize: typography.label.fontSize,
            fontWeight: typography.label.fontWeight,
            lineHeight: typography.label.lineHeight,
            fontFamily,
            padding: '0',
          }}
          aria-label="Retry sending message"
        >
          {"Couldn't send — tap to retry."}
        </button>
      )}

      {/* CSS for the sending spinner */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
