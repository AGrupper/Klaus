/**
 * usePush.test.ts — Tests for the push subscribe gesture + re-validation hook
 * (PUSH-01, D-19).
 *
 * Network-free: apiFetch is mocked. navigator.serviceWorker/PushManager/
 * Notification are minimal stand-ins — jsdom implements none of the Push API.
 * Standalone mode is simulated via `navigator.standalone` (Pattern 8 gates
 * revalidate on standalone; non-standalone tests rely on this being absent).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { usePush } from './usePush'

vi.mock('../api/client', () => ({
  apiFetch: vi.fn(),
}))

import { apiFetch } from '../api/client'

const mockApiFetch = vi.mocked(apiFetch)

const VAPID_KEY = 'AAAA' // valid-enough base64url stub for urlBase64ToUint8Array

function mockSubscription(endpoint = 'https://push.example.com/abc') {
  return {
    endpoint,
    toJSON: () => ({ endpoint, keys: { p256dh: 'p256dh-stub', auth: 'auth-stub' } }),
  } as unknown as PushSubscription
}

function setNotificationPermission(permission: NotificationPermission) {
  Object.defineProperty(window, 'Notification', {
    value: { permission },
    configurable: true,
    writable: true,
  })
}

function setServiceWorker(pushManager: {
  subscribe: ReturnType<typeof vi.fn>
  getSubscription: ReturnType<typeof vi.fn>
}) {
  Object.defineProperty(navigator, 'serviceWorker', {
    value: { ready: Promise.resolve({ pushManager }) },
    configurable: true,
    writable: true,
  })
}

function setPushManagerGlobal() {
  Object.defineProperty(window, 'PushManager', {
    value: function PushManagerStub() {},
    configurable: true,
    writable: true,
  })
}

function setStandalone(value: boolean) {
  Object.defineProperty(navigator, 'standalone', {
    value,
    configurable: true,
    writable: true,
  })
}

describe('usePush', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
    mockApiFetch.mockImplementation((path: string) => {
      if (typeof path === 'string' && path.includes('vapid-public-key')) {
        return Promise.resolve({ key: VAPID_KEY })
      }
      return Promise.resolve({ ok: true })
    })
    setPushManagerGlobal()
  })

  afterEach(() => {
    vi.clearAllMocks()
    // @ts-expect-error — cleanup test-only shims
    delete window.Notification
    // @ts-expect-error
    delete navigator.serviceWorker
    // @ts-expect-error
    delete window.PushManager
    // @ts-expect-error
    delete navigator.standalone
  })

  it('enablePush subscribes with userVisibleOnly:true and POSTs to /api/push/subscribe', async () => {
    setNotificationPermission('default')
    const subscribe = vi.fn().mockResolvedValue(mockSubscription())
    const getSubscription = vi.fn().mockResolvedValue(null)
    setServiceWorker({ subscribe, getSubscription })

    const { result } = renderHook(() => usePush())

    await act(async () => {
      await result.current.enablePush()
    })

    expect(subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ userVisibleOnly: true, applicationServerKey: expect.any(Uint8Array) }),
    )
    expect(mockApiFetch).toHaveBeenCalledWith(
      '/api/push/subscribe',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"endpoint":"https://push.example.com/abc"'),
      }),
    )

    await waitFor(() => expect(result.current.isSubscribed).toBe(true))
  })

  it('revalidate: permission granted + getSubscription()->null triggers a silent re-subscribe + POST', async () => {
    setStandalone(true)
    setNotificationPermission('granted')
    const subscribe = vi.fn().mockResolvedValue(mockSubscription('https://push.example.com/resub'))
    const getSubscription = vi.fn().mockResolvedValue(null)
    setServiceWorker({ subscribe, getSubscription })

    const { result } = renderHook(() => usePush())

    await waitFor(() => expect(subscribe).toHaveBeenCalled())

    expect(subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ userVisibleOnly: true }),
    )
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/push/subscribe',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"endpoint":"https://push.example.com/resub"'),
        }),
      ),
    )
    await waitFor(() => expect(result.current.isSubscribed).toBe(true))
  })

  it('revalidate: permission granted + existing subscription idempotently upserts (no re-subscribe)', async () => {
    setStandalone(true)
    setNotificationPermission('granted')
    const subscribe = vi.fn()
    const getSubscription = vi.fn().mockResolvedValue(mockSubscription('https://push.example.com/existing'))
    setServiceWorker({ subscribe, getSubscription })

    const { result } = renderHook(() => usePush())

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/push/subscribe',
        expect.objectContaining({
          body: expect.stringContaining('"endpoint":"https://push.example.com/existing"'),
        }),
      ),
    )
    expect(subscribe).not.toHaveBeenCalled()
    await waitFor(() => expect(result.current.isSubscribed).toBe(true))
  })

  it('permission denied + push_was_enabled flag -> needsReenable true', async () => {
    setStandalone(true)
    setNotificationPermission('denied')
    setServiceWorker({ subscribe: vi.fn(), getSubscription: vi.fn() })
    localStorage.setItem('push_was_enabled', '1')

    const { result } = renderHook(() => usePush())

    await waitFor(() => expect(result.current.needsReenable).toBe(true))
    expect(result.current.isSubscribed).toBe(false)
  })

  it('permission denied without push_was_enabled flag -> needsReenable stays false', async () => {
    setStandalone(true)
    setNotificationPermission('denied')
    setServiceWorker({ subscribe: vi.fn(), getSubscription: vi.fn() })

    const { result } = renderHook(() => usePush())

    await waitFor(() => expect(result.current.permission).toBe('denied'))
    expect(result.current.needsReenable).toBe(false)
  })

  it('permission default -> neverAsked true', () => {
    setNotificationPermission('default')
    setServiceWorker({ subscribe: vi.fn(), getSubscription: vi.fn() })

    const { result } = renderHook(() => usePush())

    expect(result.current.neverAsked).toBe(true)
  })

  it('unsupported browsers report permission=unsupported and neverAsked=false', () => {
    // No Notification/PushManager/serviceWorker set up at all this test.
    const { result } = renderHook(() => usePush())

    expect(result.current.permission).toBe('unsupported')
    expect(result.current.neverAsked).toBe(false)
  })
})
