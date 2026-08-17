/**
 * AppShell.tsx — root layout for the Paper Hub.
 *
 * One column, phone-first: Header (date · desktop tabs · gear · bell) over a
 * scrolling main region, with the phone TabBar fixed at the bottom. Desktop
 * is the same screens centered in a 560px column (tabs move into the header).
 *
 * The two global sheets (Bell, Customize) mount here so they overlay any
 * route; their open state is local to the shell, and the bell's unread dot
 * clears when the sheet opens (markSeen).
 *
 * Bounded-height root: `height: 100dvh` (not min-height) so <main> stays the
 * real scroll container (UAT gap-closure lesson, Phase 26).
 */
import { useState, type ReactNode } from 'react'
import { Header } from './Header'
import { TabBar } from './TabBar'
import { BellSheet } from '../bell/BellSheet'
import { CustomizeSheet } from '../customize/CustomizeSheet'
import { OfflineIndicator } from '../shared/OfflineIndicator'
import { InstallBanner } from '../shared/InstallBanner'
import { UpdatePrompt } from '../shared/UpdatePrompt'
import { UndoToast } from '../shared/UndoToast'
import { useNotifications } from '../../hooks/useNotifications'
import { useSettings } from '../../hooks/useSettings'

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const [bellOpen, setBellOpen] = useState(false)
  const [customizeOpen, setCustomizeOpen] = useState(false)
  const notifications = useNotifications()

  // Load once at the shell so the account theme applies before any page needs it.
  useSettings()

  function openBell() {
    setBellOpen(true)
    notifications.markSeen()
  }

  return (
    <div
      style={{
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--ground)',
      }}
    >
      <OfflineIndicator />
      <UpdatePrompt />
      <InstallBanner />

      {/* Centered column — full width on phone, 560px on desktop */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          width: '100%',
          maxWidth: '560px',
          margin: '0 auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Header
          unread={notifications.unread}
          onOpenBell={openBell}
          onOpenCustomize={() => setCustomizeOpen(true)}
        />
        <main
          className="hub-main"
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {children}
        </main>
      </div>

      <TabBar />
      <UndoToast />

      <BellSheet
        open={bellOpen}
        onClose={() => setBellOpen(false)}
        items={notifications.items}
        loading={notifications.isLoading}
      />
      <CustomizeSheet open={customizeOpen} onClose={() => setCustomizeOpen(false)} />
    </div>
  )
}
