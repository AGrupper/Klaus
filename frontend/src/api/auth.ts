/**
 * Auth API client — calls /api/auth/* routes.
 *
 * All requests use credentials: 'include' via the shared apiFetch wrapper so
 * the httpOnly session cookie is sent automatically (RESEARCH.md Pitfall 5).
 */
import { apiFetch } from './client'

interface AuthOkResponse {
  ok: boolean
  email?: string
}

interface MeResponse {
  email: string
}

/**
 * Exchange a Google Identity Services credential (ID token) for a session cookie.
 *
 * On success, the server sets an httpOnly Secure SameSite=Strict session cookie
 * valid for 365 days. The cookie is invisible to JavaScript (httpOnly).
 *
 * @param credential - The GIS ID token from the `google.accounts.id.initialize`
 *                     callback (window.google.accounts.id).
 */
export async function signInWithGoogle(credential: string): Promise<AuthOkResponse> {
  return apiFetch<AuthOkResponse>('/api/auth/google', {
    method: 'POST',
    body: JSON.stringify({ credential }),
  })
}

/**
 * Clear the session cookie on the current device (single-device sign-out).
 *
 * Does NOT bump session_version — use revokeAll() for sign-out-everywhere (D-02).
 */
export async function logout(): Promise<AuthOkResponse> {
  return apiFetch<AuthOkResponse>('/api/auth/logout', {
    method: 'POST',
  })
}

/**
 * Bump session_version to invalidate every existing session cookie on every device.
 *
 * This is the "lost phone" escape hatch (D-02). After this call, every previously
 * issued cookie — including any on other devices — will return 401 until the user
 * signs in again on each device.
 */
export async function revokeAll(): Promise<AuthOkResponse> {
  return apiFetch<AuthOkResponse>('/api/auth/revoke-all', {
    method: 'POST',
  })
}

/**
 * Check whether the current session cookie is valid and return the email.
 *
 * Used on app load to determine whether to show the sign-in page or the hub.
 * Returns null on 401 (no valid session); apiFetch redirects to /?signin=required.
 */
export async function fetchMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>('/api/auth/me', {
    method: 'GET',
  })
}
