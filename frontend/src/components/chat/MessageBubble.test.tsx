/**
 * MessageBubble.test.tsx — Markdown rendering in Klaus bubbles (2026-07-06).
 *
 * The brain emits Markdown (**bold**, pipe tables, bullets, `code`) which
 * used to render as raw asterisks/pipes. Klaus messages now render through
 * react-markdown (GFM); user messages stay literal plain text; the
 * T-26-08-01 invariant holds — embedded raw HTML is inert text, never
 * parsed (no rehype-raw, no dangerouslySetInnerHTML).
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import type { ChatMessage } from '../../api/chat'
import { MessageBubble } from './MessageBubble'

function msg(role: ChatMessage['role'], content: string): ChatMessage {
  return { id: `m-${role}`, role, content } as ChatMessage
}

describe('MessageBubble markdown rendering', () => {
  it('renders **bold** in Klaus messages as <strong>, without literal asterisks', () => {
    render(<MessageBubble message={msg('assistant', 'hit **150g** today')} />)
    const strong = screen.getByText('150g')
    expect(strong.tagName).toBe('STRONG')
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument()
  })

  it('renders GFM pipe tables as a real <table>', () => {
    const table = '| Rep | Pace |\n| --- | --- |\n| 1 | 4:02/km |'
    const { container } = render(<MessageBubble message={msg('assistant', table)} />)
    expect(container.querySelector('table')).toBeInTheDocument()
    expect(screen.getByText('4:02/km').closest('td')).toBeInTheDocument()
    expect(container.textContent).not.toContain('|')
  })

  it('renders bullet lists as <ul>', () => {
    const { container } = render(
      <MessageBubble message={msg('assistant', '- first\n- second')} />,
    )
    expect(container.querySelector('ul')).toBeInTheDocument()
    expect(container.querySelectorAll('li')).toHaveLength(2)
  })

  it('keeps raw HTML in Klaus messages inert (T-26-08-01)', () => {
    const { container } = render(
      <MessageBubble message={msg('assistant', 'try <img src=x onerror=alert(1)>')} />,
    )
    expect(container.querySelector('img')).not.toBeInTheDocument()
  })

  it('leaves user messages as literal plain text (no markdown parsing)', () => {
    render(<MessageBubble message={msg('user', 'is **this** bold?')} />)
    expect(screen.getByText('is **this** bold?')).toBeInTheDocument()
  })
})

describe('MessageBubble attachments (transient session previews)', () => {
  it('renders an image attachment as an <img> using its preview URL', () => {
    const message = {
      id: 'm-att',
      role: 'user',
      content: 'look',
      attachments: [
        { id: 'a'.repeat(32), kind: 'image', mime: 'image/jpeg', name: 'photo.jpg', size: 10 },
      ],
      previewUrls: ['blob:fake-preview'],
    } as ChatMessage
    render(<MessageBubble message={message} />)
    const img = screen.getByRole('img', { name: 'photo.jpg' })
    expect(img).toHaveAttribute('src', 'blob:fake-preview')
  })

  it('renders a PDF attachment as a file chip with its name', () => {
    const message = {
      id: 'm-pdf',
      role: 'user',
      content: '',
      attachments: [
        { id: 'b'.repeat(32), kind: 'pdf', mime: 'application/pdf', name: 'report.pdf', size: 999 },
      ],
    } as ChatMessage
    render(<MessageBubble message={message} />)
    expect(screen.getByText('report.pdf')).toBeInTheDocument()
  })

  it('renders an image attachment without a preview URL as a named chip (post-refresh fallback)', () => {
    const message = {
      id: 'm-noprev',
      role: 'user',
      content: '',
      attachments: [
        { id: 'c'.repeat(32), kind: 'image', mime: 'image/jpeg', name: 'old.jpg', size: 5 },
      ],
    } as ChatMessage
    render(<MessageBubble message={message} />)
    expect(screen.getByText('old.jpg')).toBeInTheDocument()
  })
})
