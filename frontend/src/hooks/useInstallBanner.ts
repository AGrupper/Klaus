/**
 * useInstallBanner.ts — iOS Add-to-Home-Screen install banner gate (D-12 / HUB-02).
 *
 * iOS has no `beforeinstallprompt` event. This hook implements the detection
 * logic from RESEARCH.md Pattern 4:
 *
 *   isIOS      = /iphone|ipad|ipod/i.test(navigator.userAgent)
 *   isStandalone = window.matchMedia('(display-mode: standalone)').matches
 *                  || navigator.standalone === true
 *   dismissed  = localStorage.getItem('install-banner-dismissed') === '1'
 *   showBanner = isIOS && !isStandalone && !dismissed
 *
 * Dismiss is one-time: calling dismiss() sets localStorage and hides the
 * banner permanently (stays gone on all future page loads).
 *
 * Note (RESEARCH.md Pitfall 6 / iOS-EU caveat): Israel is assumed non-EU so
 * iOS 17.4+ standalone install works. The banner degrades gracefully regardless
 * — if the app cannot be installed as a standalone PWA, the instructional text
 * still guides the user to add a web clip.
 */
import { useCallback, useState } from 'react'

const DISMISSED_KEY = 'install-banner-dismissed'

function detectIOS(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iphone|ipad|ipod/i.test(navigator.userAgent)
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

function isDismissed(): boolean {
  // localStorage access can throw (Safari private mode) or be non-functional in
  // some runtimes — never let it crash the banner render.
  try {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

export interface UseInstallBannerResult {
  /** True when the banner should be shown (iOS, not standalone, not dismissed). */
  showBanner: boolean
  /** Call to permanently dismiss the banner (sets localStorage). */
  dismiss: () => void
}

export function useInstallBanner(): UseInstallBannerResult {
  const [dismissed, setDismissed] = useState<boolean>(() => isDismissed())

  const isIOS = detectIOS()
  const isStandalone = detectStandalone()
  const showBanner = isIOS && !isStandalone && !dismissed

  const dismiss = useCallback(() => {
    // setItem can throw in Safari private mode — still hide the banner this session.
    try {
      localStorage.setItem(DISMISSED_KEY, '1')
    } catch {
      /* ignore — dismissal won't persist, but the banner hides for this session */
    }
    setDismissed(true)
  }, [])

  return { showBanner, dismiss }
}
