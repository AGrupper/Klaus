/**
 * useChat.ts — Optimistic send (useMutation) + 2.5s polling (useQuery).
 *
 * Implements RESEARCH Pattern 5 (CHAT-03):
 *   - useQuery polls /api/chat/messages every 2500ms ONLY when the chat is
 *     visible (isVisible arg). Pauses on tab blur (TanStack default:
 *     refetchIntervalInBackground: false).
 *   - useMutation does optimistic send: appends a { status:'sending' } message
 *     immediately, rolls back on error, invalidates on settle so the real
 *     server message replaces it.
 *   - isKlausThinking: true while the last message is role 'user' (turn in
 *     flight); false once an assistant message arrives.
 *
 * Security note (T-26-08-04): "sent" (green) state is shown only AFTER the
 * POST ACKs. onError rolls back + marks status:'error' so the user can retry.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchMessages, postChatMessage } from '../api/chat'
import type { ChatMessage } from '../api/chat'

export const CHAT_QUERY_KEY = ['chat', 'messages'] as const

/**
 * Main hook for the chat panel.
 *
 * @param isVisible - Controls whether polling is active. Pass `true` when the
 *   ChatWindow is mounted and the user can see it; `false` when off-screen or
 *   collapsed so we don't waste agent turns (T-26-08-02).
 */
export function useChat(isVisible: boolean = true) {
  const queryClient = useQueryClient()

  // -------------------------------------------------------------------------
  // Polling query — 2.5s cadence while visible (CHAT-03, T-26-08-02)
  // -------------------------------------------------------------------------
  const query = useQuery({
    queryKey: CHAT_QUERY_KEY,
    queryFn: fetchMessages,
    refetchInterval: isVisible ? 2500 : false,
    // Pause when the browser tab loses focus (TanStack default; explicit here
    // for clarity and test-ability).
    refetchIntervalInBackground: false,
    // Treat stale data as still valid between poll cycles so we don't
    // show a loading flicker on every refetch.
    staleTime: 0,
  })

  const messages: ChatMessage[] = query.data ?? []

  // -------------------------------------------------------------------------
  // "Klaus is thinking…" indicator condition
  // When the last message is from the user, a turn is in-flight.
  // Clear when an assistant message arrives.
  // -------------------------------------------------------------------------
  const isKlausThinking =
    messages.length > 0 && messages[messages.length - 1].role === 'user'

  // -------------------------------------------------------------------------
  // Optimistic send mutation (CHAT-03)
  // -------------------------------------------------------------------------
  const mutation = useMutation({
    mutationFn: (content: string) => postChatMessage(content),

    onMutate: async (content: string) => {
      // 1. Cancel any in-flight refetch to avoid a race that overwrites our
      //    optimistic entry before the mutation resolves.
      await queryClient.cancelQueries({ queryKey: CHAT_QUERY_KEY })

      // 2. Snapshot the current messages so we can roll back on error.
      const previous = queryClient.getQueryData<ChatMessage[]>(CHAT_QUERY_KEY)

      // 3. Append the optimistic message with status 'sending'.
      const optimisticMessage: ChatMessage = {
        id: `optimistic-${Date.now()}`,
        role: 'user',
        content,
        status: 'sending',
      }
      queryClient.setQueryData<ChatMessage[]>(CHAT_QUERY_KEY, (old) => [
        ...(old ?? []),
        optimisticMessage,
      ])

      return { previous, optimisticId: optimisticMessage.id }
    },

    onError: (_err, _content, context) => {
      // Roll back to the snapshot — the POST failed, so the message never
      // reached the server (T-26-08-04).
      if (context?.previous !== undefined) {
        queryClient.setQueryData<ChatMessage[]>(CHAT_QUERY_KEY, context.previous)
      }
    },

    onSettled: () => {
      // Whether success or error, re-sync with the server so the real
      // message (or absence of it) replaces the optimistic entry.
      queryClient.invalidateQueries({ queryKey: CHAT_QUERY_KEY })
    },
  })

  return {
    messages,
    isLoading: query.isLoading,
    isError: query.isError,
    isKlausThinking,
    sendMessage: mutation.mutate,
    isSending: mutation.isPending,
  }
}
