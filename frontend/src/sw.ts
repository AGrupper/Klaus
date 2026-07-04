/// <reference lib="webworker" />
/**
 * Custom service worker (injectManifest strategy).
 *
 * Replaces the previous vite-plugin-pwa `generateSW` auto-generated worker so
 * push (PUSH-02) + badge (PUSH-04) handlers can live alongside the exact same
 * precache/runtime-caching behavior generateSW used to produce. This file
 * preserves two load-bearing behaviors from the deleted plugin config:
 *
 *  - HUB-03: index.html is NetworkFirst with a 5s timeout so a stale cache
 *    never blocks a fresh deploy.
 *  - The `SKIP_WAITING` message listener — UpdatePrompt.tsx's
 *    `updateServiceWorker(true)` posts this message to activate a waiting SW
 *    immediately; without this listener the "New version available" banner
 *    would do nothing.
 *
 * Push handler rule (iOS 3-strikes, T-29-13): a push event must ALWAYS
 * display a notification inside `event.waitUntil`. The badge/IndexedDB
 * increment is wrapped in its own try/catch so a badge failure can never
 * suppress the notification.
 */
declare let self: ServiceWorkerGlobalScope

import { precacheAndRoute, cleanupOutdatedCaches, createHandlerBoundToURL } from 'workbox-precaching'
import { registerRoute, setCatchHandler } from 'workbox-routing'
import { NetworkFirst, CacheFirst } from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'

// ── 1. Precache (replaces generateSW globPatterns behavior) ──
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// ── 2. Runtime caching — exact replica of the deleted vite.config.ts block ──
// HUB-03: index.html network-first, 5s timeout — stale-deploy protection.
registerRoute(
  ({ request }) => request.destination === 'document',
  new NetworkFirst({
    cacheName: 'html-cache',
    networkTimeoutSeconds: 5,
    plugins: [new ExpirationPlugin({ maxEntries: 5, maxAgeSeconds: 60 * 60 * 24 })],
  }),
)
registerRoute(
  /\/assets\/.+\.(js|css)$/,
  new CacheFirst({
    cacheName: 'assets-cache',
    plugins: [new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 * 365 })],
  }),
)

// WR-06: generateSW also auto-configured `navigateFallback: 'index.html'`,
// which the injectManifest migration dropped. Without it, an offline
// navigation to a route with no `html-cache` entry (never-visited route, or
// >24h offline after ExpirationPlugin evicts the cached document) fails
// outright even though index.html sits in the precache — a blank error page
// on an installed-PWA cold start. Restore it as the router's CATCH handler
// (not a second NavigationRoute: workbox serves the FIRST matching route, so
// the NetworkFirst document route above always wins while online — HUB-03's
// 5s network-first behavior is unchanged — and the catch handler only runs
// when that strategy rejects, i.e. network AND html-cache both missed).
let navigationFallback: ReturnType<typeof createHandlerBoundToURL> | null = null
try {
  navigationFallback = createHandlerBoundToURL('index.html')
} catch (err) {
  // 'index.html' absent from the precache manifest — never the case in a
  // real build (globPatterns includes html; happens in tests where
  // __WB_MANIFEST is stubbed empty). Degrade to normal error behavior.
  console.error('[sw] navigation fallback unavailable', err)
}
setCatchHandler((options) => {
  if (navigationFallback && options.request.destination === 'document') {
    return navigationFallback(options)
  }
  return Promise.resolve(Response.error())
})

// ── 3. Raw IndexedDB badge counter (PUSH-04) — no `idb` package ──
const BADGE_DB_NAME = 'klaus-badge'
const BADGE_STORE_NAME = 'badge'
const BADGE_COUNT_KEY = 'count'

function openBadgeDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = self.indexedDB.open(BADGE_DB_NAME, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(BADGE_STORE_NAME)) {
        request.result.createObjectStore(BADGE_STORE_NAME)
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB open failed'))
  })
}

async function readBadgeCount(): Promise<number> {
  const db = await openBadgeDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(BADGE_STORE_NAME, 'readonly')
    const req = tx.objectStore(BADGE_STORE_NAME).get(BADGE_COUNT_KEY)
    req.onsuccess = () => resolve(typeof req.result === 'number' ? req.result : 0)
    req.onerror = () => reject(req.error ?? new Error('IndexedDB read failed'))
  })
}

async function writeBadgeCount(count: number): Promise<void> {
  const db = await openBadgeDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(BADGE_STORE_NAME, 'readwrite')
    tx.objectStore(BADGE_STORE_NAME).put(count, BADGE_COUNT_KEY)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('IndexedDB write failed'))
  })
}

async function incrementBadgeCount(): Promise<number> {
  const current = await readBadgeCount()
  const next = current + 1
  await writeBadgeCount(next)
  return next
}

async function resetBadgeCount(count: number): Promise<void> {
  await writeBadgeCount(count)
}

type NavigatorWithBadging = Navigator & {
  setAppBadge?: (count?: number) => Promise<void>
  clearAppBadge?: () => Promise<void>
}

// ── 4. Prompt-mode update flow + badge reset messages ──
// useRegisterSW's updateServiceWorker(true) posts {type:'SKIP_WAITING'} to the
// waiting SW — this listener is what keeps the existing UpdatePrompt working.
self.addEventListener('message', (event) => {
  const message = event.data as { type?: string; count?: number } | undefined
  if (message?.type === 'SKIP_WAITING') {
    self.skipWaiting()
    return
  }
  if (message?.type === 'RESET_BADGE' && typeof message.count === 'number') {
    const count = message.count
    void (async () => {
      try {
        await resetBadgeCount(count)
        const nav = navigator as NavigatorWithBadging
        if (count === 0) {
          await nav.clearAppBadge?.()
        } else {
          await nav.setAppBadge?.(count)
        }
      } catch (err) {
        console.error('[sw] badge reset failed', err)
      }
    })()
  }
})

// ── 5. Push (PUSH-02) — ALWAYS show a notification (iOS 3-strikes) ──
self.addEventListener('push', (event) => {
  const data = (() => {
    try {
      return (event.data?.json() ?? {}) as { title?: string; body?: string; url?: string }
    } catch {
      return {} as { title?: string; body?: string; url?: string }
    }
  })()
  event.waitUntil(
    (async () => {
      // Badge work is isolated in its own try/catch so a failure here can
      // NEVER skip the notification below (T-29-13 / iOS 3-strikes rule).
      try {
        const count = await incrementBadgeCount()
        const nav = navigator as NavigatorWithBadging
        await nav.setAppBadge?.(count)
      } catch (err) {
        console.error('[sw] badge increment failed', err)
      }
      await self.registration.showNotification(data.title ?? 'Klaus', {
        body: data.body ?? 'New message from Klaus',
        icon: '/icon-192.png',
        data: { url: data.url ?? '/' },
        // NO tag (D-12: each message gets its own notification)
      })
    })(),
  )
})

// ── 6. Tap → Today, never chat (D-12) ──
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const client = clientList[0]
      if (client) {
        await client.focus()
        client.postMessage({ type: 'NAVIGATE', path: '/' })
      } else {
        await self.clients.openWindow('/')
      }
    })(),
  )
})
