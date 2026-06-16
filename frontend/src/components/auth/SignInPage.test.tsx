/**
 * SignInPage.test.tsx — sign-in success must transition to the hub.
 *
 * Regression: POST /api/auth/google returns 200 and sets the cookie, but the
 * App gate reads the on-load fetchMe query (errored, staleTime: Infinity). Without
 * invalidating ['auth','me'] after sign-in, the app never re-checks the cookie and
 * bounces back to the sign-in page despite a successful login.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SignInPage } from './SignInPage'
import { useAuthStore } from '../../store/auth'

vi.mock('../../api/auth', () => ({
  signInWithGoogle: vi.fn(),
}))
import { signInWithGoogle } from '../../api/auth'
const mockSignIn = vi.mocked(signInWithGoogle)

describe('SignInPage sign-in success', () => {
  beforeEach(() => {
    useAuthStore.setState({ signedIn: false, email: null })
    vi.clearAllMocks()
  })

  it('invalidates the auth query and marks signed-in after a 200 sign-in', async () => {
    mockSignIn.mockResolvedValue({ ok: true, email: 'amit.grupper@gmail.com' })
    const queryClient = new QueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    render(
      <QueryClientProvider client={queryClient}>
        <SignInPage />
      </QueryClientProvider>,
    )

    // SignInPage exposes its credential handler on window for the GIS callback.
    expect(typeof window.handleGisCredential).toBe('function')
    await act(async () => {
      await window.handleGisCredential!({ credential: 'fake-jwt' })
    })

    expect(mockSignIn).toHaveBeenCalledWith('fake-jwt')
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['auth', 'me'] })
    expect(useAuthStore.getState().signedIn).toBe(true)
    expect(useAuthStore.getState().email).toBe('amit.grupper@gmail.com')
  })

  it('does not invalidate or sign in when the server rejects the credential', async () => {
    mockSignIn.mockResolvedValue({ ok: false })
    const queryClient = new QueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    render(
      <QueryClientProvider client={queryClient}>
        <SignInPage />
      </QueryClientProvider>,
    )

    await act(async () => {
      await window.handleGisCredential!({ credential: 'bad-jwt' })
    })

    expect(invalidateSpy).not.toHaveBeenCalled()
    expect(useAuthStore.getState().signedIn).toBe(false)
  })
})
