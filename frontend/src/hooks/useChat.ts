/**
 * useChat.ts — Optimistic send (useMutation) + 2.5s tail polling (useQuery)
 * + scroll-up pagination (UAT gap-closure, 2026-07).
 *
 * Implements RESEARCH Pattern 5 (CHAT-03):
 *   - useQuery polls /api/chat/messages every 2500ms ONLY when the chat is
 *     visible (isVisible arg). Pauses on tab blur (TanStack default:
 *     refetchIntervalInBackground: false). The poll now requests only the
 *     newest TAIL_LIMIT messages (server-side windowing) instead of the
 *     full conversation history on every tick.
 *   - useMutation does optimistic send: appends a { status:'sending' } message
 *     immediately, rolls back on error, invalidates on settle so the real
 *     server message replaces it.
 *   - isKlausThinking: true while the last message is role 'user' (turn in
 *     flight); false once an assistant message arrives.
 *   - loadOlder(): fetches one older page (before=<oldest loaded seq>) and
 *     prepends it to local state, merged + de-duped by `seq` with whatever
 *     the live tail poll currently holds. hasMoreOlder / isLoadingOlder let
 *     ChatWindow drive an on-reach-top affordance.
 *
 * Security note (T-26-08-04): "sent" (green) state is shown only AFTER the
 * POST ACKs. onError rolls back + marks status:'error' so the user can retry.
 */
import { useCallback, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchMessages,
  postChatMessage,
  regenerateReply as apiRegenerateReply,
  stopGeneration as apiStopGeneration,
} from '../api/chat'
import type { AttachmentMeta, ChatMessage } from '../api/chat'

export const CHAT_QUERY_KEY = ['chat', 'messages'] as const

/**
 * Input for sendMessage. A plain string is still accepted (retry path,
 * older callers) and means "text only".
 */
export interface SendMessageInput {
  content: string
  attachments?: AttachmentMeta[]
  /** Object URLs for image previews, parallel to `attachments`. */
  previewUrls?: string[]
}

// Page size for both the live poll tail and each "load earlier" page.
const TAIL_LIMIT = 50

/**
 * Merge an older page and the live tail into one ascending-by-seq list,
 * de-duplicating by `seq` (falling back to reference identity for
 * client-only entries such as the in-flight optimistic message, which has
 * no `seq` yet). `older` is assumed to sort entirely before `tail` — true
 * here because `older` is always fetched with `before=<tail's oldest seq>`.
 */
function mergeMessages(older: ChatMessage[], tail: ChatMessage[]): ChatMessage[] {
  const seenSeqs = new Set<number>()
  const merged: ChatMessage[] = []
  for (const list of [older, tail]) {
    for (const msg of list) {
      if (typeof msg.seq === 'number') {
        if (seenSeqs.has(msg.seq)) continue
        seenSeqs.add(msg.seq)
      }
      merged.push(msg)
    }
  }
  return merged
}

/**
 * The highest known absolute seq + 1 (i.e. the true total conversation
 * length as of the last successful read), derived by scanning from the end
 * of `messages` for the last entry that carries a server-assigned `seq`.
 * Falls back to `messages.length` when no message has a `seq` yet (e.g. an
 * all-optimistic array, or tests that don't set seq) so existing unread-
 * count math keeps working. Exported for BottomTabs/DockChat/ChatWindow,
 * which all need this instead of raw `messages.length` now that the tail
 * poll no longer always starts at seq 0 (UAT gap-closure windowing).
 */
