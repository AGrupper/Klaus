/**
 * App.tsx — Route guard + top-level routing.
 *
 * On mount: calls fetchMe() via useQuery to check the session cookie.
 *   - Loading  → minimal centered spinner on #0A0A0A
 *   - 401/err  → SignInPage (from 26-03)
 *   - Success  → sets zustand auth store + renders AppShell with nested routes
 *
 * Routes:
 *   /         → Today timeline placeholder (real content: 26-07)
 *   /tasks    → Placeholder — owned by P27
 *   /klaus    → Chat placeholder (real content: 26-08)
 *   /habits   → Placeholder — owned by P28
 *   /health   → Placeholder — owned by P30
 *
 * Security note: this route guard is a UX gate only. Every /api/* route
 * enforces require_hub_session server-side (26-03). A bypassed guard returns 401.
 */
import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchMe } from './api/auth'
import { useAuthStore } from './store/auth'
import { SignInPage } from './components/auth/SignInPage'
import { AppShell } from './components/layout/AppShell'
import { TimelineDay } from './components/timeline/TimelineDay'
import { dominant, textSecondary, typography } from './tokens'

// ---------------------------------------------------------------------------
// Placeholder pages for routes owned by later plans
// ---------------------------------------------------------------------------

function ComingSoon({ label }: { label: string }) {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: textSecondary,
        fontSize: typography.body.fontSize,
        fontWeight: typography.body.fontWeight,
        fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
      }}
    >
      {label} — Coming soon
    </div>
  )
}

function TodayPage() {
  return <TimelineDay />
}

function TasksPage() {
  return <ComingSoon label="Tasks" />
}

function KlausPage() {
  return <ComingSoon label="Chat" />
}

function HabitsPage() {
  return <ComingSoon label="Habits" />
}

function HealthPage() {
  return <ComingSoon label="Health" />
}

// ---------------------------------------------------------------------------
// Minimal spinner shown while the session check is in-flight
// ---------------------------------------------------------------------------

function LoadingScreen() {
  return (
    <div
      style={{
        minHeight: '100dvh',
        backgroundColor: dominant,
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
          border: '3px solid #2A2A2A',
          borderTopColor: '#6366F1',
          borderRadius: '50%',
          animation: 'spin 0.75s linear infinite',
        }}
      />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

export default function App() {
  const setSignedIn = useAuthStore((s) => s.setSignedIn)
  const signOut = useAuthStore((s) => s.signOut)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: fetchMe,
    retry: false,        // a 401 is not a transient failure — don't retry
    staleTime: Infinity, // session doesn't change mid-session
  })

  // Sync the zustand store when auth check resolves
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

  if (isLoading) {
    return <LoadingScreen />
  }

  if (isError || !data?.email) {
    return <SignInPage />
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<TodayPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/klaus" element={<KlausPage />} />
        <Route path="/habits" element={<HabitsPage />} />
        <Route path="/health" element={<HealthPage />} />
        {/* Catch-all: redirect unknown paths to Today */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
