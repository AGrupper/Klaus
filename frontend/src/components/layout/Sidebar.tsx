/**
 * Sidebar.tsx — Desktop-only icon navigation bar (hidden on phone).
 *
 * UI-SPEC constraints:
 *   - 64px wide, full height, #0A0A0A background
 *   - "Klaus" wordmark at Display (28px/600) at top
 *   - Icon-only nav buttons (lucide-react); each carries:
 *       title="{label}" and <span className="sr-only">{label}</span>
 *   - Active icon in accent #6366F1; inactive icons in textSecondary #9CA3AF
 *   - Footer: "Sign out" + "Sign out everywhere" (with confirmation modal, destructive #EF4444)
 *   - Hidden on phone: className="hidden md:flex"
 */
import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  CalendarDays,
  CheckSquare,
  MessageCircle,
  Activity,
  Heart,
  LogOut,
  ShieldOff,
  X,
} from 'lucide-react'
import { logout, revokeAll } from '../../api/auth'
import { useAuthStore } from '../../store/auth'

interface NavItem {
  label: string
  path: string
  icon: typeof CalendarDays
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Today', path: '/', icon: CalendarDays },
  { label: 'Tasks', path: '/tasks', icon: CheckSquare },
  { label: 'Klaus', path: '/klaus', icon: MessageCircle },
  { label: 'Habits', path: '/habits', icon: Activity },
  { label: 'Health', path: '/health', icon: Heart },
]

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const signOut = useAuthStore((s) => s.signOut)
  const [showRevokeModal, setShowRevokeModal] = useState(false)
  const [revoking, setRevoking] = useState(false)

  const handleSignOut = async () => {
    try {
      await logout()
    } catch {
      // swallow — redirect regardless
    }
    signOut()
    navigate('/', { replace: true })
    window.location.href = '/?signin=required'
  }

  const handleRevokeAll = async () => {
    setRevoking(true)
    try {
      await revokeAll()
    } catch {
      // swallow — redirect regardless
    }
    signOut()
    setShowRevokeModal(false)
    window.location.href = '/?signin=required'
  }

  return (
    <>
      {/*
       * Sidebar column.
       * hidden md:flex — desktop only; hides on phone.
       * flex-col: vertical stack of icon buttons.
       */}
      <nav
        className="hidden md:flex flex-col items-center justify-between"
        style={{
          width: '64px',
          minHeight: '100dvh',
          backgroundColor: '#0A0A0A',
          borderRight: '1px solid #2A2A2A',
          padding: '16px 0',
          flexShrink: 0,
        }}
        aria-label="Main navigation"
      >
        {/* Top: wordmark */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '24px', width: '100%' }}>
          {/* Klaus wordmark — Display (28px/600) */}
          <div
            aria-label="Klaus"
            style={{
              fontSize: '28px',
              fontWeight: 600,
              lineHeight: 1.15,
              color: '#F9FAFB',
              letterSpacing: '-0.01em',
              fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
              cursor: 'default',
              paddingBottom: '8px',
              borderBottom: '1px solid #2A2A2A',
              width: '100%',
              textAlign: 'center',
            }}
          >
            K
          </div>

          {/* Nav buttons */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', width: '100%' }}>
            {NAV_ITEMS.map(({ label, path, icon: Icon }) => {
              // Active if exact match for "/" or prefix match otherwise
              const isActive =
                path === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(path)

              return (
                <button
                  key={path}
                  title={label}
                  onClick={() => navigate(path)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '48px',
                    height: '48px',
                    borderRadius: '8px',
                    border: 'none',
                    cursor: 'pointer',
                    backgroundColor: isActive ? 'rgba(99, 102, 241, 0.12)' : 'transparent',
                    color: isActive ? '#6366F1' : '#9CA3AF',
                    transition: 'background-color 0.15s, color 0.15s',
                  }}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <Icon size={22} strokeWidth={1.75} aria-hidden="true" />
                  <span className="sr-only">{label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Footer: sign-out controls */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
          {/* Sign out everywhere (destructive, behind modal) */}
          <button
            title="Sign out everywhere"
            onClick={() => setShowRevokeModal(true)}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              width: '48px',
              height: '48px',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
              backgroundColor: 'transparent',
              color: '#9CA3AF',
              transition: 'color 0.15s',
            }}
          >
            <ShieldOff size={18} strokeWidth={1.75} aria-hidden="true" />
            <span className="sr-only">Sign out everywhere</span>
          </button>

          {/* Sign out (single device) */}
          <button
            title="Sign out"
            onClick={handleSignOut}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              width: '48px',
              height: '48px',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
              backgroundColor: 'transparent',
              color: '#9CA3AF',
              transition: 'color 0.15s',
            }}
          >
            <LogOut size={18} strokeWidth={1.75} aria-hidden="true" />
            <span className="sr-only">Sign out</span>
          </button>
        </div>
      </nav>

      {/* Sign out everywhere — confirmation modal */}
      {showRevokeModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="revoke-modal-heading"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '16px',
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowRevokeModal(false)
          }}
        >
          <div
            style={{
              backgroundColor: '#1A1A1A',
              border: '1px solid #2A2A2A',
              borderRadius: '12px',
              padding: '24px',
              maxWidth: '360px',
              width: '100%',
              position: 'relative',
            }}
          >
            {/* Close button */}
            <button
              onClick={() => setShowRevokeModal(false)}
              aria-label="Close"
              style={{
                position: 'absolute',
                top: '12px',
                right: '12px',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: '#9CA3AF',
                padding: '4px',
              }}
            >
              <X size={18} aria-hidden="true" />
            </button>

            <h2
              id="revoke-modal-heading"
              style={{
                fontSize: '20px',
                fontWeight: 600,
                lineHeight: 1.2,
                color: '#F9FAFB',
                margin: '0 0 8px',
                fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
              }}
            >
              Sign out of all devices?
            </h2>
            <p
              style={{
                fontSize: '16px',
                fontWeight: 400,
                lineHeight: 1.5,
                color: '#9CA3AF',
                margin: '0 0 24px',
                fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
              }}
            >
              This will end all active sessions, including on your phone.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {/* Destructive CTA */}
              <button
                onClick={handleRevokeAll}
                disabled={revoking}
                style={{
                  height: '44px',
                  backgroundColor: '#EF4444',
                  color: '#F9FAFB',
                  border: 'none',
                  borderRadius: '8px',
                  fontSize: '16px',
                  fontWeight: 600,
                  cursor: revoking ? 'not-allowed' : 'pointer',
                  opacity: revoking ? 0.6 : 1,
                  fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
                }}
              >
                {revoking ? 'Signing out…' : 'Sign out everywhere'}
              </button>

              {/* Cancel */}
              <button
                onClick={() => setShowRevokeModal(false)}
                disabled={revoking}
                style={{
                  height: '44px',
                  backgroundColor: 'transparent',
                  color: '#9CA3AF',
                  border: '1px solid #2A2A2A',
                  borderRadius: '8px',
                  fontSize: '16px',
                  fontWeight: 400,
                  cursor: 'pointer',
                  fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
                }}
              >
                Stay signed in
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
