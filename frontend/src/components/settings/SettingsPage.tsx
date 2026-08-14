/**
 * SettingsPage.tsx — Minimal /settings skeleton (D-15).
 *
 * Provides the retained Web Push control. usePush().enablePush is wired to a
 * real button click (the only gesture-driven path to the iOS permission
 * prompt, T-29-21), with re-enable and subscribed states.
 *
 * Deliberately kept a skeleton — no sign-out/preferences/app-version here.
 * Sign-out already lives in Sidebar; this page grows in later phases
 * (RESEARCH.md "Settings page growth" note).
 */
import { useQuery } from '@tanstack/react-query'
import { usePush } from '../../hooks/usePush'
import { fetchSettings } from '../../api/settings'
import {
  dominant,
  accent,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

export function SettingsPage() {
  const { permission, enablePush, needsReenable, neverAsked, isSubscribed } = usePush()
  useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
  })

  return (
    <div
      style={{
        padding: '24px 16px 40px',
        maxWidth: '480px',
        display: 'flex',
        flexDirection: 'column',
        gap: '32px',
        fontFamily,
        backgroundColor: dominant,
        minHeight: '100%',
      }}
    >
      <h1
        style={{
          margin: 0,
          fontSize: typography.heading.fontSize,
          fontWeight: typography.heading.fontWeight,
          lineHeight: typography.heading.lineHeight,
          color: textPrimary,
        }}
      >
        Settings
      </h1>

      {/* Push notifications section */}
      <section aria-labelledby="settings-push-heading">
        <h2
          id="settings-push-heading"
          style={{
            margin: '0 0 8px',
            fontSize: typography.body.fontSize,
            fontWeight: typography.heading.fontWeight,
            lineHeight: typography.body.lineHeight,
            color: textPrimary,
          }}
        >
          Push notifications
        </h2>

        {permission === 'unsupported' ? (
          <p
            style={{
              margin: 0,
              fontSize: typography.label.fontSize,
              lineHeight: typography.label.lineHeight,
              color: textSecondary,
            }}
          >
            Push isn&rsquo;t supported on this device or browser.
          </p>
        ) : needsReenable ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <p
              style={{
                margin: 0,
                fontSize: typography.label.fontSize,
                lineHeight: typography.label.lineHeight,
                color: textSecondary,
              }}
            >
              Push was turned off in iOS Settings. Re-enable it: Settings &rarr;
              Notifications &rarr; Klaus &rarr; Allow Notifications.
            </p>
          </div>
        ) : isSubscribed ? (
          <p
            style={{
              margin: 0,
              fontSize: typography.label.fontSize,
              lineHeight: typography.label.lineHeight,
              color: textSecondary,
            }}
          >
            Push is enabled on this device.
          </p>
        ) : (
          <button
            type="button"
            onClick={() => void enablePush()}
            style={{
              minHeight: '44px',
              padding: '0 16px',
              backgroundColor: accent,
              color: textPrimary,
              border: 'none',
              borderRadius: '8px',
              fontSize: typography.body.fontSize,
              fontWeight: typography.heading.fontWeight,
              cursor: 'pointer',
            }}
          >
            {neverAsked ? 'Enable push' : 'Enable push notifications'}
          </button>
        )}
      </section>

    </div>
  )
}
