/**
 * chat.ts — Klaus Hub chat API client.
 *
 * Backend endpoints (26-05, windowing added UAT gap-closure 2026-07):
 *   POST /api/chat          body { content: string } → { ok: true }
 *   GET  /api/chat/messages?limit=&before=&chat_visible= →
 *        { messages: ChatMessage[], has_more: boolean }
 *
 * Security note (T-26-08-01): message content must never be set via
 * dangerouslySetInnerHTML — React's default text rendering escapes it.
 */
import { apiFetch } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Transport metadata for one uploaded attachment, returned by
 * POST /api/chat/upload and echoed back in POST /api/chat. Attachments are
 * TRANSIENT: the server never stores them in conversation history, so this
 * only ever lives client-side for the current session.
 */
export interface AttachmentMeta {
  id: string
  kind: 'image' | 'pdf'
  mime: string
  name: string
  size: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  /** Client-only status for optimistic messages (CHAT-03). */
  status?: 'sending' | 'sent' | 'error'
  /** Client-only id for tracking the optimistic entry. */
  id?: string
  /**
   * Absolute position in the server's stored conversation array at read
   * time (added by the server, D-11 / UAT gap-closure windowing). Absent on
   * client-only optimistic messages until the real message replaces them.
   */
  seq?: number
  /** Client-only: attachments sent with this message (session-local). */
  attachments?: AttachmentMeta[]
  /** Client-only: object URLs for image previews, parallel to attachments. */
  previewUrls?: string[]
}

interface MessagesResponse {
  messages: ChatMessage[]
  /** True when older messages exist beyond this page (UAT gap-closure). */
  has_more?: boolean
}

export interface FetchMessagesResult {
  messages: ChatMessage[]
  hasMore: boolean
}

export interface FetchMessagesOptions {
  /**
   * Phase 29 (D-02): report that the hub chat view is genuinely on-screen
   * so the poll carries `?chat_visible=1` — the server-side push
   * suppression gate (core.scheduled_message.mark_chat_visible) reads this.
   * Defaults to false so callers that don't opt in never report visibility.
   */
  chatVisible?: boolean
  /** Page size. Server default is 50 if omitted. */
  limit?: number
  /**
   * Pagination cursor (UAT gap-closure, "load earlier messages"): when set,
   * the server returns the `limit` messages immediately OLDER than this seq
   * instead of the newest tail.
   */
  before?: number
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch a page of conversation messages from the server.
 *
 * With no `before`, returns the newest `limit` messages (the poll tail —
 * D-08). With `before=<seq>`, returns the `limit` messages immediately
 * older than that seq (scroll-to-top pagination, UAT gap-closure).
 */
export async function fetchMessages(
  options: FetchMessagesOptions = {},
): Promise<FetchMessagesResult> {
  const { chatVisible = false, limit, before } = options

  const params = new URLSearchParams()
  if (chatVisible) params.set('chat_visible', '1')
  if (limit !== undefined) params.set('limit', String(limit))
  if (before !== undefined) params.set('before', String(before))

  const qs = params.toString()
  const path = qs ? `/api/chat/messages?${qs}` : '/api/chat/messages'
  const data = await apiFetch<MessagesResponse>(path)
  return { messages: data.messages, hasMore: data.has_more ?? false }
}

/**
 * Send a new user message into the Klaus agent loop.
 * Returns quickly — the agent response arrives asynchronously via polling.
 */
export async function postChatMessage(
  content: string,
  attachments?: AttachmentMeta[],
): Promise<void> {
  await apiFetch<{ ok: boolean }>('/api/chat', {
    method: 'POST',
    body: JSON.stringify(
      attachments && attachments.length > 0 ? { content, attachments } : { content },
    ),
  })
}

/**
 * Upload one attachment (image/PDF) ahead of send. Raw-body upload — the
 * file's own mime rides as Content-Type (overriding apiFetch's JSON default)
 * and the filename goes in the query string, so no multipart encoding is
 * needed. Returns the metadata dict to echo back in postChatMessage.
 */
export async function uploadAttachment(
  blob: Blob,
  filename: string,
): Promise<AttachmentMeta> {
  const params = new URLSearchParams({ filename })
  return apiFetch<AttachmentMeta>(`/api/chat/upload?${params}`, {
    method: 'POST',
    body: blob,
    headers: { 'Content-Type': blob.type || 'application/octet-stream' },
  })
}
