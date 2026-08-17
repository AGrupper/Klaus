/**
 * TabBar.tsx — phone-only fixed bottom tab bar: Today · Routines.
 *
 * Display comes from `flex md:hidden` classes — NEVER inline `display`
 * (Pitfall 2 / T-28-display: an inline value overrides md:hidden and leaks
 * the bar onto desktop). Sits at z:100; sheets go above at 400+.
 */
import { useLocation, useNavigate } from 'react-router-dom'
import { Flame, House } from 'lucide-react'

const TABS = [
  { label: 'Today', path: '/', icon: House },
  { label: 'Routines', path: '/routines', icon: Flame },
]

export function TabBar() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <nav
      className="flex md:hidden"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        background: 'color-mix(in srgb, var(--ground) 88%, transparent)',
        WebkitBackdropFilter: 'blur(14px)',
        backdropFilter: 'blur(14px)',
        borderTop: '1px solid var(--sep)',
        padding: '7px 0 max(9px, env(safe-area-inset-bottom))',
        zIndex: 100,
      }}
      aria-label="Main navigation"
    >
      {TABS.map(({ label, path, icon: Icon }) => {
        const active =
          path === '/' ? location.pathname === '/' : location.pathname.startsWith(path)
        return (
          <button
            key={path}
            onClick={() => navigate(path)}
            aria-current={active ? 'page' : undefined}
            style={{
              flex: 1,
              border: 'none',
              background: 'none',
              color: active ? 'var(--accent)' : 'var(--faint)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '3px',
              fontSize: '10.5px',
              fontWeight: 600,
              padding: '4px 0',
              minHeight: '44px',
              cursor: 'pointer',
            }}
          >
            <Icon size={21} strokeWidth={1.8} aria-hidden="true" />
            {label}
          </button>
        )
      })}
    </nav>
  )
}
