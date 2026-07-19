/**
 * ChatInput.tsx — Message input area with textarea + attach + send.
 *
 * UI-SPEC Interaction Contracts (Chat):
 *   - Desktop: Enter sends, Shift+Enter inserts newline.
 *   - Phone: send button only (no Enter shortcut to avoid false fires on mobile).
 *   - Send button: accent #6366F1 background, ≥44px on phone (iOS HIG).
 *   - aria-label "Send message" on the button (Copywriting Contract).
 *   - Disables on submit; clears the textarea after successful send.
 *
 * Attachments (hub attachments feature — transient):
 *   - Paperclip button opens a file picker (images + PDFs, max 4 per message);
 *     pasting an image into the textarea attaches it too.
 *   - Upload-on-select: each file is prepared (images downscaled/re-encoded,
 *     see attachmentUtils.ts) and uploaded to /api/chat/upload immediately —
 *     a chip shows the upload state and failures surface before send.
 *   - Send is enabled with text OR ready attachments; blocked while any
 *     upload is still in flight.
 */
import { useEffect, useRef, useState } from 'react'
import { uploadAttachment } from '../../api/chat'
import type { AttachmentMeta } from '../../api/chat'
import type { SendMessageInput } from '../../hooks/useChat'
import { prepareAttachment } from './attachmentUtils'
import { accent, destructive, textPrimary, textSecondary, border, secondary, dominant, fontFamily, typography } from '../../tokens'

const MAX_ATTACHMENTS = 4

interface PendingAttachment {
  localId: string
  name: string
  kind: 'image' | 'pdf'
  /** Object URL for image thumbnails (undefined for PDFs). */
  previewUrl?: string
  status: 'uploading' | 'ready' | 'error'
  meta?: AttachmentMeta
  error?: string
}

interface ChatInputProps {
  onSend: (input: SendMessageInput) => void
  disabled?: boolean
  /** True while Klaus is generating — swaps the send button for Stop. */
  generating?: boolean
  /** Called when the user taps Stop (hub streaming feature). */
  onStop?: () => void
  /**
   * Edit-and-resend (hub message actions): when set, replaces the textarea
   * content and focuses it. The nonce distinguishes repeat edits of the same
   * text.
   */
  prefill?: { value: string; nonce: number } | null
}

