/**
 * Shared fetch wrapper for all Klaus Hub API calls.
 *
 * WHY credentials: 'include' — the session cookie is httpOnly so JS cannot
 * read it directly. The browser must send it with every request via
 * credentials: 'include'. Without this the cookie is omitted and every
 * /api/* call returns 401 (RESEARCH.md Pitfall 5).
 *
 * WHY same-origin only — no CORS headers are set on the server. All hub
 * requests go to the same origin that served the SPA.
 *
 * WHY cache: 'no-store' — the Hub is a live dashboard and a refresh must show
 * current state. The server sends Cache-Control: no-store on /api too; this is
 * the client half of the same guarantee, so no browser heuristic can decide a
 * response is still fresh.
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  opts?: { redirectOn401?: boolean },
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'include', // Send httpOnly session cookie on every request
    cache: 'no-store',      // Never serve a Hub payload from the HTTP cache
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (res.status === 401) {
    // Session expired or not authenticated. By default redirect to sign-in,
    // but callers that EXPECT a 401 (the on-load auth check, fetchMe) pass
    // redirectOn401:false — otherwise the full-page redirect fires on first
    // load for a signed-out user and the app reloads in an infinite loop
    // before the sign-in page can ever render.
    if (opts?.redirectOn401 !== false) {
      window.location.href = '/?signin=required'
    }
    throw new Error('Not authenticated')
  }

  if (!res.ok) {
    throw new Error(`API error ${res.status}`)
  }

  return res.json() as Promise<T>
}
