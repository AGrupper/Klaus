/**
 * UndoToast.tsx — Global undo toast driven by undoStore.
 *
 * Position:
 *   - Phone (< 768px): fixed above BottomTabs at bottom: 76px (64px tabs + 12px gap)
 *   - Desktop (≥ 768px): fixed bottom-center at bottom: 24px
 *
 * Mechanics (D-13, D-14, UI-SPEC § Undo toast):
 *   - Single active item (last-action-wins) from undoStore.
 *   - 4-second countdown; on expiry → hardDeleteTask(id) + clear().
 *   - "Undo" button → undoTask(id) + restore query cache + clear().
 *   - 200ms fade-out on dismiss.
 *   - Second action before first expires: UndoToast fires hardDelete for old
 *     item immediately when show() is called (store replaces activeItem;
 *     UndoToast's useEffect detects the new id and fires the prior delete).
 *
 * The 4s timer is a browser setTimeout — NOT a server call (T-27-REP, CLAUDE.md §6).
 *
 * Security note (T-27-TI): toast message is static copy, not task content.
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useUndoStore } from '../../store/undoStore'
import { undoTask, hardDeleteTask } from '../../api/tasks'
import { tasksQueryKey } from '../../hooks/useTasks'
import {
  accent,
  border,
  secondary,
  textPrimary,
  typography,
  fontFamily,
} from '../../tokens'

// ---------------------------------------------------------------------------
// UndoToast
// ---------------------------------------------------------------------------

export function UndoToast() {
  const activeItem = useUndoStore((s) => s.activeItem)
  const clear = useUndoStore((s) => s.clear)
  const queryClient = useQueryClient()

  // Track visibility for fade-out
  const [visible, setVisible] = useState(false)

  // Timer ref for the 4s countdown
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Ref to track which id the current timer was started for
  const timerItemIdRef = useRef<string | null>(null)
  // Snapshot of the item for the fade-out cleanup
  const pendingDeleteRef = useRef<{ id: string; listId: string } | null>(null)

  // Helper: fire hard-delete for an item that's being replaced or expired
  function fireHardDelete(id: string) {
    hardDeleteTask(id).catch(() => {
      // Best-effort — server will garbage-collect orphaned "completing" docs
    })
  }

  useEffect(() => {
    if (activeItem) {
      // If there's already a timer running for a DIFFERENT item, fire its hard-delete now
      // (last-action-wins: the replaced item's undo window ends immediately)
      if (
        timerItemIdRef.current !== null &&
        timerItemIdRef.current !== activeItem.id &&
        pendingDeleteRef.current
      ) {
        fireHardDelete(pendingDeleteRef.current.id)
      }

      // Clear any existing timer
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }

      // Show the toast
      setVisible(true)
      timerItemIdRef.current = activeItem.id
      pendingDeleteRef.current = { id: activeItem.id, listId: activeItem.listId }

      // Start the 4s countdown
      timerRef.current = setTimeout(() => {
        // Timer expired: fire hard-delete and dismiss
        if (pendingDeleteRef.current) {
          fireHardDelete(pendingDeleteRef.current.id)
        }
        // Fade out
        setVisible(false)
        setTimeout(() => {
          clear()
          timerItemIdRef.current = null
          pendingDeleteRef.current = null
        }, 200)
        timerRef.current = null
      }, 4000)
    } else {
      // Store cleared externally (e.g., undo fired from the button)
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      setVisible(false)
      timerItemIdRef.current = null
      pendingDeleteRef.current = null
    }

    return () => {
      // Cleanup on unmount — do NOT fire hard-delete on unmount (user navigated away)
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [activeItem?.id]) // Re-run whenever the active item id changes

  async function handleUndo() {
    if (!activeItem) return

    // Cancel the timer
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }

    const { id, listId } = activeItem

    // Clear store first (optimistic UI restore)
    clear()
    setVisible(false)
    timerItemIdRef.current = null
    pendingDeleteRef.current = null

    try {
      await undoTask(id)
      // Invalidate the query to refetch the task back into the list
      queryClient.invalidateQueries({ queryKey: tasksQueryKey(listId) })
    } catch {
      // Undo failed — the task was already hard-deleted server-side or the
      // undo window expired. There's nothing to restore; show no additional error
      // (the user already acknowledged the action).
    }
  }

  // Don't render if no active item
  if (!activeItem) return null

  const message =
    activeItem.action === 'complete' ? 'Task completed.' : 'Task deleted.'

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      style={{
        position: 'fixed',
        // Phone: above BottomTabs (64px) + 12px gap
        // Desktop: bottom-center 24px
        bottom: 'calc(env(safe-area-inset-bottom, 0px) + 76px)',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 100,
        opacity: visible ? 1 : 0,
        transition: 'opacity 0.2s ease',
        pointerEvents: visible ? 'auto' : 'none',
      }}
      className="md:bottom-6" // Tailwind override for desktop: bottom 24px
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '12px 16px',
          backgroundColor: secondary,
          border: `1px solid ${border}`,
          borderRadius: '10px',
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
          maxWidth: '320px',
          height: '52px',
          whiteSpace: 'nowrap',
        }}
      >
        <span
          style={{
            fontSize: typography.label.fontSize,
            fontFamily,
            color: textPrimary,
          }}
        >
          {message}
        </span>
        <button
          onClick={handleUndo}
          style={{
            border: 'none',
            backgroundColor: 'transparent',
            color: accent,
            fontSize: typography.label.fontSize,
            fontWeight: 600,
            fontFamily,
            cursor: 'pointer',
            padding: '0',
            flexShrink: 0,
          }}
        >
          Undo
        </button>
      </div>
    </div>
  )
}
