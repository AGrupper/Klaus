/**
 * UnreadBadge.tsx — Unread message count badge (CHAT-04).
 *
 * UI-SPEC Shared Components:
 *   - Accent (#6366F1) background, white label text.
 *   - Shows the count, or "9+" for counts > 9.
 *   - Renders nothing (null) at count 0.
 *
 * Used by: BottomTabs (Klaus tab) + DockChat header.
 */
import { accent, fontFamily, typography } from '../../tokens'

interface UnreadBadgeProps {
  count: number
}

export function UnreadBadge({ count }: UnreadBadgeProps) {
  if (count <= 0) {
    return null
  }

  const label = count > 9 ? '9+' : String(count)

  return (
    <span
      aria-label={`${count} unread message${count === 1 ? '' : 's'}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        minWidth: '18px',
        height: '18px',
        paddingLeft: '4px',
        paddingRight: '4px',
        borderRadius: '9px',
        backgroundColor: accent,
        color: '#FFFFFF',
        fontSize: '11px',
        fontWeight: typography.label.fontWeight,
        lineHeight: 1,
        fontFamily,
        pointerEvents: 'none',
        userSelect: 'none',
      }}
    >
      {label}
    </span>
  )
}
