/**
 * Zustand auth store — client-side authentication state.
 *
 * Stores whether the user is signed in and their email. This is CLIENT-ONLY
 * state: the authoritative session truth lives in the httpOnly cookie that the
 * server verifies on every /api/* request. This store is used only to:
 *   1. Decide whether to show SignInPage or the main hub shell.
 *   2. Display the user's email in the UI.
 *
 * WHY zustand (not React Context): zustand provides selective subscription so
 * components that only read `signedIn` do not re-render when `email` changes.
 * Context would re-render every subscriber on any state change.
 *
 * Initialization: call fetchMe() on app load and setSignedIn(email) on success,
 * or signOut() on 401.
 */
import { create } from 'zustand'

interface AuthState {
  /** Whether the user has a valid session cookie. */
  signedIn: boolean
  /** The verified email from the session cookie, or null if not signed in. */
  email: string | null
  /** Mark the user as signed in with the given email. */
  setSignedIn: (email: string) => void
  /** Clear the signed-in state (client-side only — does not clear the cookie). */
  signOut: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  signedIn: false,
  email: null,

  setSignedIn: (email: string) =>
    set({ signedIn: true, email }),

  signOut: () =>
    set({ signedIn: false, email: null }),
}))
