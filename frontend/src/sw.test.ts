/**
 * Custom service worker tests.
 *
 * These tests mock the minimal `self`/`navigator` service-worker globals
 * needed to exercise the handlers registered by `sw.ts`, without a real
 * browser SW context. `self.indexedDB` is intentionally left undefined
 * (its natural state in this jsdom test environment) so the badge-increment
 * step inside the push handler throws — proving the notification still
 * fires unconditionally (T-29-13 / iOS 3-strikes rule).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Listener = (event: unknown) => void

function getListener(
  listeners: Map<string, Listener[]>,
  type: string,
): Listener {
  const registered = listeners.get(type)
  if (!registered || registered.length === 0) {
    throw new Error(`No listener registered for "${type}"`)
  }
  return registered[registered.length - 1]
}

describe('sw.ts', () => {
  let listeners: Map<string, Listener[]>
  let showNotification: ReturnType<typeof vi.fn>
  let skipWaiting: ReturnType<typeof vi.fn>
  let matchAll: ReturnType<typeof vi.fn>
  let openWindow: ReturnType<typeof vi.fn>
  let getNotifications: ReturnType<typeof vi.fn>

  beforeEach(async () => {
    vi.resetModules()
    listeners = new Map()
    showNotification = vi.fn().mockResolvedValue(undefined)
    skipWaiting = vi.fn()
    matchAll = vi.fn().mockResolvedValue([])
    openWindow = vi.fn().mockResolvedValue(undefined)
    getNotifications = vi.fn().mockResolvedValue([])

    // Precache manifest is normally injected at build time by injectManifest;
    // stub it as empty so precacheAndRoute() doesn't need a real array.
    vi.stubGlobal('__WB_MANIFEST_STUB__', [])
    Object.defineProperty(globalThis, '__WB_MANIFEST', {
      value: [],
      configurable: true,
      writable: true,
    })

    const addEventListener = vi.fn((type: string, listener: Listener) => {
      const existing = listeners.get(type) ?? []
      existing.push(listener)
      listeners.set(type, existing)
    })
    vi.stubGlobal('addEventListener', addEventListener)
    Object.defineProperty(globalThis, 'skipWaiting', {
      value: skipWaiting,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(globalThis, 'registration', {
      value: { showNotification, getNotifications },
      configurable: true,
      writable: true,
    })
    Object.defineProperty(globalThis, 'clients', {
      value: { matchAll, openWindow },
      configurable: true,
      writable: true,
    })
    // self.indexedDB is intentionally NOT stubbed — jsdom leaves it
    // undefined, which makes the badge-increment path throw naturally.

    await import('./sw')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('push handler always calls showNotification, even when the badge step throws', async () => {
    const pushListener = getListener(listeners, 'push')
    const waitUntilPromises: Promise<unknown>[] = []
    const event = {
      data: {
        json: () => ({ title: 'Klaus', body: 'Hello Sir', url: '/' }),
      },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    }

    pushListener(event)
    await Promise.all(waitUntilPromises)

    expect(showNotification).toHaveBeenCalledTimes(1)
    expect(showNotification).toHaveBeenCalledWith(
      'Klaus',
      expect.objectContaining({
        body: 'Hello Sir',
        data: { url: '/', external_url: null },
      }),
    )
    // Untagged payload → untagged notification (D-12 default).
    const [, options] = showNotification.mock.calls[0] as [string, { tag?: string }]
    expect(options.tag).toBeUndefined()
  })

  it('SKIP_WAITING message calls self.skipWaiting()', () => {
    const messageListener = getListener(listeners, 'message')
    messageListener({ data: { type: 'SKIP_WAITING' } })
    expect(skipWaiting).toHaveBeenCalledTimes(1)
  })

  it('notificationclick focuses an existing client and posts NAVIGATE to the review path', async () => {
    const postMessage = vi.fn()
    const focus = vi.fn().mockResolvedValue(undefined)
    matchAll.mockResolvedValueOnce([{ focus, postMessage }])
    const reviewPath = '/klaus/reviews/nightly/2026-08-10'

    const notificationClickListener = getListener(listeners, 'notificationclick')
    const close = vi.fn()
    const waitUntilPromises: Promise<unknown>[] = []
    const event = {
      notification: { close, data: { url: reviewPath } },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    }

    notificationClickListener(event)
    await Promise.all(waitUntilPromises)

    expect(close).toHaveBeenCalledTimes(1)
    expect(focus).toHaveBeenCalledTimes(1)
    expect(postMessage).toHaveBeenCalledWith({ type: 'NAVIGATE', path: reviewPath })
    expect(openWindow).not.toHaveBeenCalled()
  })

  it.each([
    'https://evil.example/phish',
    '//evil.example/phish',
    '/\\\\evil.example/phish',
    '/klaus\n/evil',
  ])('notificationclick falls back to root for hostile path %j', async (url) => {
    const postMessage = vi.fn()
    const focus = vi.fn().mockResolvedValue(undefined)
    matchAll.mockResolvedValueOnce([{ focus, postMessage }])
    const notificationClickListener = getListener(listeners, 'notificationclick')
    const waitUntilPromises: Promise<unknown>[] = []
    const event = {
      notification: { close: vi.fn(), data: { url } },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    }

    notificationClickListener(event)
    await Promise.all(waitUntilPromises)

    expect(focus).toHaveBeenCalledTimes(1)
    expect(postMessage).toHaveBeenCalledWith({ type: 'NAVIGATE', path: '/' })
    expect(openWindow).not.toHaveBeenCalled()
  })

  it('notificationclick opens a new window at the review path when no client is focused', async () => {
    matchAll.mockResolvedValueOnce([])
    const notificationClickListener = getListener(listeners, 'notificationclick')
    const waitUntilPromises: Promise<unknown>[] = []
    const reviewPath = '/klaus/reviews/nightly/2026-08-10'
    const event = {
      notification: { close: vi.fn(), data: { url: reviewPath } },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    }

    notificationClickListener(event)
    await Promise.all(waitUntilPromises)

    expect(openWindow).toHaveBeenCalledWith(reviewPath)
  })

  // ── Paper Hub additions ──────────────────────────────────────────────

  it('push handler applies a payload tag so the Hub can dismiss it later', async () => {
    const pushListener = getListener(listeners, 'push')
    const waitUntilPromises: Promise<unknown>[] = []
    pushListener({
      data: {
        json: () => ({
          title: 'Klaus Nightly Review',
          body: 'Protein landed at 158 g.',
          url: '/',
          external_url: 'https://claude.ai/chat/abc',
          tag: 'review:nightly:2026-08-17',
        }),
      },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    })
    await Promise.all(waitUntilPromises)

    const [, options] = showNotification.mock.calls[0] as [
      string,
      { tag?: string; data: { external_url: string | null } },
    ]
    expect(options.tag).toBe('review:nightly:2026-08-17')
    expect(options.data.external_url).toBe('https://claude.ai/chat/abc')
  })

  // iOS: clients.openWindow() renders an out-of-scope https URL in the PWA's
  // in-app browser view — it never resolves claude.ai's Universal Link, so the
  // Claude app is bypassed. The tap must land in the Hub instead; the bell's
  // user-activated <a target="_blank"> is the only path iOS hands to the app.
  it('notificationclick lands in the Hub even when a claude.ai session is present', async () => {
    const postMessage = vi.fn()
    const focus = vi.fn().mockResolvedValue(undefined)
    matchAll.mockResolvedValueOnce([{ focus, postMessage }])
    const notificationClickListener = getListener(listeners, 'notificationclick')
    const waitUntilPromises: Promise<unknown>[] = []

    notificationClickListener({
      notification: {
        close: vi.fn(),
        data: {
          url: '/klaus/reviews/nightly/2026-08-18',
          external_url: 'https://claude.ai/chat/abc-123',
        },
      },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    })
    await Promise.all(waitUntilPromises)

    expect(openWindow).not.toHaveBeenCalled()
    expect(focus).toHaveBeenCalled()
    expect(postMessage).toHaveBeenCalledWith({
      type: 'NAVIGATE',
      path: '/klaus/reviews/nightly/2026-08-18',
    })
  })

  it('notificationclick opens the Hub review path on a cold start', async () => {
    matchAll.mockResolvedValueOnce([])
    const notificationClickListener = getListener(listeners, 'notificationclick')
    const waitUntilPromises: Promise<unknown>[] = []

    notificationClickListener({
      notification: {
        close: vi.fn(),
        data: {
          url: '/klaus/reviews/nightly/2026-08-18',
          external_url: 'https://claude.ai/chat/abc-123',
        },
      },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    })
    await Promise.all(waitUntilPromises)

    expect(openWindow).toHaveBeenCalledWith('/klaus/reviews/nightly/2026-08-18')
    expect(openWindow).not.toHaveBeenCalledWith('https://claude.ai/chat/abc-123')
  })

  it.each([
    'https://evil.example/steal',
    'http://claude.ai/chat/abc',
    'https://claude.ai.evil.example/x',
    'javascript:alert(1)',
  ])('notificationclick never opens external_url %j', async (external) => {
    const postMessage = vi.fn()
    const focus = vi.fn().mockResolvedValue(undefined)
    matchAll.mockResolvedValueOnce([{ focus, postMessage }])
    const notificationClickListener = getListener(listeners, 'notificationclick')
    const waitUntilPromises: Promise<unknown>[] = []

    notificationClickListener({
      notification: { close: vi.fn(), data: { url: '/', external_url: external } },
      waitUntil: (p: Promise<unknown>) => {
        waitUntilPromises.push(p)
      },
    })
    await Promise.all(waitUntilPromises)

    // Every external_url — hostile or not — falls through to the in-app path.
    expect(openWindow).not.toHaveBeenCalled()
    expect(postMessage).toHaveBeenCalledWith({ type: 'NAVIGATE', path: '/' })
  })

  it('DISMISS_NOTIFICATIONS closes only the named tags, or all when omitted', async () => {
    const closeA = vi.fn()
    const closeB = vi.fn()
    const closeUntagged = vi.fn()
    getNotifications.mockResolvedValue([
      { tag: 'review:nightly:2026-08-17', close: closeA },
      { tag: 'followup:f1', close: closeB },
      { tag: '', close: closeUntagged },
    ])
    const messageListener = getListener(listeners, 'message')

    messageListener({ data: { type: 'DISMISS_NOTIFICATIONS', tags: ['followup:f1'] } })
    await vi.waitFor(() => expect(closeB).toHaveBeenCalledTimes(1))
    expect(closeA).not.toHaveBeenCalled()

    messageListener({ data: { type: 'DISMISS_NOTIFICATIONS' } })
    await vi.waitFor(() => expect(closeA).toHaveBeenCalledTimes(1))
    expect(closeUntagged).toHaveBeenCalledTimes(1)
  })
})
