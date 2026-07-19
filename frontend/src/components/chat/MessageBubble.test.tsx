/**
 * MessageBubble.test.tsx — Markdown rendering in Klaus bubbles (2026-07-06).
 *
 * The brain emits Markdown (**bold**, pipe tables, bullets, `code`) which
 * used to render as raw asterisks/pipes. Klaus messages now render through
 * react-markdown (GFM); user messages stay literal plain text; the
 * T-26-08-01 invariant holds — embedded raw HTML is inert text, never
 * parsed (no rehype-raw, no dangerouslySetInnerHTML).
 */
import { describe, it, expect, vi } from 'vitest'
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

describe('MessageBubble actions (copy / regenerate / edit)', () => {
  it('copy button writes the raw message content to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })

    render(<MessageBubble message={msg('assistant', '**bold** reply')} />)
    const copyBtn = screen.getByRole('button', { name: /copy message/i })
    copyBtn.click()

    expect(writeText).toHaveBeenCalledWith('**bold** reply')
    vi.unstubAllGlobals()
  })

  it('renders a regenerate button only when onRegenerate is provided, and wires it', () => {
    const onRegenerate = vi.fn()
    const { rerender } = render(
      <MessageBubble message={msg('assistant', 'answer')} onRegenerate={onRegenerate} />,
    )
    const regenBtn = screen.getByRole('button', { name: /regenerate/i })
    regenBtn.click()
    expect(onRegenerate).toHaveBeenCalledTimes(1)

    rerender(<MessageBubble message={msg('assistant', 'answer')} />)
    expect(screen.queryByRole('button', { name: /regenerate/i })).toBeNull()
  })

  it('renders an edit button on user messages when onEdit is provided, passing the content', () => {
    const onEdit = vi.fn()
    render(<MessageBubble message={msg('user', 'my typo message')} onEdit={onEdit} />)
    screen.getByRole('button', { name: /edit message/i }).click()
    expect(onEdit).toHaveBeenCalledWith('my typo message')
  })
})

describe('MessageBubble rich code blocks (Workstream D)', () => {
  const pythonFence = '```python\ndef hello():\n    return 42\n```'

  it('syntax-highlights fenced code (hljs token spans present)', () => {
    const { container } = render(<MessageBubble message={msg('assistant', pythonFence)} />)
    expect(container.querySelectorAll('[class*="hljs"]').length).toBeGreaterThan(0)
  })

  it('shows the fence language as a label on the block', () => {
    render(<MessageBubble message={msg('assistant', pythonFence)} />)
    expect(screen.getByText('python')).toBeInTheDocument()
  })

  it('copy-code button copies the raw code text', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })

    render(<MessageBubble message={msg('assistant', pythonFence)} />)
    screen.getByRole('button', { name: /copy code/i }).click()

    expect(writeText).toHaveBeenCalledWith('def hello():\n    return 42\n')
    vi.unstubAllGlobals()
  })

  it('inline code is untouched by block chrome (no label, no copy button)', () => {
    render(<MessageBubble message={msg('assistant', 'use `pip install x` here')} />)
    expect(screen.queryByRole('button', { name: /copy code/i })).toBeNull()
  })
})
