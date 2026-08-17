/**
 * AppShell.tsx — root layout for the Paper Hub.
 *
 * One column, phone-first: Header (date · desktop tabs · gear · bell) over a
 * scrolling main region, with the phone TabBar fixed at the bottom. Desktop
 * is the same screens centered in a 560px column (tabs move into the header).
 *
 * The two global sheets (Bell, Customize) mount here so they overlay any
 * route; their open state is local to the shell. The unread dot clears only
 * on an explicit "Mark all read" inside the sheet.
 *
 * Bounded-height root: `height: 100dvh` (not min-height) so <main> stays the
 * real scroll container (UAT gap-closure lesson, Phase 26).
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Header } from './Header'
import { TabBar } from './TabBar'
import { BellSheet } from '../bell/BellSheet'
import { CustomizeSheet } from '../customize/CustomizeSheet'
import { OfflineIndicator } from '../shared/OfflineIndicator'
import { InstallBanner } from '../shared/InstallBanner'
import { UpdatePrompt } from '../shared/UpdatePrompt'
import { UndoToast } from '../shared/UndoToast'
import { PullToRefresh } from '../shared/PullToRefresh'
import { useNotifications } from '../../hooks/useNotifications'
import { useSettings } from '../../hooks/useSettings'

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const [bellOpen, setBellOpen] = useState(false)
  const [customizeOpen, setCustomizeOpen] = useState(false)
  const notifications = useNotifications()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  // Load once at the shell so the account theme applies before any page needs it.
  useSettings()

  /** Pull down anywhere in the app to refetch everything it shows. */
  const refresh = useCallback(
    () =>
      queryClient.refetchQueries({
        type: 'active',
        queryKey: undefined, // every live query: today, routines, bell, settings
      }),
    [queryClient],
  )

  // Opening the bell deliberately does NOT clear the unread dot — "Mark all
  // read" inside the sheet is the explicit gesture (it also clears delivered
  // notifications from the lock screen).
  function openBell() {
    setBellOpen(true)
  }

  // ?bell=1 — how a review notification tap arrives (see App.tsx routes).
  // Consume the param so a later refresh doesn't reopen the sheet.
  useEffect(() => {
    if (searchParams.get('bell') !== '1') return
    setBellOpen(true)
    const next = new URLSearchParams(searchParams)
    next.delete('bell')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

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
        <PullToRefresh
          onRefresh={refresh}
          className="hub-main"
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            overflowX: 'hidden',
            WebkitOverflowScrolling: 'touch',
            // Keep the gesture inside this scroller — the document must never
            // rubber-band, or fixed elements ride along with it.
            overscrollBehaviorY: 'contain',
          }}
        >
          {children}
        </PullToRefresh>
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
