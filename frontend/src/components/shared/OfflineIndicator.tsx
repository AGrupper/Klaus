/**
 * OfflineIndicator.tsx — Amber offline strip + notice (HUB-03).
 *
 * When the browser is offline, renders a fixed 4px #F59E0B (amber-500) top
 * border strip with the "Offline — showing cached data" text below it.
 * Renders nothing when online.
 *
 * Mounted in AppShell so it appears at the top of every view.
 *
 * Copy locked by 26-UI-SPEC.md § Copywriting Contract.
 */
import { useOnline } from '../../hooks/useOnline'

export function OfflineIndicator() {
  const isOnline = useOnline()

  if (isOnline) {
    return null
  }

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        borderTop: '4px solid #F59E0B',
        backgroundColor: '#1A1A1A',
        padding: '6px 16px 8px',
        textAlign: 'center',
      }}
    >
      <span
        style={{
          fontSize: '13px',
          fontWeight: 400,
          color: '#F59E0B',
          lineHeight: 1.4,
        }}
      >
        Offline — showing cached data
      </span>
    </div>
  )
}
