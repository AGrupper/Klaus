/**
 * Sheet.tsx — bottom-sheet primitive with the Phase-27 iOS lessons baked in:
 *
 *  - z-index above the fixed TabBar (tabbar z:100 → scrim 400 / sheet 401)
 *  - `bottom: keyboardInset` via useVisualViewport so position:fixed tracks
 *    the soft keyboard instead of being covered by it
 *  - body scroll-lock while open (overflow:hidden), restored on close
 *  - scrim uses onMouseDown preventDefault so blur-before-click can't eat
 *    the first tap on controls inside the sheet
 *  - no autoFocus on phones (callers own their focus behavior)
 *
 * Purely presentational: open/close state lives with the caller.
 */
import { useEffect, type ReactNode } from 'react'
import { useVisualViewport } from '../../hooks/useVisualViewport'

interface SheetProps {
  open: boolean
  onClose: () => void
  title: string
  /** Optional small text next to the title (e.g. "2 new"). */
  subtitle?: string
  children: ReactNode
  ariaLabel?: string
}

export function Sheet({ open, onClose, title, subtitle, children, ariaLabel }: SheetProps) {
  const { keyboardInset } = useVisualViewport()

  // Body scroll-lock while open (iOS rubber-band scrolling leaks through
  // the scrim otherwise). Restored on close/unmount.
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  return (
    <>
      {/* Scrim */}
      <div
        onMouseDown={(e) => e.preventDefault()}
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(20,22,28,0.35)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          transition: 'opacity 0.25s',
          zIndex: 400,
        }}
        aria-hidden="true"
      />
      {/* Sheet */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel ?? title}
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: keyboardInset,
          zIndex: 401,
          maxWidth: '430px',
          margin: '0 auto',
          background: 'var(--ground)',
          borderRadius: '20px 20px 0 0',
          boxShadow: '0 -8px 40px rgba(0,0,0,0.18)',
          transform: open ? 'translateY(0)' : 'translateY(105%)',
          transition: 'transform 0.32s cubic-bezier(0.3,0.9,0.3,1)',
          maxHeight: '85dvh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Grab handle */}
        <div
          style={{
            width: '36px',
            height: '4px',
            borderRadius: '2px',
            background: 'var(--faint)',
            opacity: 0.5,
            margin: '10px auto 4px',
            flexShrink: 0,
          }}
        />
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: '8px',
            padding: '6px 20px 10px',
            flexShrink: 0,
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              letterSpacing: '-0.02em',
              fontSize: '21px',
              color: 'var(--ink)',
            }}
          >
            {title}
          </span>
          {subtitle && (
            <span style={{ fontSize: '12.5px', color: 'var(--muted)' }}>{subtitle}</span>
          )}
          <button
            onClick={onClose}
            onMouseDown={(e) => e.preventDefault()}
            style={{
              marginLeft: 'auto',
              border: 'none',
              background: 'none',
              color: 'var(--accent)',
              fontSize: '14px',
              fontWeight: 600,
              padding: '4px 0',
              cursor: 'pointer',
            }}
          >
            Done
          </button>
        </div>
        {/* Body */}
        <div
          style={{
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch',
            padding: '0 20px calc(20px + env(safe-area-inset-bottom, 0px))',
          }}
        >
          {children}
        </div>
      </div>
    </>
  )
}
