/**
 * InstallBanner.tsx — iOS Add-to-Home-Screen instruction banner (HUB-02 / D-12).
 *
 * Shows only when: iOS device, not already running in standalone mode, and the
 * user has not previously dismissed it. Persists dismissal to localStorage so
 * it stays gone on future visits.
 *
 * Position: fixed-bottom, above the BottomTabs on phone and above the viewport
 * bottom on desktop.
 *
 * All copy is locked by 26-UI-SPEC.md § Copywriting Contract:
 *   heading: "Add Klaus to your home screen"
 *   body: 'Tap the Share button below, then choose "Add to Home Screen".'
 *   CTA: "How to install"
 *   dismiss aria-label: "Dismiss install prompt"
 *
 * Note (RESEARCH.md Pitfall 6): Israel is assumed non-EU so iOS 17.4+ standalone
 * install works. The banner degrades gracefully if it cannot install standalone.
 */
import { useState } from 'react'
import { useInstallBanner } from '../../hooks/useInstallBanner'

export function InstallBanner() {
  const { showBanner, dismiss } = useInstallBanner()

  // Expanded state for the "How to install" CTA
  const [expanded, setExpanded] = useState(false)

  if (!showBanner) {
    return null
  }

  return (
    /*
     * Fixed bottom banner — above BottomTabs (BottomTabs is 64px, so pb-16 = 64px)
     * on phone, above bottom of viewport on desktop.
     * z-40 keeps it below modals (z-50) but above standard content.
     */
    <div
      role="complementary"
      aria-label="Install Klaus as a home screen app"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 40,
        backgroundColor: '#1A1A1A',
        borderTop: '1px solid #2A2A2A',
        // On phone: add bottom padding to sit above the BottomTabs (64px) and safe-area inset
        paddingBottom: 'calc(64px + env(safe-area-inset-bottom, 0px))',
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
            Add Klaus to your home screen
          </p>
          <p
            style={{
              fontSize: '13px',
              fontWeight: 400,
              color: '#9CA3AF',
              lineHeight: 1.4,
              margin: '0 0 12px',
            }}
          >
            Tap the Share button below, then choose &ldquo;Add to Home Screen&rdquo;.
          </p>

          {/* Expanded instruction (shown when CTA clicked) */}
          {expanded && (
            <p
              style={{
                fontSize: '13px',
                fontWeight: 400,
                color: '#9CA3AF',
                lineHeight: 1.4,
                margin: '0 0 12px',
              }}
            >
              1. Tap the Share icon (box with arrow) in Safari&rsquo;s toolbar.
              <br />
              2. Scroll down and tap &ldquo;Add to Home Screen&rdquo;.
              <br />
              3. Tap &ldquo;Add&rdquo; to confirm.
            </p>
          )}

          {/* Accent CTA button */}
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
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
            How to install
          </button>
        </div>

        {/* Dismiss X button */}
        <button
          type="button"
          aria-label="Dismiss install prompt"
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
          {/* Simple X — no lucide dep needed for a dismiss button */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 18 18"
            fill="none"
            aria-hidden="true"
            focusable="false"
          >
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
