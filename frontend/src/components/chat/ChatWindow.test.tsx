/**
 * ChatWindow.test.tsx — UAT gap-closure regression guard (2026-07).
 *
 * Problem 1 (scroll): on the phone PWA, chat always opened at the TOP of
 * history instead of the latest message (WhatsApp-style). Root cause: the
 * ancestor height chain up through AppShell had no definite height, so
 * `<main>`'s overflow-y-auto never became the real scroll container —
 * scrollHeight stayed equal to clientHeight and the initial-scroll effect's
 * `el.scrollHeight > el.clientHeight` guard never passed. Two independent
 * fixes are locked in here:
 *   (1) AppShell.test.tsx locks the bounded-height root (`height`, not
 *       `minHeight`) that makes `<main>` a real scroll region.
 *   (2) This file locks that ChatWindow's own message-list container has
 *       the structural classes that make IT the scroll region
 *       (flex-1 min-h-0 overflow-y-auto), and that the initial-scroll
 *       effect no longer depends on the (previously always-false-on-phone)
 *       scrollHeight > clientHeight guard — jsdom can't measure real
 *       layout, so these are the structural + logic-level assertions the
 *       harness can make instead of a real device screenshot.
 *
 * Problem 2 (windowing): scroll-to-top pagination (loadOlder) must fetch
 * before=<oldest seq>, prepend, and preserve the user's scroll position
 * (classic anchor-preservation) without auto-scrolling to the bottom or
 * creating a phantom unread badge.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import '@testing-library/jest-dom'
import type { ChatMessage } from '../../api/chat'

// ---------------------------------------------------------------------------
// jsdom has no IntersectionObserver — ChatWindow's unread-clearing effect
// constructs one on mount. Minimal stub so render() doesn't throw; the
// unread-badge behavior itself is covered by useChat.test.tsx.
// ---------------------------------------------------------------------------
class MockIntersectionObserver {
  observe = vi.fn()
  disconnect = vi.fn()
  unobserve = vi.fn()
}

// ---------------------------------------------------------------------------
// Mock useChat — ChatWindow.test.tsx tests ChatWindow's own scroll/render
// logic in isolation; useChat's fetch/merge/pagination logic is covered by
// useChat.test.tsx. latestKnownSeq is re-exported from the real module so
// the unread-badge wiring still runs its real (simple) math.
// ---------------------------------------------------------------------------
vi.mock('../../hooks/useChat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../hooks/useChat')>()
  return {
    ...actual,
    useChat: vi.fn(),
  }
})

import { useChat } from '../../hooks/useChat'
import { ChatWindow } from './ChatWindow'

const mockUseChat = vi.mocked(useChat)

function baseChatReturn(overrides: Partial<ReturnType<typeof useChat>> = {}) {
  return {
    messages: [] as ChatMessage[],
    isKlausThinking: false,
    sendMessage: vi.fn(),
    isSending: false,
    loadOlder: vi.fn().mockResolvedValue(undefined),
    hasMoreOlder: true,
    isLoadingOlder: false,
    isLoading: false,
    isError: false,
    ...overrides,
  }
}

function makeMessages(n: number, startSeq = 0): ChatMessage[] {
  return Array.from({ length: n }, (_, i) => ({
    role: i % 2 === 0 ? 'user' : ('assistant' as const),
    content: `message-${startSeq + i}`,
    seq: startSeq + i,
  }))
}

/** Installs a controllable get/set stub for scroll geometry on `el`. */
function stubScrollGeometry(
  el: HTMLElement,
  initial: { scrollHeight: number; clientHeight: number; scrollTop: number },
) {
  const state = { ...initial }
  Object.defineProperty(el, 'scrollHeight', {
    configurable: true,
    get: () => state.scrollHeight,
  })
  Object.defineProperty(el, 'clientHeight', {
    configurable: true,
    get: () => state.clientHeight,
  })
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => state.scrollTop,
    set: (v: number) => {
      state.scrollTop = v
    },
  })
  return state
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
  // jsdom does not implement Element.scrollTo — the existing
  // "auto-scroll to bottom on new message" effect calls it whenever the
  // message count grows while wasNearBottomRef is true (default on mount).
  Element.prototype.scrollTo = vi.fn()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Structural fix: the message list is its own bounded scroll region
// ---------------------------------------------------------------------------

describe('ChatWindow — structural scroll region (Problem 1 fix)', () => {
  it('the message list container carries the flex/height classes that make it the scroller, not the page', () => {
    mockUseChat.mockReturnValue(baseChatReturn({ messages: makeMessages(3) }))
    const { container } = render(<ChatWindow />)

    const scrollRegion = container.querySelector('.overflow-y-auto')
    expect(scrollRegion).not.toBeNull()
    // flex-1 + min-h-0: fills the remaining height of the bounded column
    // above AND overrides the flex default min-height:auto that would
    // otherwise let this box grow to fit its content instead of scrolling
    // it. overflow-y-auto is what makes it the actual scroller.
    expect(scrollRegion).toHaveClass('flex-1', 'min-h-0', 'overflow-y-auto')
  })

  it('the outer wrapper is a bounded column (h-full + overflow-hidden) so it never itself overflows its parent', () => {
    mockUseChat.mockReturnValue(baseChatReturn({ messages: makeMessages(1) }))
    const { container } = render(<ChatWindow />)

    const outer = container.firstElementChild
    expect(outer).toHaveClass('flex', 'flex-col', 'h-full', 'overflow-hidden')
  })
})

// ---------------------------------------------------------------------------
// Initial-scroll effect: guard removed (the actual Problem 1 fix)
// ---------------------------------------------------------------------------

