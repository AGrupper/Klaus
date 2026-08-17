/**
 * Header.tsx — the app's single top bar: date, desktop tabs, gear, bell.
 *
 * Phone (<md): [date ......................... gear, bell]
 * Desktop (md+): [date ... (Today | Routines) ... gear, bell]
 *
 * Desktop tab visibility is class-driven (`hidden md:flex`) — never inline
 * display (Pitfall 2 / T-28-display).
 */
import { useLocation, useNavigate } from 'react-router-dom'
import { Bell, Settings2 } from 'lucide-react'
import { useTapGuard } from '../../hooks/useTapGuard'
import { tapFeedback } from '../../utils/haptics'

const DATE_FORMAT = new Intl.DateTimeFormat('en-US', {
  weekday: 'long',
  month: 'long',
  day: 'numeric',
})

interface HeaderProps {
  unread: number
  onOpenBell: () => void
  onOpenCustomize: () => void
}

function HeaderButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  // Pull-to-refresh often starts with a thumb on these buttons, and iOS still
  // fires a click on release — which was opening Customize on every pull
  // (Amit's UAT). useTapGuard swallows a click that travelled.
  const guard = useTapGuard(() => {
    tapFeedback()
    onClick()
  })
  return (
    <button
      {...guard}
      aria-label={label}
      className="press"
      style={{
        // The header does not scroll, so a touch starting here has nothing to
        // pan. `none` stops the browser handing the gesture to a scroller at
        // all — which is what produced the cancelled-gesture click that kept
        // opening Customize on every pull-down.
        touchAction: 'none',
        position: 'relative',
        width: '38px',
        height: '38px',
        borderRadius: '50%',
        border: 'none',
        background: 'var(--surface)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--ink)',
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  )
}

export function Header({ unread, onOpenBell, onOpenCustomize }: HeaderProps) {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '16px 20px 0',
      }}
    >
      <span
        style={{
          fontSize: '12.5px',
          color: 'var(--muted)',
          fontWeight: 600,
          marginRight: 'auto',
        }}
      >
        {DATE_FORMAT.format(new Date())}
      </span>

      {/* Desktop tabs — phone uses the bottom TabBar */}
      <nav className="hidden md:flex" style={{ gap: '4px', marginRight: '8px' }} aria-label="Sections">
        {[
          { label: 'Today', path: '/' },
          { label: 'Routines', path: '/routines' },
        ].map(({ label, path }) => {
          const active =
            path === '/' ? location.pathname === '/' : location.pathname.startsWith(path)
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              aria-current={active ? 'page' : undefined}
              className="press"
              style={{
                border: 'none',
                borderRadius: '999px',
                transition: 'background 0.2s var(--ease), color 0.2s var(--ease)',
                padding: '7px 14px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
                background: active ? 'var(--accent)' : 'var(--surface)',
                color: active ? 'var(--accent-ink)' : 'var(--muted)',
              }}
            >
              {label}
            </button>
          )
        })}
      </nav>

      <HeaderButton label="Customize" onClick={onOpenCustomize}>
        <Settings2 size={18} strokeWidth={1.8} aria-hidden="true" />
      </HeaderButton>
      <HeaderButton label={unread > 0 ? `Notifications, ${unread} new` : 'Notifications'} onClick={onOpenBell}>
        <Bell size={19} strokeWidth={1.8} aria-hidden="true" />
        {unread > 0 && (
          <span
            style={{
              position: 'absolute',
              top: '7px',
              right: '8px',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: 'var(--flame)',
              border: '2px solid var(--ground)',
            }}
            aria-hidden="true"
          />
        )}
      </HeaderButton>
    </div>
  )
}