export function ChatInput({ onSend, disabled = false, generating = false, onStop, prefill }: ChatInputProps) {
  const [value, setValue] = useState('')
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (prefill) {
      setValue(prefill.value)
      textareaRef.current?.focus()
    }
    // Keyed on the nonce so editing the same message twice re-applies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.nonce])

  function updatePending(localId: string, patch: Partial<PendingAttachment>) {
    setPending((prev) =>
      prev.map((p) => (p.localId === localId ? { ...p, ...patch } : p)),
    )
  }

  async function addFiles(files: File[]) {
    // Enforce the per-message cap across the current chip row.
    const room = MAX_ATTACHMENTS - pending.length
    for (const file of files.slice(0, room)) {
      const localId = `att-${Date.now()}-${Math.random().toString(36).slice(2)}`
      const isImage = file.type.startsWith('image/')
      const chip: PendingAttachment = {
        localId,
        name: file.name || (isImage ? 'photo' : 'file'),
        kind: file.type === 'application/pdf' ? 'pdf' : 'image',
        status: 'uploading',
      }
      setPending((prev) => [...prev, chip])
      try {
        const prepared = await prepareAttachment(file)
        const previewUrl =
          prepared.kind === 'image' ? URL.createObjectURL(prepared.blob) : undefined
        updatePending(localId, { previewUrl, name: prepared.filename })
        const meta = await uploadAttachment(prepared.blob, prepared.filename)
        updatePending(localId, { status: 'ready', meta })
      } catch (err) {
        updatePending(localId, {
          status: 'error',
          error: err instanceof Error ? err.message : 'Upload failed',
        })
      }
    }
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    // Reset so re-selecting the same file fires change again.
    e.target.value = ''
    void addFiles(files)
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(e.clipboardData?.files ?? []).filter(
      (f) => f.type.startsWith('image/') || f.type === 'application/pdf',
    )
    if (files.length > 0) {
      e.preventDefault()
      void addFiles(files)
    }
  }

  function removeChip(localId: string) {
    setPending((prev) => prev.filter((p) => p.localId !== localId))
  }

  const readyChips = pending.filter((p) => p.status === 'ready' && p.meta)
  const uploading = pending.some((p) => p.status === 'uploading')

  function handleSend() {
    const content = value.trim()
    if (disabled || uploading) return
    if (!content && readyChips.length === 0) return
    onSend({
      content,
      attachments:
        readyChips.length > 0 ? readyChips.map((p) => p.meta as AttachmentMeta) : undefined,
      // Parallel to attachments: PDFs contribute undefined (chip render).
      previewUrls:
        readyChips.length > 0 ? readyChips.map((p) => p.previewUrl ?? '') : undefined,
    })
    setValue('')
    // Keep the object URLs alive — the session-local preview registry in
    // useChat still renders them in the thread after send.
    setPending((prev) => prev.filter((p) => p.status === 'error'))
    // Refocus after send
    setTimeout(() => textareaRef.current?.focus(), 0)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Desktop Enter sends; Shift+Enter inserts newline (UI-SPEC).
    // Gate on a fine pointer (mouse/trackpad) so a phone's soft-keyboard
    // "Enter" inserts a newline rather than sending prematurely (IN-05).
    // matchMedia is guarded for non-browser/test environments.
    const hasFinePointer =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(pointer: fine)').matches
    if (e.key === 'Enter' && !e.shiftKey && hasFinePointer) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend =
    !disabled && !uploading && (value.trim().length > 0 || readyChips.length > 0)
  const canAttach = !disabled && pending.length < MAX_ATTACHMENTS

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        borderTop: `1px solid ${border}`,
        backgroundColor: secondary,
        flexShrink: 0,
      }}
    >
      {/* Pending attachment chips */}
      {pending.length > 0 && (
        <div
          style={{
            display: 'flex',
            gap: '8px',
            padding: '10px 16px 0',
            overflowX: 'auto',
          }}
        >
          {pending.map((chip) => (
            <div
              key={chip.localId}
              style={{
                position: 'relative',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: chip.previewUrl ? '0' : '6px 10px',
                borderRadius: '8px',
                border: `1px solid ${chip.status === 'error' ? destructive : border}`,
                backgroundColor: dominant,
                flexShrink: 0,
                maxWidth: '160px',
              }}
            >
              {chip.previewUrl ? (
                <img
                  src={chip.previewUrl}
                  alt={chip.name}
                  style={{
                    width: '48px',
                    height: '48px',
                    objectFit: 'cover',
                    borderRadius: '7px',
                    display: 'block',
                    opacity: chip.status === 'uploading' ? 0.5 : 1,
                  }}
                />
              ) : (
                <span
                  style={{
                    color: chip.status === 'error' ? destructive : textPrimary,
                    fontSize: typography.label.fontSize,
                    fontFamily,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {chip.kind === 'pdf' ? '📄 ' : ''}
                  {chip.status === 'error' ? chip.error || 'Upload failed' : chip.name}
                </span>
              )}

              {/* Upload spinner overlay */}
              {chip.status === 'uploading' && (
                <span
                  aria-label="Uploading attachment"
                  style={{
                    position: chip.previewUrl ? 'absolute' : 'static',
                    inset: 0,
                    margin: 'auto',
                    display: 'inline-block',
                    width: '14px',
                    height: '14px',
                    border: `2px solid ${textSecondary}`,
                    borderTopColor: 'transparent',
                    borderRadius: '50%',
                    animation: 'spin 0.75s linear infinite',
                    flexShrink: 0,
                  }}
                />
              )}

              {/* Remove chip */}
              <button
                onClick={() => removeChip(chip.localId)}
                aria-label={`Remove ${chip.name}`}
                style={{
                  position: 'absolute',
                  top: '-6px',
                  right: '-6px',
                  width: '18px',
                  height: '18px',
                  borderRadius: '50%',
                  border: `1px solid ${border}`,
                  backgroundColor: secondary,
                  color: textPrimary,
                  fontSize: '10px',
                  lineHeight: '1',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: '8px',
          padding: '12px 16px',
        }}
      >
        {/* Hidden file input driven by the paperclip button */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,application/pdf"
          multiple
          onChange={handleFileInputChange}
          style={{ display: 'none' }}
          aria-hidden="true"
          tabIndex={-1}
        />

        {/* Attach button — paperclip, ≥44px touch target */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={!canAttach}
          aria-label="Attach a file"
          style={{
            flexShrink: 0,
            width: '44px',
            height: '44px',
            borderRadius: '10px',
            border: 'none',
            backgroundColor: 'transparent',
            color: canAttach ? textSecondary : '#2A2A2A',
            cursor: canAttach ? 'pointer' : 'not-allowed',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {/* Paperclip icon */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M21 12.5l-8.5 8.5a6 6 0 01-8.5-8.5L12.5 4a4 4 0 015.7 5.7L9.7 18.2a2 2 0 01-2.8-2.8l8.5-8.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="sr-only">Attach a file</span>
        </button>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Message Klaus…"
          disabled={disabled}
          rows={1}
          style={{
            flex: 1,
            resize: 'none',
            border: `1px solid ${border}`,
            borderRadius: '8px',
            backgroundColor: '#0A0A0A',
            color: textPrimary,
            fontSize: typography.body.fontSize,
            fontWeight: typography.body.fontWeight,
            lineHeight: String(typography.body.lineHeight),
            fontFamily,
            padding: '10px 12px',
            outline: 'none',
            // Auto-resize up to ~4 rows
            maxHeight: '100px',
            overflowY: 'auto',
          }}
          aria-label="Message Klaus"
        />

        {/* Send button — accent bg, ≥44px touch target (iOS HIG, UI-SPEC).
            While Klaus is generating it becomes a Stop button (hub streaming). */}
        {generating ? (
          <button
            onClick={() => onStop?.()}
            aria-label="Stop generating"
            style={{
              flexShrink: 0,
              width: '44px',
              height: '44px',
              borderRadius: '10px',
              border: `1px solid ${border}`,
              backgroundColor: '#2A2A2A',
              color: textPrimary,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background-color 0.15s',
              flexDirection: 'column',
            }}
          >
            {/* Stop icon — square */}
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <rect x="1" y="1" width="12" height="12" rx="2" fill="currentColor" />
            </svg>
            <span className="sr-only">Stop generating</span>
          </button>
        ) : (
        <button
          onClick={handleSend}
          disabled={!canSend}
          aria-label="Send message"
          style={{
            flexShrink: 0,
            width: '44px',
            height: '44px',
            borderRadius: '10px',
            border: 'none',
            backgroundColor: canSend ? accent : '#2A2A2A',
            color: canSend ? '#FFFFFF' : textSecondary,
            cursor: canSend ? 'pointer' : 'not-allowed',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'background-color 0.15s',
            flexDirection: 'column',
          }}
        >
          {/* Send icon — paper plane */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 18 18"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M16 2L8.5 9.5M16 2L11 16L8.5 9.5M16 2L2 7L8.5 9.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {/* Screen-reader visible label */}
          <span className="sr-only">Send message</span>
        </button>
        )}
      </div>
    </div>
  )
}
