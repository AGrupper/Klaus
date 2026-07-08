/**
 * DrilldownSheetShell.tsx — Shared bottom-sheet (phone) / centered-modal
 * (desktop) chrome for the three training drill-down sheets, adapted from
 * TaskDetailSheet.tsx's positional split (30-PATTERNS.md, 30-UI-SPEC.md).
 *
 * scrim z:190, sheet z:191, 250ms ease-out slide, scroll-lock while open,
 * close button uses onMouseDown={preventDefault} to avoid the blur-before-
 * click trap. Unlike TaskDetailSheet, these sheets have NO text inputs, so
 * there is no useVisualViewport/keyboardInset tracking — phone anchors at
 * bottom: 0.
 *
 * Not itself listed in 30-05-PLAN.md's files_modified (it's a small internal
 * helper introduced per the plan's own instruction to "prefer a tiny shared
 * shell to avoid drift" across the three sheet files) — lives alongside them
 * in components/health/training/.
 */
import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { secondary, border, textPrimary, textSecondary, typography, fontFamily } from '../../../tokens'

interface DrilldownSheetShellProps {
  open: boolean
  onClose: () => void
  title: string
  /** 480 default; drill-downs with tables may use up to 560 (30-UI-SPEC Responsive § desktop). */
  maxWidth?: number
  children: React.ReactNode
}

export function DrilldownSheetShell({ open, onClose, title, maxWidth = 480, children }: DrilldownSheetShellProps) {
  const [slideIn, setSlideIn] = useState(false)

  // Slide-in animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setSlideIn(true))
    } else {
      setSlideIn(false)
    }
  }, [open])

  // Lock background scroll while the sheet is open.
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  if (!open) return null

  const isPhone = typeof window !== 'undefined' && window.innerWidth < 768

  return (
    <>
      {/* Scrim — above BottomTabs (z:100) so it covers the phone tab bar too */}
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(10,10,10,0.7)', zIndex: 190 }}
        aria-hidden="true"
      />

      {/* Sheet / Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{
          position: 'fixed',
          zIndex: 191,
          ...(isPhone
            ? {
                left: 0,
                right: 0,
                bottom: 0, // no keyboard inset needed — no text inputs in these sheets
                maxHeight: 'calc(100dvh - 24px)',
                borderRadius: '16px 16px 0 0',
                transform: slideIn ? 'translateY(0)' : 'translateY(100%)',
                transition: 'transform 0.25s ease-out',
              }
            : {
                left: '50%',
                top: '50%',
                transform: slideIn ? 'translate(-50%, -50%)' : 'translate(-50%, calc(-50% + 20px))',
                transition: 'transform 0.25s ease-out, opacity 0.25s ease-out',
                maxWidth: `${maxWidth}px`,
                width: '100%',
                maxHeight: '90dvh',
                borderRadius: '16px',
              }),
          backgroundColor: secondary,
          border: `1px solid ${border}`,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            padding: '14px 16px',
            borderBottom: `1px solid ${border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexShrink: 0,
          }}
        >
          <h3
            style={{
              margin: 0,
              fontSize: typography.body.fontSize,
              fontWeight: 600,
              lineHeight: typography.body.lineHeight,
              color: textPrimary,
              fontFamily,
            }}
          >
            {title}
          </h3>
          <button
            onClick={onClose}
            onMouseDown={(e) => e.preventDefault()}
            aria-label="Close"
            style={{
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              backgroundColor: 'transparent',
              color: textSecondary,
              cursor: 'pointer',
              borderRadius: '8px',
            }}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div
          style={{
            padding: '16px',
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          {children}
        </div>
      </div>
    </>
  )
}
