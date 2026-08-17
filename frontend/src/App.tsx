/**
 * App.tsx — route guard + top-level routing (Paper Hub).
 *
 * On mount: fetchMe() checks the session cookie.
 *   - Loading  → centered spinner on the paper ground
 *   - 401/err  → SignInPage
 *   - Success  → AppShell with the three routes
 *
 * Routes:
 *   /          → HomePage (day glance, Talk to Klaus, timeline)
 *   /routines  → RoutinesPage (ring cards + flames)
 *   /settings  → SettingsPage (push, system, sign-out)
 *
 * SW → router bridge (D-12, Phase 29): notificationclick posts
 * {type:'NAVIGATE', path} — a notification tap opens Today; the bell in the
 * header is the hop to the item itself.
 *
 * Security note: this guard is a UX gate only — every /api/* route enforces
 * require_hub_session server-side. A bypassed guard returns 401s.
 */
import { useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchMe } from './api/auth'
import { useAuthStore } from './store/auth'
import { SignInPage } from './components/auth/SignInPage'
import { AppShell } from './components/layout/AppShell'
import { HomePage } from './components/home/HomePage'
import { RoutinesPage } from './components/routines/RoutinesPage'
import { SettingsPage } from './components/settings/SettingsPage'

function LoadingScreen() {
  return (
    <div
      style={{
        minHeight: '100dvh',
        backgroundColor: 'var(--ground)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      aria-label="Loading…"
    >
      <div
        style={{
          width: '32px',
          height: '32px',
          border: '3px solid var(--sep)',
          borderTopColor: 'var(--accent)',
          borderRadius: '50%',
          animation: 'spin 0.75s linear infinite',
        }}
      />
    </div>
  )
}

export default function App() {
  const setSignedIn = useAuthStore((s) => s.setSignedIn)
  const signOut = useAuthStore((s) => s.signOut)
  const navigate = useNavigate()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: fetchMe,
    retry: false,        // a 401 is not a transient failure — don't retry
    staleTime: Infinity, // session doesn't change mid-session
  })

  useEffect(() => {
    if (data?.email) {
      setSignedIn(data.email)
    }
  }, [data, setSignedIn])

  useEffect(() => {
    if (isError) {
      signOut()
    }
  }, [isError, signOut])

  // SW → router bridge (D-12). Guarded: serviceWorker may be undefined
  // (unsupported browser, non-secure context) or absent in jsdom.
  useEffect(() => {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
    const handleMessage = (event: MessageEvent) => {
      const message = event.data as { type?: string; path?: string } | undefined
      if (message?.type === 'NAVIGATE') {
        navigate(message.path ?? '/')
      }
    }
    navigator.serviceWorker.addEventListener('message', handleMessage)
    return () => navigator.serviceWorker.removeEventListener('message', handleMessage)
  }, [navigate])

  if (isLoading) {
    return <LoadingScreen />
  }

  if (isError || !data?.email) {
    return <SignInPage />
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/routines" element={<RoutinesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        {/* Old bookmarked paths (tasks/health/klaus) land on Today */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