export function latestKnownSeq(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    const seq = messages[i].seq
    if (typeof seq === 'number') return seq + 1
  }
  return messages.length
}

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
  // Polling query — 2.5s cadence while visible (CHAT-03, T-26-08-02).
  // Requests only the newest TAIL_LIMIT messages (UAT gap-closure: the full
  // history used to ship over the wire on every 2.5s tick).
  // -------------------------------------------------------------------------
  const query = useQuery({
    queryKey: CHAT_QUERY_KEY,
    // Phase 29 (D-02): thread isVisible into fetchMessages so every poll while
    // the chat is genuinely on-screen carries chat_visible=1 — this is the
    // client half of the server-side push-suppression gate. The closure is
    // fresh per render, and refetchInterval below already gates polling on
    // isVisible, so chat_visible=1 is only ever sent while truly visible.
    queryFn: () => fetchMessages({ chatVisible: isVisible, limit: TAIL_LIMIT }),
    // Hub streaming: while a turn is in flight (last message is the user's)
    // poll fast (~800ms) so the draft bubble grows smoothly; idle polls stay
    // at the original 2.5s cadence.
    refetchInterval: (q) => {
      if (!isVisible) return false
      const msgs = q.state.data?.messages
      const turnInFlight =
        !!msgs && msgs.length > 0 && msgs[msgs.length - 1].role === 'user'
      return turnInFlight ? 800 : 2500
    },
    // Pause when the browser tab loses focus (TanStack default; explicit here
    // for clarity and test-ability).
    refetchIntervalInBackground: false,
    // Treat stale data as still valid between poll cycles so we don't
    // show a loading flicker on every refetch.
    staleTime: 0,
  })

  const tailMessages: ChatMessage[] = query.data?.messages ?? []

  // -------------------------------------------------------------------------
  // Scroll-up pagination state (UAT gap-closure): older pages loaded via
  // loadOlder() are held separately from the polled tail and merged for
  // consumption, so the 2.5s poll can keep replacing just the tail without
  // clobbering history the user scrolled back to see.
  // -------------------------------------------------------------------------
  const [olderMessages, setOlderMessages] = useState<ChatMessage[]>([])
  const [hasMoreOlder, setHasMoreOlder] = useState(true)
  const [isLoadingOlder, setIsLoadingOlder] = useState(false)

  // -------------------------------------------------------------------------
  // Session-local attachment previews (hub attachments feature).
  // Attachments are transient — the server stores only the text — so once the
  // poll replaces the optimistic entry with the real server message the chips
  // would vanish mid-conversation. This registry re-attaches each sent
  // attachment set to the LAST attachment-less user message with the same
  // content, keeping previews visible until refresh (accepted behavior).
  // -------------------------------------------------------------------------
  const [sentAttachments, setSentAttachments] = useState<
    { content: string; attachments: AttachmentMeta[]; previewUrls?: string[] }[]
  >([])

  const messages: ChatMessage[] = useMemo(() => {
    const merged = mergeMessages(olderMessages, tailMessages)
    if (sentAttachments.length === 0) return merged
    const annotated = [...merged]
    for (const sent of sentAttachments) {
      for (let i = annotated.length - 1; i >= 0; i--) {
        const m = annotated[i]
        if (m.role === 'user' && m.content === sent.content && !m.attachments) {
          annotated[i] = {
            ...m,
            attachments: sent.attachments,
            previewUrls: sent.previewUrls,
          }
          break
        }
      }
    }
    return annotated
  }, [olderMessages, tailMessages, sentAttachments])

  /**
   * Fetch the page immediately older than the oldest currently-loaded
   * message and prepend it. No-ops while already loading, once the start
   * of history has been reached, or before any message with a `seq` has
   * loaded (nothing to anchor the cursor to yet).
   */
  const loadOlder = useCallback(async () => {
    if (isLoadingOlder || !hasMoreOlder) return
    const oldest = messages[0]
    if (!oldest || typeof oldest.seq !== 'number') {
      setHasMoreOlder(false)
      return
    }
    setIsLoadingOlder(true)
    try {
      const page = await fetchMessages({ before: oldest.seq, limit: TAIL_LIMIT })
      setOlderMessages((prev) => mergeMessages(page.messages, prev))
      setHasMoreOlder(page.hasMore)
    } finally {
      setIsLoadingOlder(false)
    }
  }, [isLoadingOlder, hasMoreOlder, messages])

  // -------------------------------------------------------------------------
  // "Klaus is thinking…" indicator condition
  // When the last message is from the user, a turn is in-flight.
  // Clear when an assistant message arrives.
  // -------------------------------------------------------------------------
  const isKlausThinking =
    messages.length > 0 && messages[messages.length - 1].role === 'user'

  // -------------------------------------------------------------------------
  // Streaming draft (hub streaming feature): the poll carries the text Klaus
  // is generating right now; null when no turn is in flight. Only meaningful
  // while the last message is still the user's — once the real assistant
  // message lands, any stale draft from the same poll cycle is ignored.
  // -------------------------------------------------------------------------
  const draft = query.data?.draft
  const streamingDraft: string | null =
    isKlausThinking && draft && draft.status === 'generating' && draft.text
      ? draft.text
      : null

  const stopGeneration = useCallback(() => {
    // Fire-and-forget: the worker picks the flag up on its next throttled
    // write; the UI reflects the stop when the partial reply lands via poll.
    void Promise.resolve(apiStopGeneration()).catch(() => {
      // A failed stop request is non-fatal — the reply simply completes.
    })
  }, [])

  const regenerate = useCallback(() => {
    // Refetch immediately after the pop so the old reply disappears and the
    // typing indicator returns (last message becomes the user's again); the
    // regenerated reply then arrives via the fast poll like any other turn.
    void Promise.resolve(apiRegenerateReply())
      .catch(() => {
        // 409 (nothing to regenerate — e.g. double-tap) or transient failure:
        // non-fatal, the refetch below re-syncs whatever the truth is.
      })
      .finally(() => {
        void queryClient.invalidateQueries({ queryKey: CHAT_QUERY_KEY })
      })
  }, [queryClient])

  // -------------------------------------------------------------------------
  // Optimistic send mutation (CHAT-03)
  // -------------------------------------------------------------------------
  const mutation = useMutation({
    mutationFn: (input: SendMessageInput) =>
      postChatMessage(input.content, input.attachments),

    onMutate: async (input: SendMessageInput) => {
      // 1. Cancel any in-flight refetch to avoid a race that overwrites our
      //    optimistic entry before the mutation resolves.
      await queryClient.cancelQueries({ queryKey: CHAT_QUERY_KEY })

      // 2. Snapshot the current tail so we can roll back on error.
      const previous = queryClient.getQueryData<{ messages: ChatMessage[]; hasMore: boolean }>(
        CHAT_QUERY_KEY,
      )

      // Register the attachment set so previews survive the optimistic →
      // server-message swap (see the annotation pass in `messages` above).
      if (input.attachments && input.attachments.length > 0) {
        const { content, attachments, previewUrls } = input
        setSentAttachments((prev) => [...prev, { content, attachments, previewUrls }])
      }

      // 3. Append the optimistic message with status 'sending'.
      const optimisticMessage: ChatMessage = {
        id: `optimistic-${Date.now()}`,
        role: 'user',
        content: input.content,
        status: 'sending',
        attachments: input.attachments,
        previewUrls: input.previewUrls,
      }
      queryClient.setQueryData<{ messages: ChatMessage[]; hasMore: boolean }>(
        CHAT_QUERY_KEY,
        (old) => ({
          messages: [...(old?.messages ?? []), optimisticMessage],
          hasMore: old?.hasMore ?? false,
        }),
      )

      return { previous, optimisticId: optimisticMessage.id }
    },

    onError: (_err, _content, context) => {
      // Roll back to the snapshot — the POST failed, so the message never
      // reached the server (T-26-08-04).
      if (context?.previous !== undefined) {
        queryClient.setQueryData(CHAT_QUERY_KEY, context.previous)
      }
    },

    onSettled: () => {
      // Whether success or error, re-sync with the server so the real
      // message (or absence of it) replaces the optimistic entry.
      queryClient.invalidateQueries({ queryKey: CHAT_QUERY_KEY })
    },
  })

  // Normalize the plain-string form (retry path, older callers) into
  // SendMessageInput before handing off to the mutation.
  const sendMessage = useCallback(
    (input: string | SendMessageInput) => {
      mutation.mutate(typeof input === 'string' ? { content: input } : input)
    },
    [mutation.mutate],
  )

  return {
    messages,
    isLoading: query.isLoading,
    isError: query.isError,
    isKlausThinking,
    streamingDraft,
    stopGeneration,
    regenerate,
    sendMessage,
    isSending: mutation.isPending,
    loadOlder,
    hasMoreOlder,
    isLoadingOlder,
  }
}
