/**
 * SignInPage — full-screen Google Sign-In page for the Klaus Hub.
 *
 * UI-SPEC constraints:
 *   - Full-screen dark background (#0A0A0A = dominant)
 *   - Centered vertically and horizontally
 *   - "Klaus" heading at Display scale (28px/600) in textPrimary (#F9FAFB)
 *   - "Your personal agent" subheading in textSecondary (#9CA3AF)
 *   - Google Identity Services sign-in button (loads GIS script, renders button)
 *   - Accent (#6366F1) used only on the GIS button wrapper — this is the "sign-in
 *     CTA" role approved by UI-SPEC (analogous to install banner CTA)
 *
 * Flow (RESEARCH.md Pattern 2):
 *   1. Load accounts.google.com/gsi/client script on mount
 *   2. Call google.accounts.id.initialize({ client_id, callback })
 *   3. Render the sign-in button in #g_id_signin_btn
 *   4. On credential callback: POST /api/auth/google → setSignedIn(email)
 */
import { useEffect, useRef, useState } from 'react'
import { signInWithGoogle } from '../../api/auth'
import { useAuthStore } from '../../store/auth'

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string
            callback: (response: { credential: string }) => void
            auto_select?: boolean
          }) => void
          renderButton: (
            element: HTMLElement,
            options: {
              theme?: string
              size?: string
              type?: string
              text?: string
            },
          ) => void
        }
      }
    }
    handleGisCredential?: (response: { credential: string }) => void
  }
}

export function SignInPage() {
  const setSignedIn = useAuthStore((s) => s.setSignedIn)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const buttonRef = useRef<HTMLDivElement>(null)

  // Google OAuth Client ID — must be set as an env var at build time.
  // Vite exposes VITE_GOOGLE_CLIENT_ID from .env as import.meta.env.VITE_GOOGLE_CLIENT_ID.
  const clientId =
    typeof import.meta !== 'undefined' &&
    (import.meta as { env?: Record<string, string> }).env?.VITE_GOOGLE_CLIENT_ID || ''

  const handleCredential = async (response: { credential: string }) => {
    setLoading(true)
    setError(null)
    try {
      const result = await signInWithGoogle(response.credential)
      if (result.ok && result.email) {
        setSignedIn(result.email)
      } else {
        setError('Sign-in failed. Please try again.')
      }
    } catch {
      setError('Sign-in failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Expose the callback globally so the GIS script can call it
    window.handleGisCredential = handleCredential

    const initGis = () => {
      if (!window.google?.accounts?.id) return
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: handleCredential,
        auto_select: false,
      })
      if (buttonRef.current) {
        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: 'filled_black',
          size: 'large',
          type: 'standard',
          text: 'signin_with',
        })
      }
    }

    // If GIS script is already loaded, initialize immediately
    if (window.google?.accounts?.id) {
      initGis()
      return
    }

    // Otherwise, load the GIS script and initialize on load
    const script = document.createElement('script')
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.defer = true
    script.onload = initGis
    document.head.appendChild(script)

    return () => {
      // Clean up the global callback reference
      delete window.handleGisCredential
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId])

  return (
    <div
      style={{
        minHeight: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#0A0A0A',
        padding: '16px',
      }}
    >
      {/* Wordmark */}
      <h1
        style={{
          fontSize: '28px',
          fontWeight: 600,
          lineHeight: 1.15,
          color: '#F9FAFB',
          margin: 0,
          marginBottom: '8px',
          letterSpacing: '-0.01em',
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
        }}
      >
        Klaus
      </h1>

      {/* Subheading */}
      <p
        style={{
          fontSize: '16px',
          fontWeight: 400,
          lineHeight: 1.5,
          color: '#9CA3AF',
          margin: 0,
          marginBottom: '40px',
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
        }}
      >
        Your personal agent
      </p>

      {/* Google Sign-In button — rendered by GIS SDK */}
      <div
        ref={buttonRef}
        id="g_id_signin_btn"
        style={{ minHeight: '44px' }} // iOS HIG minimum touch target
      />

      {/* Loading state */}
      {loading && (
        <p
          style={{
            marginTop: '16px',
            fontSize: '13px',
            color: '#9CA3AF',
            fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          }}
        >
          Signing in…
        </p>
      )}

      {/* Error state */}
      {error && (
        <p
          style={{
            marginTop: '16px',
            fontSize: '13px',
            color: '#EF4444',
            fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          }}
          role="alert"
        >
          {error}
        </p>
      )}
    </div>
  )
}
