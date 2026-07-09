/**
 * App.tsx — Route guard + top-level routing.
 *
 * On mount: calls fetchMe() via useQuery to check the session cookie.
 *   - Loading  → minimal centered spinner on #0A0A0A
 *   - 401/err  → SignInPage (from 26-03)
 *   - Success  → sets zustand auth store + renders AppShell with nested routes
 *
 * Routes:
 *   /         → Today timeline (real content: 26-07)
 *   /tasks    → TasksPage (real content: 27-05)
 *   /klaus    → ChatWindow (real content: 26-08)
 *   /habits   → Placeholder — owned by P28
 *   /health   → Placeholder — owned by P30
 *   /settings → SettingsPage (enable-push + Telegram-mirror toggle, D-15: Phase 29)
 *
 * SW → router bridge (D-12, Phase 29): a `navigator.serviceWorker` 'message'
 * listener calls `navigate(event.data.path ?? '/')` on `{type:'NAVIGATE'}` —
 * a notification tap always opens Today, never chat (sw.ts posts this on
 * notificationclick).
 *
 * Security note: this route guard is a UX gate only. Every /api/* route
 * enforces require_hub_session server-side (26-03). A bypassed guard returns 401.
 */
import { useEffect } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchMe } from './api/auth'
import { useAuthStore } from './store/auth'
import { SignInPage } from './components/auth/SignInPage'
import { AppShell } from './components/layout/AppShell'
import { TimelineDay } from './components/timeline/TimelineDay'
import { ChatWindow } from './components/chat/ChatWindow'
import { dominant, textSecondary, typography } from './tokens'
import { TasksPage as TasksPageComponent } from './components/tasks/TasksPage'
import { HabitsPage as HabitsPageComponent } from './components/habits/HabitsPage'
import { HealthPage as HealthPageComponent } from './components/health/HealthPage'
import { SettingsPage as SettingsPageComponent } from './components/settings/SettingsPage'
import { PushEnableBanner } from './components/shared/PushEnableBanner'

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
  return (
    <>
      <TimelineDay />
      {/* First-run push enable banner (D-16) / re-enable notice (D-19) */}
      <PushEnableBanner />
    </>
  )
}

function TasksPage() {
  return <TasksPageComponent />
}

/**
 * KlausPage — Full-screen chat on phone (/klaus route).
 * ChatWindow polls while this page is mounted (isVisible=true default).
 * On desktop, the DockChat panel shows the same chat; on phone this is
 * the primary interface.
 */
function KlausPage() {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <ChatWindow isVisible={true} />
    </div>
  )
}

function HabitsPage() {
  return <HabitsPageComponent />
}

function HealthPage() {
  return <HealthPageComponent />
}

function SettingsPage() {
  return <SettingsPageComponent />
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
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

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

  // SW → router bridge (D-12): notificationclick posts {type:'NAVIGATE', path}
  // — a tap always opens Today, never chat. Guarded: serviceWorker may be
  // undefined (unsupported browser, non-secure context) or absent in jsdom.
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
        <Route path="/" element={<TodayPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/klaus" element={<KlausPage />} />
        <Route path="/habits" element={<HabitsPage />} />
        <Route path="/health" element={<HealthPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        {/* Catch-all: redirect unknown paths to Today */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
