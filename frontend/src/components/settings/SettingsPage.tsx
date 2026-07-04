/**
 * SettingsPage.tsx — Minimal /settings skeleton (D-15).
 *
 * Composes exactly two controls this phase needs:
 *   (a) Enable-push — usePush().enablePush wired to a real button click (the
 *       only gesture-driven path to the iOS permission prompt, T-29-21). Shows
 *       a re-enable hint when `needsReenable` (D-19) and a confirmed-enabled
 *       state once `isSubscribed`.
 *   (b) Telegram-mirror toggle — GET/PATCH /api/settings (D-09). Optimistic
 *       via react-query's onSuccess cache write; disabled while in flight.
 *
 * Deliberately kept a skeleton — no sign-out/preferences/app-version here.
 * Sign-out already lives in Sidebar; this page grows in later phases
 * (RESEARCH.md "Settings page growth" note).
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usePush } from '../../hooks/usePush'
import { fetchSettings, patchSettings } from '../../api/settings'
import {
  dominant,
  secondary,
  border,
  accent,
  textPrimary,
  textSecondary,
  typography,
  fontFamily,
} from '../../tokens'

export function SettingsPage() {
  const { permission, enablePush, needsReenable, neverAsked, isSubscribed } = usePush()
  const queryClient = useQueryClient()

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
  })

  const mirrorMutation = useMutation({
    mutationFn: (enabled: boolean) => patchSettings({ telegram_mirror_enabled: enabled }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated)
    },
  })

  // Default ON (mirror flag default per PROJECT context) until the first fetch resolves.
  const mirrorEnabled = settings?.telegram_mirror_enabled ?? true

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

      {/* Telegram mirror section */}
      <section aria-labelledby="settings-mirror-heading">
        <h2
          id="settings-mirror-heading"
          style={{
            margin: '0 0 8px',
            fontSize: typography.body.fontSize,
            fontWeight: typography.heading.fontWeight,
            lineHeight: typography.body.lineHeight,
            color: textPrimary,
          }}
        >
          Telegram mirror
        </h2>
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            minHeight: '44px',
            padding: '8px 12px',
            backgroundColor: secondary,
            border: `1px solid ${border}`,
            borderRadius: '8px',
            cursor: settingsLoading || mirrorMutation.isPending ? 'not-allowed' : 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={mirrorEnabled}
            disabled={settingsLoading || mirrorMutation.isPending}
            onChange={(e) => mirrorMutation.mutate(e.target.checked)}
            style={{ width: '18px', height: '18px', accentColor: accent, cursor: 'inherit' }}
            aria-label="Also send messages to Telegram"
          />
          <span
            style={{
              fontSize: typography.label.fontSize,
              lineHeight: typography.label.lineHeight,
              color: textPrimary,
            }}
          >
            Also send messages to Telegram
          </span>
        </label>
      </section>
    </div>
  )
}
