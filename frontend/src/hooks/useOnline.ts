/**
 * useOnline.ts — Reactive online/offline status hook.
 *
 * Returns true when the browser has network connectivity, false when offline.
 * Initializes from navigator.onLine and subscribes to the window online/offline
 * events for live updates. Cleans up listeners on unmount.
 *
 * Used by OfflineIndicator (HUB-03).
 */
import { useEffect, useState } from 'react'

export function useOnline(): boolean {
  const [isOnline, setIsOnline] = useState<boolean>(
    typeof navigator !== 'undefined' ? navigator.onLine : true,
  )

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true)
    }

    function handleOffline() {
      setIsOnline(false)
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  return isOnline
}
