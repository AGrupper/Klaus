/**
 * Tests for frontend/src/store/auth.ts — Zustand auth store.
 *
 * These tests verify the client-side auth state machine:
 *   - Initial state: not signed in, no email
 *   - setSignedIn: sets signedIn=true and the email
 *   - signOut: sets signedIn=false and clears email
 */
import { describe, beforeEach, it, expect } from 'vitest'
import { useAuthStore } from './auth'

describe('useAuthStore', () => {
  beforeEach(() => {
    // Reset store to initial state between tests
    useAuthStore.setState({ signedIn: false, email: null })
  })

  it('starts with signedIn=false and email=null', () => {
    const state = useAuthStore.getState()
    expect(state.signedIn).toBe(false)
    expect(state.email).toBeNull()
  })

  it('setSignedIn sets signedIn=true and records the email', () => {
    useAuthStore.getState().setSignedIn('amit.grupper@gmail.com')
    const state = useAuthStore.getState()
    expect(state.signedIn).toBe(true)
    expect(state.email).toBe('amit.grupper@gmail.com')
  })

  it('signOut sets signedIn=false and clears email', () => {
    // Sign in first
    useAuthStore.getState().setSignedIn('amit.grupper@gmail.com')
    expect(useAuthStore.getState().signedIn).toBe(true)

    // Now sign out
    useAuthStore.getState().signOut()

    const state = useAuthStore.getState()
    expect(state.signedIn).toBe(false)
    expect(state.email).toBeNull()
  })
})
