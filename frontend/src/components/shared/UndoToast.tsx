/**
 * UndoToast.tsx — global undo toast for habit deletes (D-20 flow).
 *
 * Mechanics (inherited from the Phase 27/28 toast, tasks paths removed with
 * the Tasks surface):
 *   - Single active item, last-action-wins: a second delete immediately fires
 *     the replaced item's hard-delete.
 *   - 4s browser setTimeout → hardDeleteHabit(id) + clear().
 *   - "Undo" → restoreHabit(id) + invalidate routines/habits caches.
 *   - If the tab dies mid-window, HabitStore.reclaim_stale_deletions()
 *     finishes the delete server-side on the next list load (WR-02).
 *
 * Message is static copy, never habit content (T-27-TI).
 */
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { hardDeleteHabit, restoreHabit } from '../../api/habits'
import { useUndoStore } from '../../store/undoStore'

const UNDO_WINDOW_MS = 4000

export function UndoToast() {
  const activeItem = useUndoStore((s) => s.activeItem)
  const clear = useUndoStore((s) => s.clear)
  const queryClient = useQueryClient()
  const [visible, setVisible] = useState(false)

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const timerItemIdRef = useRef<string | null>(null)

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['routines'] })
    void queryClient.invalidateQueries({ queryKey: ['habits'] })
  }

  function fireHardDelete(id: string) {
    hardDeleteHabit(id).catch(() => {
      // Best-effort: reclaim_stale_deletions() self-heals on the server.
    })
  }

  useEffect(() => {
    if (activeItem) {
      // Replacing a live toast ends the previous item's window immediately.
      if (timerItemIdRef.current !== null && timerItemIdRef.current !== activeItem.id) {
        if (timerRef.current) clearTimeout(timerRef.current)
        fireHardDelete(timerItemIdRef.current)
      }
      timerItemIdRef.current = activeItem.id
      setVisible(true)
      timerRef.current = setTimeout(() => {
        fireHardDelete(activeItem.id)
        timerItemIdRef.current = null
        setVisible(false)
        clear()
        invalidate()
      }, UNDO_WINDOW_MS)
      return () => {
        if (timerRef.current) clearTimeout(timerRef.current)
      }
    }
    setVisible(false)
    return undefined
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeItem?.id])

  if (!activeItem || !visible) return null

  function handleUndo() {
    if (!activeItem) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerItemIdRef.current = null
    restoreHabit(activeItem.id)
      .catch(() => {})
      .finally(() => invalidate())
    setVisible(false)
    clear()
  }

  return (
    <div
      role="status"
      style={{
        position: 'fixed',
        left: '50%',
        transform: 'translateX(-50%)',
        bottom: 'calc(env(safe-area-inset-bottom, 0px) + 76px)',
        zIndex: 300,
        display: 'flex',
        alignItems: 'center',
        gap: '14px',
        background: 'var(--ink)',
        color: 'var(--ground)',
        borderRadius: '12px',
        padding: '11px 16px',
        boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
        fontSize: '14px',
        fontWeight: 500,
        whiteSpace: 'nowrap',
      }}
    >
      Habit deleted
      <button
        onClick={handleUndo}
        style={{
          border: 'none',
          background: 'none',
          color: 'var(--flame-soft)',
          fontSize: '14px',
          fontWeight: 700,
          cursor: 'pointer',
          padding: 0,
        }}
      >
        Undo
      </button>
    </div>
  )
}
