/**
 * client.test.ts — apiFetch 401 handling.
 *
 * Regression for the infinite-reload loop: a signed-out load calls fetchMe(),
 * which 401s. If apiFetch performs its full-page `window.location.href` redirect
 * for THAT call, the page reloads before the sign-in page can render → loop.
 * The on-load auth check must pass redirectOn401:false.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { apiFetch } from './client'
import { fetchMe } from './auth'

describe('apiFetch 401 handling', () => {
  let hrefSetTo: string | null
  const realLocation = window.location

  beforeEach(() => {
    hrefSetTo = null
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        get href() {
          return ''
        },
        set href(v: string) {
          hrefSetTo = v
        },
      },
    })
    global.fetch = vi.fn().mockResolvedValue({ status: 401, ok: false } as Response)
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: realLocation,
    })
    vi.restoreAllMocks()
  })

  it('redirects to sign-in on 401 by default', async () => {
    await expect(apiFetch('/api/today')).rejects.toThrow('Not authenticated')
    expect(hrefSetTo).toBe('/?signin=required')
  })

  it('does NOT redirect when redirectOn401 is false', async () => {
    await expect(
      apiFetch('/api/auth/me', { method: 'GET' }, { redirectOn401: false }),
    ).rejects.toThrow('Not authenticated')
    expect(hrefSetTo).toBeNull()
  })

  it('fetchMe does not redirect on 401 (prevents the signed-out reload loop)', async () => {
    await expect(fetchMe()).rejects.toThrow('Not authenticated')
    expect(hrefSetTo).toBeNull()
  })
})
