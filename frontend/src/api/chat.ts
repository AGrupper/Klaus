/**
 * chat.ts — Klaus Hub chat API client.
 *
 * Backend endpoints (26-05):
 *   POST /api/chat          body { content: string } → { ok: true }
 *   GET  /api/chat/messages → { messages: ChatMessage[] }
 *
 * Security note (T-26-08-01): message content must never be set via
 * dangerouslySetInnerHTML — React's default text rendering escapes it.
 */
import { apiFetch } from './client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  /** Client-only status for optimistic messages (CHAT-03). */
  status?: 'sending' | 'sent' | 'error'
  /** Client-only id for tracking the optimistic entry. */
  id?: string
}

interface MessagesResponse {
  messages: ChatMessage[]
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch recent conversation messages from the server.
 * The server returns the full conversation window (up to 100);
 * the caller slices to ~50 for initial display (D-08).
 */
export async function fetchMessages(): Promise<ChatMessage[]> {
  const data = await apiFetch<MessagesResponse>('/api/chat/messages')
  return data.messages
}

/**
 * Send a new user message into the Klaus agent loop.
 * Returns quickly — the agent response arrives asynchronously via polling.
 */
export async function postChatMessage(content: string): Promise<void> {
  await apiFetch<{ ok: boolean }>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}
