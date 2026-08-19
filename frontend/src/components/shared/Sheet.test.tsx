/**
 * Sheet.test.tsx — the sheet must fit in the space left by the keyboard.
 *
 * Amit's 2026-08-19 phone UAT: opening "New item" and typing the name lifted
 * the sheet by the keyboard inset (correct) while its height stayed capped at
 * 88dvh of the *layout* viewport (wrong) — so the sheet's top, holding the
 * field being typed into, was pushed off the top of the screen. Nothing could
 * scroll it back: the clipping happened at the viewport edge, not inside the
 * sheet's scroll region, which had no overflow to scroll.
 *
 * The cap must therefore shrink by the same inset that lifts the sheet.
 */
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { Sheet } from './Sheet'

const ORIGINAL_VV = window.visualViewport
const ORIGINAL_INNER_HEIGHT = window.innerHeight

function setKeyboard(insetPx: number) {
  Object.defineProperty(window, 'innerHeight', { value: 850, configurable: true, writable: true })
  Object.defineProperty(window, 'visualViewport', {
    value: {
      height: 850 - insetPx,
      offsetTop: 0,
      addEventListener() {},
      removeEventListener() {},
    },
    configurable: true,
    writable: true,
  })
}

/** The hook only reports an inset while a text field holds focus. */
function focusTextField(): HTMLInputElement {
  const input = document.createElement('input')
  input.type = 'text'
  document.body.appendChild(input)
  input.focus()
  return input
}

afterEach(() => {
  Object.defineProperty(window, 'visualViewport', { value: ORIGINAL_VV, configurable: true, writable: true })
  Object.defineProperty(window, 'innerHeight', { value: ORIGINAL_INNER_HEIGHT, configurable: true, writable: true })
})

describe('Sheet height with the keyboard open', () => {
  it('shrinks its max height by the keyboard inset that lifts it', () => {
    const field = focusTextField()
    setKeyboard(380)

    render(
      <Sheet open onClose={() => {}} title="New item">
        <p>body</p>
      </Sheet>,
    )

    const dialog = screen.getByRole('dialog')
    expect(dialog.style.bottom).toBe('380px')
    // Lifted 380px AND capped at 88dvh would put the top ~318px off-screen.
    expect(dialog.style.maxHeight).toBe('calc(88dvh - 380px)')
    field.remove()
  })

  it('drops the tab-bar clearance while the keyboard covers the tab bar', () => {
    const field = focusTextField()
    setKeyboard(380)
    render(
      <Sheet open onClose={() => {}} title="New item">
        <p>body</p>
      </Sheet>,
    )
    // 76px of clearance for controls hidden behind the keyboard would eat a
    // fifth of the room the shortened sheet has left for the form.
    expect(screen.getByText('body').parentElement!.style.paddingBottom).toBe('16px')
    field.remove()
  })

  it('keeps the full cap when no keyboard is open', () => {
    setKeyboard(0)
    render(
      <Sheet open onClose={() => {}} title="New item">
        <p>body</p>
      </Sheet>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog.style.bottom).toBe('0px')
    expect(dialog.style.maxHeight).toBe('88dvh')
  })
})
