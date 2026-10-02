import { useCallback, useEffect, useState } from 'react'
import { api, ApiRequestError } from '../api/client.ts'
import type { ApiError, ConversationSummary } from '../api/types.ts'

export interface ConversationsState {
  conversations: ConversationSummary[]
  error?: ApiError
  reload: () => void
}

/** Conversaciones de la persona (`GET /conversations`, más recientes primero). */
export function useConversations(): ConversationsState {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [error, setError] = useState<ApiError | undefined>()
  const [round, setRound] = useState(0)

  useEffect(() => {
    let cancelled = false
    api
      .conversations()
      .then((items) => {
        if (cancelled) return
        setConversations(items)
        setError(undefined)
      })
      .catch((cause: unknown) => {
        if (!cancelled && cause instanceof ApiRequestError) setError(cause.error)
      })
    return () => {
      cancelled = true
    }
  }, [round])

  const reload = useCallback(() => setRound((current) => current + 1), [])
  return { conversations, error, reload }
}
