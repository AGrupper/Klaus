/**
 * TaskFAB.tsx — Phone-only floating action button that opens QuickAddBar.
 *
 * UI-SPEC (§ FAB):
 *   - 56px diameter accent #6366F1 circle
 *   - Fixed at bottom: 76px (above BottomTabs 64px + 12px gap)
 *   - aria-label="Add task"
 *   - Plus icon (lucide-react)
 *   - Phone only (hidden on desktop via md:hidden Tailwind class)
 *
 * When tapped:
 *   - Opens QuickAddBar as a bottom sheet overlay above the tab bar.
 *   - Bottom sheet slides up from the bottom of the screen.
 *   - Tapping the scrim or pressing Escape dismisses the sheet.
 *
 * Security (T-27-TI): no user content rendered here — static UI chrome only.
 */

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { QuickAddBar } from './QuickAddBar'
import {
  accent,
  border,
  secondary,
} from '../../tokens'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TaskFABProps {
  /** The list_id to create tasks into when no #list token is matched. */
  defaultListId?: string
}

// ---------------------------------------------------------------------------
// TaskFAB
// ---------------------------------------------------------------------------

export function TaskFAB({ defaultListId = 'inbox' }: TaskFABProps) {
  const [open, setOpen] = useState(false)

  function handleOpen() {
    setOpen(true)
  }

  function handleClose() {
    setOpen(false)
  }

  return (
    <>
      {/* FAB button — phone only (md:hidden) */}
      <button
        onClick={handleOpen}
        className="md:hidden"
        aria-label="Add task"
        style={{
          position: 'fixed',
          right: '16px',
          bottom: 'calc(env(safe-area-inset-bottom, 0px) + 76px)',
          width: '56px',
          height: '56px',
          borderRadius: '28px',
          backgroundColor: accent,
          border: 'none',
          color: '#FFFFFF',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          boxShadow: '0 4px 16px rgba(99,102,241,0.5)',
          zIndex: 40,
        }}
      >
        <Plus size={24} strokeWidth={2} aria-hidden="true" />
      </button>

      {/* Quick-add bottom sheet — phone only, slides up when FAB tapped */}
      {open && (
        <>
          {/* Scrim — tapping outside dismisses */}
          <div
            onClick={handleClose}
            className="md:hidden"
            style={{
              position: 'fixed',
              inset: 0,
              backgroundColor: 'rgba(10,10,10,0.7)',
              zIndex: 80,
            }}
            aria-hidden="true"
          />

          {/* Bottom sheet */}
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Add a task"
            className="md:hidden"
            data-quickadd
            style={{
              position: 'fixed',
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: secondary,
              borderTop: `1px solid ${border}`,
              borderRadius: '16px 16px 0 0',
              zIndex: 81,
              paddingBottom: 'env(safe-area-inset-bottom, 16px)',
            }}
          >
            {/* Drag handle */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                paddingTop: '10px',
                paddingBottom: '4px',
              }}
              aria-hidden="true"
            >
              <div
                style={{
                  width: '36px',
                  height: '4px',
                  borderRadius: '2px',
                  backgroundColor: '#3A3A3A',
                }}
              />
            </div>

            <QuickAddBar
              defaultListId={defaultListId}
              onClose={handleClose}
              onSubmit={() => {
                // Keep sheet open for rapid multi-entry; user can dismiss via Escape/scrim
              }}
              autoFocus={true}
            />
          </div>
        </>
      )}
    </>
  )
}
