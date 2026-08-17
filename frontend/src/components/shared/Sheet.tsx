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
 * Two fixes from Amit's 2026-08-17 phone UAT:
 *  - The body is now a real flex-min-height:0 scroll region and reserves the
 *    tab bar + home indicator at its foot, so a tall form's Save button is
 *    always reachable (it was rendering under the tab bar before).
 *  - The grab handle drags: touch/pointer down on the header pulls the sheet
 *    with your finger and releases into a dismiss past ~90px or a snap back.
 *
 * Purely presentational: open/close state lives with the caller.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useVisualViewport } from '../../hooks/useVisualViewport'

/** Drag distance past which the release dismisses instead of snapping back. */
const DISMISS_THRESHOLD_PX = 90

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
  const [dragOffset, setDragOffset] = useState(0)
  const dragStartY = useRef<number | null>(null)

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

  // Reset any residual drag whenever the sheet reopens.
  useEffect(() => {
    if (open) setDragOffset(0)
  }, [open])

  function handlePointerDown(event: React.PointerEvent) {
    dragStartY.current = event.clientY
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  function handlePointerMove(event: React.PointerEvent) {
    if (dragStartY.current === null) return
    // Downward only — an upward pull shouldn't lift the sheet off its anchor.
    setDragOffset(Math.max(0, event.clientY - dragStartY.current))
  }

  function handlePointerEnd() {
    if (dragStartY.current === null) return
    const travelled = dragOffset
    dragStartY.current = null
    setDragOffset(0)
    if (travelled > DISMISS_THRESHOLD_PX) onClose()
  }

  const dragging = dragStartY.current !== null

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
          transform: open ? `translateY(${dragOffset}px)` : 'translateY(105%)',
          transition: dragging
            ? 'none'
            : 'transform 0.32s cubic-bezier(0.3,0.9,0.3,1)',
          // Cap the sheet, then let the body scroll inside it.
          maxHeight: '88dvh',
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
        }}
      >
        {/* Drag zone: handle + header. touchAction none so the browser doesn't
            claim the gesture for scrolling before we see it. */}
        <div
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
          style={{ flexShrink: 0, touchAction: 'none', cursor: 'grab' }}
        >
          <div
            style={{
              width: '36px',
              height: '5px',
              borderRadius: '3px',
              background: 'var(--faint)',
              opacity: 0.6,
              margin: '10px auto 4px',
            }}
            aria-hidden="true"
          />
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: '8px',
              padding: '6px 20px 10px',
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
              onPointerDown={(e) => e.stopPropagation()}
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
        </div>
        {/* Body — the scroll region. min-height:0 is what actually lets it
            shrink inside the flex column; without it the content pushes the
            sheet past its max-height and the last controls are unreachable. */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch',
            overscrollBehavior: 'contain',
            padding: '0 20px',
            // Clear the fixed TabBar (60px) and the home indicator so the
            // final button in a form is never trapped behind them.
            paddingBottom: 'calc(76px + env(safe-area-inset-bottom, 0px))',
          }}
        >
          {children}
        </div>
      </div>
    </>
  )
}
