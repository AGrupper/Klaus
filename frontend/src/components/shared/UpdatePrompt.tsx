/**
 * UpdatePrompt.tsx — "New version available → Refresh" banner.
 *
 * The PWA service worker caches the app shell + bundles. With the previous
 * `registerType: 'autoUpdate'` config, a new deploy updated silently in the
 * background and only swapped in on some future load — so the user kept seeing
 * stale code with no signal. This switches to prompt-mode: when the SW detects
 * a newly-deployed version, this banner appears and the user taps Refresh to
 * load it immediately (updateServiceWorker(true) activates the new SW + reloads).
 *
 * Also polls for a new version every 60s while the app is open so the prompt
 * shows up without the user having to relaunch.
 */
import { useRegisterSW } from 'virtual:pwa-register/react'

export function UpdatePrompt() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      if (registration) {
        setInterval(() => {
          void registration.update()
        }, 60_000)
      }
    },
  })

  if (!needRefresh) return null

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        left: '50%',
        transform: 'translateX(-50%)',
        // Sit above the phone bottom-tab bar (64px + safe area); harmless on desktop.
        bottom: 'calc(64px + env(safe-area-inset-bottom, 0px) + 12px)',
        zIndex: 200,
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        maxWidth: 'calc(100vw - 32px)',
        backgroundColor: '#1A1A1A',
        border: '1px solid #2A2A2A',
        borderRadius: '12px',
        padding: '10px 12px 10px 16px',
        boxShadow: '0 8px 24px rgba(0, 0, 0, 0.5)',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
      }}
    >
      <span style={{ fontSize: '14px', color: '#F9FAFB', whiteSpace: 'nowrap' }}>
        New version available
      </span>
      <button
        onClick={() => updateServiceWorker(true)}
        style={{
          flexShrink: 0,
          backgroundColor: '#6366F1',
          color: '#FFFFFF',
          border: 'none',
          borderRadius: '8px',
          padding: '8px 14px',
          fontSize: '14px',
          fontWeight: 600,
          cursor: 'pointer',
          minHeight: '36px',
        }}
      >
        Refresh
      </button>
      <button
        onClick={() => setNeedRefresh(false)}
        aria-label="Dismiss update notice"
        style={{
          flexShrink: 0,
          background: 'none',
          border: 'none',
          color: '#9CA3AF',
          fontSize: '14px',
          cursor: 'pointer',
          padding: '8px',
        }}
      >
        Later
      </button>
    </div>
  )
}
