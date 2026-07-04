/**
 * usePush.ts — Web Push subscribe gesture + silent re-validation (PUSH-01, D-19).
 *
 * Same defensive shape as useInstallBanner.ts: feature-detect the browser
 * capability, guard every browser-API access in try/catch, expose a small
 * `{ state..., action() }` object.
 *
 * iOS hard requirements (RESEARCH.md Pattern 3):
 *   - Push API exists only in the installed home-screen web app.
 *   - `pushManager.subscribe` (which triggers the permission prompt) MUST be
 *     called from a user-gesture handler — never on mount.
 *   - `userVisibleOnly: true` is mandatory.
 *
 * Re-validation (RESEARCH.md Pattern 8 / D-19 silent recovery), run on mount
 * and on `visibilitychange` → visible, standalone only:
 *   - permission 'granted' + subscription exists  → idempotent upsert POST
 *   - permission 'granted' + subscription missing → silently re-subscribe
 *     (no gesture needed — permission is already granted) + POST. This is
 *     the iOS 3-strikes revocation-recovery path (Pitfall 1) — logged loudly
 *     so the root cause isn't masked.
 *   - permission 'denied' + push_was_enabled flag → needsReenable (banner)
 *   - permission 'default' (never asked)          → neverAsked (first-run banner)
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../api/client'

const PUSH_WAS_ENABLED_KEY = 'push_was_enabled'

export type PushPermission = 'unsupported' | 'granted' | 'denied' | 'default'

export interface UsePushResult {
  /** Current Notification permission state ('unsupported' if the Push API isn't available at all). */
  permission: PushPermission
  /** Call from a real user-gesture click handler to request permission + subscribe. */
  enablePush: () => Promise<void>
  /** True when permission was revoked after previously being enabled — show the re-enable banner (D-19). */
  needsReenable: boolean
  /** True when the user has never been asked — show the first-run enable banner (D-16). */
  neverAsked: boolean
  /** True once a subscription is confirmed present (optimistic on subscribe, confirmed on revalidate). */
  isSubscribed: boolean
}

function detectSupport(): boolean {
  if (typeof navigator === 'undefined' || typeof window === 'undefined') return false
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

function detectStandalone(): boolean {
  if (typeof window === 'undefined') return false
  const mediaMatch =
    typeof window.matchMedia === 'function'
      ? window.matchMedia('(display-mode: standalone)').matches
      : false
  // navigator.standalone is a non-standard Safari property (true when launched from home screen)
  const navStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true
  return mediaMatch || navStandalone
}

function getWasEnabled(): boolean {
  try {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(PUSH_WAS_ENABLED_KEY) === '1'
  } catch {
    return false
  }
}

function markWasEnabled(): void {
  try {
    localStorage.setItem(PUSH_WAS_ENABLED_KEY, '1')
  } catch {
    /* ignore — Safari private mode; not fatal, just won't persist the flag */
  }
}

/** Standard base64url → Uint8Array conversion for PushManager's applicationServerKey. */
function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(new ArrayBuffer(rawData.length))
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

async function fetchVapidKey(): Promise<string> {
  const { key } = await apiFetch<{ key: string }>('/api/push/vapid-public-key')
  return key
}

async function postSubscription(sub: PushSubscription): Promise<void> {
  await apiFetch('/api/push/subscribe', {
    method: 'POST',
    body: JSON.stringify({ subscription: sub.toJSON(), user_agent: navigator.userAgent }),
  })
}

export function usePush(): UsePushResult {
  const supported = detectSupport()
  const [permission, setPermission] = useState<PushPermission>(() =>
    supported ? (Notification.permission as PushPermission) : 'unsupported',
  )
  const [isSubscribed, setIsSubscribed] = useState(false)
  const [needsReenable, setNeedsReenable] = useState(false)

  // Keep a stable ref to the latest revalidate closure so the mount effect
  // (which must only run once) always calls the current version.
  const revalidateRef = useRef<() => Promise<void>>(async () => {})

  const revalidate = useCallback(async () => {
    if (!supported) return
    if (!detectStandalone()) return
    try {
      const current = Notification.permission as PushPermission
      setPermission(current)

      if (current === 'granted') {
        const reg = await navigator.serviceWorker.ready
        const existing = await reg.pushManager.getSubscription()
        if (existing) {
          setIsSubscribed(true)
          await postSubscription(existing)
        } else {
          // Permission still granted but the subscription is gone — iOS
          // revoked it (3-strikes or expiry). Re-subscribe silently, no
          // gesture required since permission was already granted. Log
          // loudly: this recovery masks the true root cause (Pitfall 1).
          console.warn(
            '[usePush] permission granted but subscription missing — silently re-subscribing (revocation recovery)',
          )
          const key = await fetchVapidKey()
          const resubscribed = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(key),
          })
          markWasEnabled()
          setIsSubscribed(true)
          await postSubscription(resubscribed)
        }
        setNeedsReenable(false)
      } else if (current === 'denied' && getWasEnabled()) {
        setIsSubscribed(false)
        setNeedsReenable(true)
      } else {
        setIsSubscribed(false)
        setNeedsReenable(false)
      }
    } catch {
      // Defensive: browser API failures must never crash the hook.
    }
  }, [supported])

  revalidateRef.current = revalidate

  useEffect(() => {
    void revalidateRef.current()
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') void revalidateRef.current()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
    // Intentionally mount-only — revalidateRef always points at the latest closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const enablePush = useCallback(async () => {
    if (!supported) return
    try {
      const reg = await navigator.serviceWorker.ready
      const key = await fetchVapidKey()
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      })
      await postSubscription(sub)
      markWasEnabled()
      setIsSubscribed(true)
      setNeedsReenable(false)
    } catch {
      // Subscribe failed (denied, dismissed prompt, network) — reflect
      // whatever the browser actually landed on; don't crash the caller.
    } finally {
      if (supported) setPermission(Notification.permission as PushPermission)
    }
  }, [supported])

  const neverAsked = permission === 'default'

  return { permission, enablePush, needsReenable, neverAsked, isSubscribed }
}
