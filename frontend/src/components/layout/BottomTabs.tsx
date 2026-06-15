/**
 * BottomTabs.tsx — Phone-only fixed bottom tab bar.
 *
 * UI-SPEC constraints:
 *   - Phone only: className="md:hidden" — not visible on desktop
 *   - 64px height, #1A1A1A background
 *   - 5 tabs: Today · Tasks · Klaus · Habits · Health (Klaus center)
 *   - Each tab touch target >= 44px (iOS HIG)
 *   - Active icon in accent #6366F1; inactive in textSecondary #9CA3AF
 *   - UnreadBadge slot on Klaus tab (component arrives in 26-08; placeholder slot here)
 */
import { useNavigate, useLocation } from 'react-router-dom'
import {
  CalendarDays,
  CheckSquare,
  MessageCircle,
  Activity,
  Heart,
} from 'lucide-react'

interface TabItem {
  label: string
  path: string
  icon: typeof CalendarDays
}

const TABS: TabItem[] = [
  { label: 'Today', path: '/', icon: CalendarDays },
  { label: 'Tasks', path: '/tasks', icon: CheckSquare },
  { label: 'Klaus', path: '/klaus', icon: MessageCircle },
  { label: 'Habits', path: '/habits', icon: Activity },
  { label: 'Health', path: '/health', icon: Heart },
]

export function BottomTabs() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    /*
     * md:hidden — phone only. desktop uses Sidebar.
     * fixed bottom bar: above safe-area inset on iOS.
     */
    <nav
      className="md:hidden"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: '64px',
        backgroundColor: '#1A1A1A',
        borderTop: '1px solid #2A2A2A',
        display: 'flex',
        alignItems: 'stretch',
        zIndex: 100,
        // Safe-area inset for iPhone notch/home indicator
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
      }}
      aria-label="Main navigation"
    >
      {TABS.map(({ label, path, icon: Icon }) => {
        const isKlaus = label === 'Klaus'
        const isActive =
          path === '/'
            ? location.pathname === '/'
            : location.pathname.startsWith(path)

        return (
          <button
            key={path}
            onClick={() => navigate(path)}
            title={label}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '44px', // iOS HIG touch target
              gap: '2px',
              border: 'none',
              backgroundColor: 'transparent',
              cursor: 'pointer',
              color: isActive ? '#6366F1' : '#9CA3AF',
              position: 'relative',
              transition: 'color 0.15s',
            }}
            aria-current={isActive ? 'page' : undefined}
          >
            {/* UnreadBadge slot — placeholder for 26-08 */}
            {isKlaus && (
              <div
                id="bottom-tab-unread-badge-slot"
                style={{ position: 'absolute', top: '8px', right: 'calc(50% - 18px)' }}
                aria-hidden="true"
              />
            )}

            <Icon size={24} strokeWidth={1.75} aria-hidden="true" />
            <span
              style={{
                fontSize: '10px',
                fontWeight: 400,
                lineHeight: 1.2,
                fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
              }}
            >
              {label}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
