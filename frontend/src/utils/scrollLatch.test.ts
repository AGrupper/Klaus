/**
 * scrollLatch — the global "did the page just move?" gate that finally stops
 * a pull-down from opening the Customize sheet.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { recentlyScrolled, __setLastMovementForTests } from './scrollLatch'

beforeEach(() => {
  __setLastMovementForTests(0)
})

describe('scrollLatch', () => {
  it('is quiet when nothing has moved', () => {
    expect(recentlyScrolled()).toBe(false)
  })

  it('latches immediately after movement', () => {
    __setLastMovementForTests(Date.now())
    expect(recentlyScrolled()).toBe(true)
  })

  it('releases once the quiet period has passed', () => {
    __setLastMovementForTests(Date.now() - 1000)
    expect(recentlyScrolled()).toBe(false)
  })

  it('honours a caller-supplied window', () => {
    __setLastMovementForTests(Date.now() - 300)
    expect(recentlyScrolled(200)).toBe(false)
    expect(recentlyScrolled(1000)).toBe(true)
  })

  it('is fed by scroll and touchmove anywhere in the app', () => {
    // Listeners are registered at module load in the capture phase, so an
    // event on any descendant reaches the latch.
    const child = document.createElement('div')
    document.body.appendChild(child)
    child.dispatchEvent(new Event('scroll', { bubbles: true }))
    expect(recentlyScrolled()).toBe(true)

    __setLastMovementForTests(0)
    child.dispatchEvent(new Event('touchmove', { bubbles: true }))
    expect(recentlyScrolled()).toBe(true)
    child.remove()
  })
})
