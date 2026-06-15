/**
 * TypingIndicator.tsx — "Klaus is thinking…" indicator.
 *
 * Left-aligned, styled like a Klaus message bubble.
 * Appears when `isKlausThinking` is true (last message is role 'user').
 * Clears when an assistant message arrives (CHAT-03).
 *
 * Exact copy: "Klaus is thinking…" (UI-SPEC Copywriting Contract).
 */
import { secondary, textSecondary, typography, fontFamily } from '../../tokens'

// 3-dot CSS animation
const DOT_STYLE = (delay: string): React.CSSProperties => ({
  display: 'inline-block',
  width: '5px',
  height: '5px',
  borderRadius: '50%',
  backgroundColor: textSecondary,
  animation: 'typingBounce 1.2s ease-in-out infinite',
  animationDelay: delay,
  margin: '0 1px',
})

export function TypingIndicator() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        padding: '0 16px',
        marginBottom: '8px',
      }}
      aria-label="Klaus is thinking"
      role="status"
    >
      <div
        style={{
          backgroundColor: secondary,
          borderRadius: '16px 16px 16px 4px',
          padding: '10px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        {/* Exact copy per UI-SPEC Copywriting Contract */}
        <span
          style={{
            color: textSecondary,
            fontSize: typography.label.fontSize,
            fontWeight: typography.label.fontWeight,
            lineHeight: typography.label.lineHeight,
            fontFamily,
          }}
        >
          {/* Exact copy per UI-SPEC Copywriting Contract */}
          {'Klaus is thinking…'}
        </span>
        {/* 3-dot bounce animation */}
        <span aria-hidden="true" style={{ display: 'inline-flex', alignItems: 'center' }}>
          <span style={DOT_STYLE('0s')} />
          <span style={DOT_STYLE('0.2s')} />
          <span style={DOT_STYLE('0.4s')} />
        </span>
        <style>{`
          @keyframes typingBounce {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-4px); }
          }
        `}</style>
      </div>
    </div>
  )
}
