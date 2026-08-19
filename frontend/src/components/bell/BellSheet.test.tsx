/**
 * BellSheet.test.tsx — rows mark themselves read when they come into view.
 *
 * Amit's report (2026-08-19): "when I open it, it doesn't automatically mark
 * what I interact with as read" — tapping a row only ever dismissed the push,
 * never the read state — "and I'd like it to mark the things I can see in my
 * direct vicinity as read".
 *
 * jsdom has no IntersectionObserver, so these tests install a stub that hands
 * back the callback; firing it is what "the row scrolled into view" means here.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as notificationsApi from '../../api/notifications'
import * as settingsApi from '../../api/settings'
import * as agentApi from '../../api/agent'
import { itemKey, type BellItem } from '../../api/notifications'
import { BellSheet } from './BellSheet'

// ---------------------------------------------------------------------------
// IntersectionObserver stub
// ---------------------------------------------------------------------------

interface StubObserver {
  callback: IntersectionObserverCallback
  elements: Set<Element>
}

let observers: StubObserver[] = []

function installObserverStub() {
  observers = []
  class Stub {
    private record: StubObserver
    constructor(callback: IntersectionObserverCallback) {
      this.record = { callback, elements: new Set() }
      observers.push(this.record)
    }
    observe(el: Element) {
      this.record.elements.add(el)
    }
    unobserve(el: Element) {
      this.record.elements.delete(el)
    }
    disconnect() {
      this.record.elements.clear()
    }
    takeRecords() {
      return []
    }
  }
  vi.stubGlobal('IntersectionObserver', Stub)
}

/** Fire the observer for every element matching `predicate`, as intersecting. */
function scrollIntoView(predicate: (el: Element) => boolean) {
  for (const observer of observers) {
    const entries = [...observer.elements]
      .filter(predicate)
      .map((target) => ({ target, isIntersecting: true }) as IntersectionObserverEntry)
    if (entries.length > 0) {
      observer.callback(entries, {} as IntersectionObserver)
    }
  }
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function item(id: string, at: string, over: Partial<BellItem> = {}): BellItem {
  return {
    id,
    type: 'alert',
    title: id,
    body: null,
    at,
    claude_session_url: null,
    routine: null,
    target_date: null,
    push_tag: null,
    ...over,
  }
}

const TOP = item('top', '2026-08-18T10:00:00')
const BOTTOM = item('bottom', '2026-08-18T09:00:00')
const ITEMS = [TOP, BOTTOM]

function settings(readIds: string[] = []): settingsApi.HubSettings {
  return {
    push_enabled_at: null,
    appearance: { accent: '#1C2540', flame: '#B02A2A', font: 'default' },
    home_sections: { leaveby: true, stats: true, corner: true, portfolio: false },
    bell_last_seen: null,
    bell_read_ids: readIds,
  }
}

let queryClient: QueryClient

function Harness({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

function renderSheet() {
  return render(
    <Harness>
      <BellSheet open onClose={() => {}} items={ITEMS} loading={false} />
    </Harness>,
  )
}

function row(target: BellItem) {
  return screen.getByTestId(`bell-row-${itemKey(target)}`)
}

beforeEach(() => {
  localStorage.clear()
  installObserverStub()
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  vi.spyOn(notificationsApi, 'fetchNotifications').mockResolvedValue(ITEMS)
  vi.spyOn(settingsApi, 'fetchSettings').mockResolvedValue(settings())
  vi.spyOn(settingsApi, 'patchSettings').mockResolvedValue(settings())
  vi.spyOn(agentApi, 'fetchAgentStatus').mockResolvedValue({
    claude_project_url: 'https://claude.ai/project/x',
  } as Awaited<ReturnType<typeof agentApi.fetchAgentStatus>>)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('BellSheet read marking', () => {
  it('renders every row unread before anything is seen', async () => {
    renderSheet()
    await waitFor(() => expect(row(TOP)).toHaveAttribute('data-unread', 'true'))
    expect(row(BOTTOM)).toHaveAttribute('data-unread', 'true')
  })

  it('marks a row read as soon as it scrolls into view', async () => {
    renderSheet()
    await waitFor(() => expect(row(TOP)).toHaveAttribute('data-unread', 'true'))

    act(() => scrollIntoView((el) => el === row(TOP)))

    await waitFor(() => expect(row(TOP)).toHaveAttribute('data-unread', 'false'))
  })

  it('leaves a row below the fold unread', async () => {
    renderSheet()
    await waitFor(() => expect(row(TOP)).toHaveAttribute('data-unread', 'true'))

    act(() => scrollIntoView((el) => el === row(TOP)))

    await waitFor(() => expect(row(TOP)).toHaveAttribute('data-unread', 'false'))
    expect(row(BOTTOM)).toHaveAttribute('data-unread', 'true')
  })

  it('marks a row read when its action is tapped', async () => {
    renderSheet()
    await waitFor(() => expect(row(BOTTOM)).toHaveAttribute('data-unread', 'true'))

    fireEvent.click(screen.getAllByText('Open in Today')[1])

    await waitFor(() => expect(row(BOTTOM)).toHaveAttribute('data-unread', 'false'))
  })

  it('marks everything read from the Mark all read button', async () => {
    renderSheet()
    await waitFor(() => expect(row(TOP)).toHaveAttribute('data-unread', 'true'))

    fireEvent.click(screen.getByText('Mark all read'))

    await waitFor(() => expect(row(TOP)).toHaveAttribute('data-unread', 'false'))
    expect(row(BOTTOM)).toHaveAttribute('data-unread', 'false')
  })
})
