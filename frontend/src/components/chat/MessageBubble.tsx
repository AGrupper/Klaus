/**
 * MessageBubble.tsx — Single chat message bubble.
 *
 * User messages: right-aligned, accent-tinted background, plain text.
 * Klaus messages: left-aligned, secondary surface background, rendered as
 * Markdown (the brain writes **bold**, pipe tables, bullets, code fences —
 * previously shown as raw asterisks/pipes).
 *
 * User message status icons (CHAT-03):
 *   sending  → animated clock spinner
 *   sent     → green (#22C55E) checkmark
 *   error    → red (#EF4444) "Couldn't send — tap to retry." with retry tap
 *
 * Security note (T-26-08-01): never dangerouslySetInnerHTML. react-markdown
 * builds React elements from a Markdown AST and ignores embedded raw HTML by
 * default (no rehype-raw), so model/content HTML stays inert text.
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import type { ChatMessage } from '../../api/chat'
import {
  accent,
  border,
  dominant,
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
  /** Present only on the last Klaus message — regenerates the reply. */
  onRegenerate?: () => void
  /** Present only on the user's last message — prefills the input to resend. */
  onEdit?: (content: string) => void
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
// Markdown rendering for Klaus messages
// ---------------------------------------------------------------------------

const bodyText: CSSProperties = {
  color: textPrimary,
  fontSize: typography.body.fontSize,
  fontWeight: typography.body.fontWeight,
  lineHeight: typography.body.lineHeight,
  fontFamily,
  wordBreak: 'break-word',
}

const codeFont = 'ui-monospace, SFMono-Regular, Menlo, monospace'
const cellStyle: CSSProperties = {
  padding: '4px 8px',
  border: `1px solid ${border}`,
  textAlign: 'left',
  whiteSpace: 'nowrap',
}

/**
 * Styled element overrides for react-markdown. Everything inherits the chat
 * body type scale; tables scroll horizontally inside the bubble instead of
 * blowing past its 75% max-width.
 */
const markdownComponents = {
  p: (props: React.ComponentProps<'p'>) => (
    <p {...props} style={{ ...bodyText, margin: '0 0 8px' }} />
  ),
  strong: (props: React.ComponentProps<'strong'>) => (
    <strong {...props} style={{ fontWeight: 600, color: textPrimary }} />
  ),
  a: (props: React.ComponentProps<'a'>) => (
    <a
      {...props}
      target="_blank"
      rel="noopener noreferrer"
      style={{ color: accent, textDecoration: 'underline' }}
    />
  ),
  ul: (props: React.ComponentProps<'ul'>) => (
    <ul {...props} style={{ ...bodyText, margin: '0 0 8px', paddingLeft: '20px' }} />
  ),
  ol: (props: React.ComponentProps<'ol'>) => (
    <ol {...props} style={{ ...bodyText, margin: '0 0 8px', paddingLeft: '20px' }} />
  ),
  li: (props: React.ComponentProps<'li'>) => (
    <li {...props} style={{ marginBottom: '2px' }} />
  ),
  h1: (props: React.ComponentProps<'h1'>) => (
    <p {...props} style={{ ...bodyText, fontWeight: 600, margin: '0 0 8px' }} />
  ),
  h2: (props: React.ComponentProps<'h2'>) => (
    <p {...props} style={{ ...bodyText, fontWeight: 600, margin: '0 0 8px' }} />
  ),
  h3: (props: React.ComponentProps<'h3'>) => (
    <p {...props} style={{ ...bodyText, fontWeight: 600, margin: '0 0 8px' }} />
  ),
  code: (props: React.ComponentProps<'code'>) => (
    <code
      {...props}
      style={{
        fontFamily: codeFont,
        fontSize: '0.9em',
        backgroundColor: dominant,
        borderRadius: '4px',
        padding: '1px 4px',
      }}
    />
  ),
  pre: (props: React.ComponentProps<'pre'>) => (
    <pre
      {...props}
      style={{
        fontFamily: codeFont,
        fontSize: '0.85em',
        backgroundColor: dominant,
        border: `1px solid ${border}`,
        borderRadius: '8px',
        padding: '8px 10px',
        overflowX: 'auto',
        margin: '0 0 8px',
        color: textPrimary,
      }}
    />
  ),
  table: (props: React.ComponentProps<'table'>) => (
    <div style={{ overflowX: 'auto', margin: '0 0 8px' }}>
      <table
        {...props}
        style={{
          ...bodyText,
          fontSize: '0.9em',
          borderCollapse: 'collapse',
        }}
      />
    </div>
  ),
  th: (props: React.ComponentProps<'th'>) => (
    <th {...props} style={{ ...cellStyle, fontWeight: 600, backgroundColor: dominant }} />
  ),
  td: (props: React.ComponentProps<'td'>) => <td {...props} style={cellStyle} />,
  blockquote: (props: React.ComponentProps<'blockquote'>) => (
    <blockquote
      {...props}
      style={{
        ...bodyText,
        margin: '0 0 8px',
        paddingLeft: '10px',
        borderLeft: `2px solid ${border}`,
        color: textSecondary,
      }}
    />
  ),
  hr: () => <hr style={{ border: 'none', borderTop: `1px solid ${border}`, margin: '8px 0' }} />,
}