describe('ChatWindow — initial scroll lands on the latest message (Problem 1 fix)', () => {
  it('jumps to the bottom (scrollTop = scrollHeight) once messages are present, unconditionally', () => {
    mockUseChat.mockReturnValue(baseChatReturn({ messages: [] }))
    const { container, rerender } = render(<ChatWindow />)
    const el = container.querySelector('.overflow-y-auto') as HTMLDivElement

    // Equal scrollHeight/clientHeight — the exact condition that silently
    // defeated the old guard on phone.
    const state = stubScrollGeometry(el, { scrollHeight: 600, clientHeight: 600, scrollTop: 0 })

    mockUseChat.mockReturnValue(baseChatReturn({ messages: makeMessages(5) }))
    act(() => {
      rerender(<ChatWindow />)
    })

    expect(state.scrollTop).toBe(600)
  })
})

// ---------------------------------------------------------------------------
// Loading-earlier-messages affordance
// ---------------------------------------------------------------------------

describe('ChatWindow — "load earlier messages" affordance (Problem 2)', () => {
  it('shows a loading indicator while isLoadingOlder is true', () => {
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: makeMessages(3), isLoadingOlder: true }),
    )
    render(<ChatWindow />)
    expect(screen.getByText('Loading earlier messages…')).toBeInTheDocument()
  })

  it('does not show the loading indicator when not loading older messages', () => {
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: makeMessages(3), isLoadingOlder: false }),
    )
    render(<ChatWindow />)
    expect(screen.queryByText('Loading earlier messages…')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Scroll-to-top triggers loadOlder(); scroll position is preserved on prepend
// ---------------------------------------------------------------------------

describe('ChatWindow — scroll-to-top pagination (Problem 2)', () => {
  it('calls loadOlder() when scrolled near the top of an overflowing list', () => {
    const loadOlder = vi.fn().mockResolvedValue(undefined)
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: makeMessages(3), loadOlder, hasMoreOlder: true }),
    )
    const { container } = render(<ChatWindow />)
    const el = container.querySelector('.overflow-y-auto') as HTMLDivElement
    stubScrollGeometry(el, { scrollHeight: 1000, clientHeight: 400, scrollTop: 10 })

    fireEvent.scroll(el)

    expect(loadOlder).toHaveBeenCalledTimes(1)
  })

  it('does NOT call loadOlder() when the list has no overflow (nothing to scroll)', () => {
    const loadOlder = vi.fn().mockResolvedValue(undefined)
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: makeMessages(2), loadOlder, hasMoreOlder: true }),
    )
    const { container } = render(<ChatWindow />)
    const el = container.querySelector('.overflow-y-auto') as HTMLDivElement
    // scrollHeight === clientHeight: short conversation, nothing to page.
    stubScrollGeometry(el, { scrollHeight: 300, clientHeight: 300, scrollTop: 0 })

    fireEvent.scroll(el)

    expect(loadOlder).not.toHaveBeenCalled()
  })

  it('does NOT call loadOlder() when hasMoreOlder is false (start of history reached)', () => {
    const loadOlder = vi.fn().mockResolvedValue(undefined)
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: makeMessages(3), loadOlder, hasMoreOlder: false }),
    )
    const { container } = render(<ChatWindow />)
    const el = container.querySelector('.overflow-y-auto') as HTMLDivElement
    stubScrollGeometry(el, { scrollHeight: 1000, clientHeight: 400, scrollTop: 10 })

    fireEvent.scroll(el)

    expect(loadOlder).not.toHaveBeenCalled()
  })

  it('preserves scroll position (anchors to the same content) after an older page is prepended', () => {
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: makeMessages(2, 10), hasMoreOlder: true }),
    )
    const { container, rerender } = render(<ChatWindow />)
    const el = container.querySelector('.overflow-y-auto') as HTMLDivElement
    const state = stubScrollGeometry(el, { scrollHeight: 1000, clientHeight: 400, scrollTop: 10 })

    // User scrolls near the top — triggers the pending-anchor bookkeeping.
    fireEvent.scroll(el)

    // Simulate the older page arriving and being prepended: 2 more messages,
    // and the container growing by exactly 400px of new content.
    state.scrollHeight = 1400
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: [...makeMessages(2, 8), ...makeMessages(2, 10)], hasMoreOlder: true }),
    )
    act(() => {
      rerender(<ChatWindow />)
    })

    // scrollTop shifted by exactly the height the prepend added (400px),
    // so the message the user was reading stays under the viewport.
    expect(state.scrollTop).toBe(410)
  })

  it('does not auto-scroll to the bottom while reading history (prepend must not fight the anchor fix)', () => {
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: makeMessages(2, 10), hasMoreOlder: true }),
    )
    const { container, rerender } = render(<ChatWindow />)
    const el = container.querySelector('.overflow-y-auto') as HTMLDivElement
    const state = stubScrollGeometry(el, { scrollHeight: 1000, clientHeight: 400, scrollTop: 10 })

    // Scrolling away from the bottom marks wasNearBottomRef=false.
    fireEvent.scroll(el)

    state.scrollHeight = 1400
    mockUseChat.mockReturnValue(
      baseChatReturn({ messages: [...makeMessages(2, 8), ...makeMessages(2, 10)], hasMoreOlder: true }),
    )
    act(() => {
      rerender(<ChatWindow />)
    })

    // The bottom would be scrollTop === scrollHeight - clientHeight === 1000.
    // The anchor fix should leave scrollTop far short of that.
    expect(state.scrollTop).toBeLessThan(1000)
  })
})
