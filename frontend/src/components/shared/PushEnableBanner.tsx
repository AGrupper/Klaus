/**
 * PushEnableBanner.tsx — Today first-run push enable banner (D-16) + the
 * re-enable-in-iOS-Settings variant (D-19).
 *
 * Modeled on InstallBanner's fixed-bottom shell (role, z-40 above BottomTabs,
 * safe-area padding, dismiss X, 44px tap targets). Two independent dismiss
 * keys so dismissing the first-run prompt doesn't permanently suppress a
 * later re-enable notice — they're different lifecycle moments.
 *
 * Gated on:
 *   - Push API supported (usePush().permission !== 'unsupported')
 *   - standalone (installed home-screen PWA — iOS Push API requirement)
 *   - usePush().neverAsked (first-run, D-16) OR usePush().needsReenable (D-19)
 *
 * The primary CTA only appears in the first-run variant and calls
 * usePush().enablePush directly from this onClick — a real user gesture,
 * the only path that can trigger the iOS permission prompt (T-29-21). The
 * re-enable variant has no functional button (permission is already
 * 'denied'; subscribe() cannot succeed there) — it's instructional text
 * pointing to iOS Settings.
 */
import { useState } from 'react'
import { usePush } from '../../hooks/usePush'

const NEVER_ASKED_DISMISS_KEY = 'push-banner-dismissed'
const REENABLE_DISMISS_KEY = 'push-reenable-banner-dismissed'

function detectStandalone(): boolean {
  if (typeof window === 'undefined') return false
  const mediaMatch =
    typeof window.matchMedia === 'function'
      ? window.matchMedia('(display-mode: standalone)').matches
      : false
  // navigator.standalone is a non-standard Safari property (true when launched from home screen)
  const navStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true
  return mediaMatch || navStandalone
}

function isDismissed(key: string): boolean {
  try {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function persistDismissed(key: string): void {
  try {
    localStorage.setItem(key, '1')
  } catch {
    /* ignore — Safari private mode; dismiss just won't persist across reloads */
  }
}

export function PushEnableBanner() {
  const { permission, enablePush, needsReenable, neverAsked } = usePush()
  const [neverAskedDismissed, setNeverAskedDismissed] = useState(() =>
    isDismissed(NEVER_ASKED_DISMISS_KEY),
  )
  const [reenableDismissed, setReenableDismissed] = useState(() =>
    isDismissed(REENABLE_DISMISS_KEY),
  )

  if (permission === 'unsupported') return null
  if (!detectStandalone()) return null

  const showReenable = needsReenable && !reenableDismissed
  const showNeverAsked = !showReenable && neverAsked && !neverAskedDismissed

  if (!showReenable && !showNeverAsked) return null

  const variant: 'reenable' | 'first-run' = showReenable ? 'reenable' : 'first-run'

  function dismiss() {
    if (variant === 'reenable') {
      persistDismissed(REENABLE_DISMISS_KEY)
      setReenableDismissed(true)
    } else {
      persistDismissed(NEVER_ASKED_DISMISS_KEY)
      setNeverAskedDismissed(true)
    }
  }

  return (
    /*
     * Fixed bottom banner — above BottomTabs (BottomTabs is 64px, so
     * pb-16 = 64px) on phone, above bottom of viewport on desktop.
     * z-40 keeps it below modals (z-50) but above standard content.
     */
    <div
      role="complementary"
      aria-label={
        variant === 'reenable' ? 'Re-enable push notifications' : 'Enable push notifications'
      }
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 40,
        backgroundColor: '#1A1A1A',
        borderTop: '1px solid #2A2A2A',
        padding: '16px 16px calc(64px + env(safe-area-inset-bottom, 0px))',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
        {/* Text content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <p
            style={{
              fontSize: '16px',
              fontWeight: 600,
              color: '#F9FAFB',
              lineHeight: 1.2,
              margin: '0 0 6px',
            }}
          >
            {variant === 'reenable' ? 'Push notifications are off' : 'Turn on push notifications'}
          </p>
          <p
            style={{
              fontSize: '13px',
              fontWeight: 400,
              color: '#9CA3AF',
              lineHeight: 1.4,
              margin: variant === 'reenable' ? 0 : '0 0 12px',
            }}
          >
            {variant === 'reenable'
              ? 'Re-enable them in iOS Settings → Notifications → Klaus → Allow Notifications.'
              : 'Get notified the instant Klaus replies — even with the app closed.'}
          </p>

          {/* Primary CTA — first-run only; a real user gesture (T-29-21) */}
          {variant === 'first-run' && (
            <button
              type="button"
              onClick={() => void enablePush()}
              style={{
                backgroundColor: '#6366F1',
                color: '#F9FAFB',
                fontSize: '13px',
                fontWeight: 600,
                lineHeight: 1.4,
                border: 'none',
                borderRadius: '6px',
                padding: '8px 14px',
                cursor: 'pointer',
                minHeight: '44px',
              }}
            >
              Enable push
            </button>
          )}
        </div>

        {/* Dismiss X button */}
        <button
          type="button"
          aria-label="Dismiss push notification prompt"
          onClick={dismiss}
          style={{
            background: 'none',
            border: 'none',
            color: '#9CA3AF',
            cursor: 'pointer',
            padding: '4px',
            minWidth: '44px',
            minHeight: '44px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true" focusable="false">
            <path
              d="M14 4L4 14M4 4l10 10"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    </div>
  )
}
