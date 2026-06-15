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
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'include', // Send httpOnly session cookie on every request
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (res.status === 401) {
    // Session expired or not authenticated — redirect to sign-in
    window.location.href = '/?signin=required'
    throw new Error('Not authenticated')
  }

  if (!res.ok) {
    throw new Error(`API error ${res.status}`)
  }

  return res.json() as Promise<T>
}
