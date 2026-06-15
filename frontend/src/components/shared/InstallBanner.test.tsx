/**
 * InstallBanner.test.tsx — Vitest spec for install-banner gate logic + online/offline toggle.
 *
 * NOTE: The actual on-device iOS install gesture (HUB-02) and the offline-shell
 * load with skeletons (HUB-03) are MANUAL verifications per VALIDATION.md.
 * This spec covers only the show/hide gate logic and the online/offline toggle.
 *
 * Manual HUB-02 verification: open the hub in Safari on a physical iPhone (not
 * standalone), confirm the install banner appears, follow Share → Add to Home
 * Screen, confirm install, then confirm the banner stays dismissed after reopening.
 *
 * Manual HUB-03 verification: reload with the network off (DevTools offline or
 * airplane mode) and confirm the app shell loads from cache, the offline
 * indicator shows, and sections degrade to Skeletons.
 *
 * Gate logic covered:
 *   (a) InstallBanner renders when iOS, not standalone, and dismiss not set.
 *   (b) InstallBanner renders nothing when install-banner-dismissed === '1'.
 *   (c) InstallBanner renders nothing on a non-iOS userAgent.
 *   (d) Clicking dismiss sets localStorage['install-banner-dismissed'] = '1' and hides banner.
 *   (e) OfflineIndicator renders "Offline — showing cached data" when navigator.onLine is false.
 *   (f) OfflineIndicator renders nothing when navigator.onLine is true.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import '@testing-library/jest-dom'
import { InstallBanner } from './InstallBanner'
import { OfflineIndicator } from './OfflineIndicator'

// ---------------------------------------------------------------------------
// Helpers: mock navigator.userAgent (read-only, must use Object.defineProperty)
// ---------------------------------------------------------------------------

function mockUserAgent(ua: string) {
  Object.defineProperty(navigator, 'userAgent', {
    value: ua,
    configurable: true,
    writable: true,
  })
}

function mockMatchMedia(standalone: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query === '(display-mode: standalone)' ? standalone : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

function mockOnline(online: boolean) {
  Object.defineProperty(navigator, 'onLine', {
    value: online,
    configurable: true,
    writable: true,
  })
}

const IOS_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
const DESKTOP_UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

// ---------------------------------------------------------------------------
// InstallBanner gate tests
// ---------------------------------------------------------------------------

describe('InstallBanner — show/hide gate logic', () => {
  beforeEach(() => {
    localStorage.clear()
    // Default: iOS, not standalone
    mockUserAgent(IOS_UA)
    mockMatchMedia(false)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('(a) renders the banner when iOS, not standalone, and dismissed key is unset', () => {
    render(<InstallBanner />)
    expect(
      screen.getByText('Add Klaus to your home screen'),
    ).toBeInTheDocument()
  })

  it('(b) renders nothing when install-banner-dismissed is "1"', () => {
    localStorage.setItem('install-banner-dismissed', '1')
    render(<InstallBanner />)
    expect(
      screen.queryByText('Add Klaus to your home screen'),
    ).not.toBeInTheDocument()
  })

  it('(c) renders nothing on a non-iOS userAgent', () => {
    mockUserAgent(DESKTOP_UA)
    render(<InstallBanner />)
    expect(
      screen.queryByText('Add Klaus to your home screen'),
    ).not.toBeInTheDocument()
  })

  it('(d) clicking dismiss sets localStorage key and hides the banner', () => {
    render(<InstallBanner />)

    // Banner is visible
    expect(
      screen.getByText('Add Klaus to your home screen'),
    ).toBeInTheDocument()

    // Click the X dismiss button
    const dismissBtn = screen.getByRole('button', {
      name: 'Dismiss install prompt',
    })
    fireEvent.click(dismissBtn)

    // Banner should be gone
    expect(
      screen.queryByText('Add Klaus to your home screen'),
    ).not.toBeInTheDocument()

    // localStorage key must be set
    expect(localStorage.getItem('install-banner-dismissed')).toBe('1')
  })

  it('renders the exact body copy from UI-SPEC Copywriting Contract', () => {
    render(<InstallBanner />)
    expect(
      // Using a function matcher to handle HTML entity rendering
      screen.getByText((content) =>
        content.includes('Tap the Share button below') &&
        content.includes('Add to Home Screen'),
      ),
    ).toBeInTheDocument()
  })

  it('renders the "How to install" CTA button', () => {
    render(<InstallBanner />)
    expect(
      screen.getByRole('button', { name: 'How to install' }),
    ).toBeInTheDocument()
  })

  it('renders nothing when the app is already in standalone mode', () => {
    mockMatchMedia(true) // standalone = true
    render(<InstallBanner />)
    expect(
      screen.queryByText('Add Klaus to your home screen'),
    ).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// OfflineIndicator — online/offline toggle tests
// ---------------------------------------------------------------------------

describe('OfflineIndicator — online/offline toggle', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('(e) renders "Offline — showing cached data" when navigator.onLine is false', () => {
    mockOnline(false)
    render(<OfflineIndicator />)
    expect(
      screen.getByText('Offline — showing cached data'),
    ).toBeInTheDocument()
  })

  it('(f) renders nothing when navigator.onLine is true', () => {
    mockOnline(true)
    render(<OfflineIndicator />)
    expect(
      screen.queryByText('Offline — showing cached data'),
    ).not.toBeInTheDocument()
  })

  it('shows the offline strip when the offline event fires', () => {
    mockOnline(true)
    render(<OfflineIndicator />)
    // Initially online — nothing rendered
    expect(
      screen.queryByText('Offline — showing cached data'),
    ).not.toBeInTheDocument()

    // Simulate going offline
    act(() => {
      mockOnline(false)
      window.dispatchEvent(new Event('offline'))
    })

    expect(
      screen.getByText('Offline — showing cached data'),
    ).toBeInTheDocument()
  })

  it('hides the offline strip when the online event fires after being offline', () => {
    mockOnline(false)
    render(<OfflineIndicator />)
    // Initially offline — strip visible
    expect(
      screen.getByText('Offline — showing cached data'),
    ).toBeInTheDocument()

    // Simulate coming back online
    act(() => {
      mockOnline(true)
      window.dispatchEvent(new Event('online'))
    })

    expect(
      screen.queryByText('Offline — showing cached data'),
    ).not.toBeInTheDocument()
  })
})