function KlausMarkdown({ content }: { content: string }) {
  return (
    // Negative margin swallows the last block's 8px bottom margin so the
    // bubble's own padding stays visually even.
    <div style={{ marginBottom: '-8px' }}>
      <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={markdownComponents}>
        {content}
      </Markdown>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Attachments (hub attachments feature — transient session previews)
// ---------------------------------------------------------------------------

/**
 * Renders the attachments sent with a message. Images show as an inline
 * preview when their object URL is still alive this session; after a refresh
 * (or for PDFs always) a named file chip is shown instead — the bytes are
 * transient and there is no server URL to recover them from.
 */
function AttachmentList({ message }: { message: ChatMessage }) {
  const attachments = message.attachments ?? []
  if (attachments.length === 0) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: message.content ? '8px' : 0 }}>
      {attachments.map((att, i) => {
        const previewUrl = message.previewUrls?.[i]
        if (att.kind === 'image' && previewUrl) {
          return (
            <img
              key={att.id}
              src={previewUrl}
              alt={att.name}
              style={{
                maxWidth: '240px',
                maxHeight: '240px',
                borderRadius: '10px',
                objectFit: 'cover',
                display: 'block',
              }}
            />
          )
        }
        // File chip: PDFs, and images whose preview URL is gone.
        return (
          <div
            key={att.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 10px',
              borderRadius: '8px',
              backgroundColor: dominant,
              border: `1px solid ${border}`,
              maxWidth: '240px',
            }}
          >
            <span aria-hidden="true" style={{ fontSize: '16px' }}>
              {att.kind === 'pdf' ? '📄' : '🖼️'}
            </span>
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  ...bodyText,
                  fontSize: '0.85em',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {att.name}
              </div>
              <div style={{ color: textSecondary, fontSize: '0.75em', fontFamily }}>
                {formatSize(att.size)}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
  return `${bytes} B`
}

// ---------------------------------------------------------------------------
// Message actions (hub message actions feature)
// ---------------------------------------------------------------------------

const actionButtonStyle: CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: textSecondary,
  fontSize: typography.label.fontSize,
  fontWeight: typography.label.fontWeight,
  fontFamily,
  padding: '2px 4px',
  display: 'inline-flex',
  alignItems: 'center',
  gap: '4px',
}

/**
 * Small action row under a bubble: copy (always), plus regenerate/edit when
 * the parent passes the callbacks (last Klaus / last user message only).
 * Copies the RAW markdown for Klaus messages — pasteable anywhere.
 */
function MessageActions({ message, onRegenerate, onEdit }: {
  message: ChatMessage
  onRegenerate?: () => void
  onEdit?: (content: string) => void
}) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    void navigator.clipboard?.writeText(message.content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: '8px',
        marginTop: '2px',
        justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start',
      }}
    >
      <button onClick={handleCopy} aria-label="Copy message" style={actionButtonStyle}>
        {copied ? (
          '✓ Copied'
        ) : (
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <rect x="4.5" y="4.5" width="8" height="8" rx="1.5" stroke="currentColor" />
            <path d="M9.5 4.5V3a1.5 1.5 0 00-1.5-1.5H3A1.5 1.5 0 001.5 3v5A1.5 1.5 0 003 9.5h1.5" stroke="currentColor" />
          </svg>
        )}
      </button>
      {onRegenerate && (
        <button onClick={onRegenerate} aria-label="Regenerate reply" style={actionButtonStyle}>
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M12.5 7A5.5 5.5 0 111.9 4.5M12.5 1.5v3h-3" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
      {onEdit && (
        <button
          onClick={() => onEdit(message.content)}
          aria-label="Edit message"
          style={actionButtonStyle}
        >
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M9.8 1.7a1.5 1.5 0 012.1 2.1L4.5 11.2l-2.9.8.8-2.9 7.4-7.4z" stroke="currentColor" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MessageBubble({ message, onRetry, onRegenerate, onEdit }: MessageBubbleProps) {
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
        {/* Attachments sent with this message (session-local previews) */}
        <AttachmentList message={message} />

        {/* Message text — never dangerouslySetInnerHTML (T-26-08-01).
            Klaus messages render as Markdown (React elements from an AST);
            user messages stay literal plain text. */}
        {isUser ? (
          message.content ? (
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
          ) : null
        ) : (
          <KlausMarkdown content={message.content} />
        )}

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

      {/* Action row — copy always; regenerate/edit when wired by the parent.
          Hidden on in-flight/error optimistic messages (status row owns those). */}
      {message.status !== 'sending' && !isError && (
        <MessageActions message={message} onRegenerate={onRegenerate} onEdit={onEdit} />
      )}

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
    </div>
  )
}
