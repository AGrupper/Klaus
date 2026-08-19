/**
 * claudeLink.ts — pick a claude.ai URL that iOS will hand to the Claude app.
 *
 * iOS opens a link in the Claude app only when its path appears in the app's
 * apple-app-site-association file (claude.ai/.well-known/...). As of
 * 2026-08-19 that list is `/new`, `/cowork`, `/code/*`, `/artifacts/*`,
 * `/public/artifacts/*`, `/share/*` plus auth callbacks — and `/cowork` is an
 * EXACT match, so the Hub's own project URL
 * (`/cowork/project/<id>`) matches nothing and renders in the PWA's in-app
 * browser instead. Verified on device: both `/cowork` and
 * `/cowork?project=<id>` open the app on the Cowork tab; no URL reaches a
 * specific project, and the query string is ignored.
 *
 * So on iOS an unclaimed claude.ai link is downgraded to `/cowork` — the app
 * opens, one tap from the project. Everywhere else (desktop, Android) the
 * exact URL is kept, since there is no app to intercept it and the precise
 * project page is strictly better.
 */

// Paths the Claude iOS app claims. Anchored: `/cowork` and `/new` are exact,
// the rest are prefixes.
const APP_CLAIMED_PATHS = [
  /^\/new$/,
  /^\/cowork$/,
  /^\/code\//,
  /^\/artifacts\//,
  /^\/public\/artifacts\//,
  /^\/share\//,
]

const CLAUDE_HOSTS = new Set(['claude.ai', 'www.claude.ai'])
const COWORK_HOME = 'https://claude.ai/cowork'

/** True on iPhone/iPad, including iPadOS 13+ which reports itself as macOS. */
export function isAppleMobile(): boolean {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent || ''
  if (/iPhone|iPad|iPod/.test(ua)) return true
  return /Macintosh/.test(ua) && (navigator.maxTouchPoints ?? 0) > 1
}

/**
 * @param url  the configured claude.ai URL (may be null while /agent/status loads)
 * @param ios  override for tests; defaults to sniffing the current device
 * @returns    a URL safe to put in an <a href>, or undefined when there is none
 */
export function claudeAppUrl(
  url: string | null | undefined,
  ios: boolean = isAppleMobile(),
): string | undefined {
  if (!url) return undefined
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return undefined
  }
  if (!ios || !CLAUDE_HOSTS.has(parsed.hostname)) return url
  if (APP_CLAIMED_PATHS.some((pattern) => pattern.test(parsed.pathname))) return url
  return COWORK_HOME
}
