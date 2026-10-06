import { useCallback, useEffect, useState } from 'react'
import { api, ApiRequestError } from '../api/client.ts'
import type { ApiError, ConversationSummary } from '../api/types.ts'
import { qualityReviewView, type ConversationSummaryView } from '../components/ConversationList/index.ts'

export interface ConversationsState {
  conversations: ConversationSummaryView[]
  error?: ApiError
  reload: () => void
}

function byUpdatedDesc(a: ConversationSummaryView, b: ConversationSummaryView): number {
  return (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0)
}

/**
 * Conversaciones de la persona (`GET /conversations`, más recientes primero) y, con `withQuality`, sus revisiones
 * de calidad (`GET /quality-reviews`) juntas por `updated_at` (docs/api/README.md, PA-103). Si solo fallan las
 * revisiones, la lista sigue con las conversaciones: las revisiones vuelven en la siguiente recarga.
 */
export function useConversations(withQuality = false): ConversationsState {
  const [conversations, setConversations] = useState<ConversationSummaryView[]>([])
  const [error, setError] = useState<ApiError | undefined>()
  const [round, setRound] = useState(0)

  useEffect(() => {
    let cancelled = false
    const reviews = withQuality ? api.qualityReviews().catch(() => []) : Promise.resolve([])
    Promise.all([api.conversations(), reviews])
      .then(([items, quality]: [ConversationSummary[], Awaited<typeof reviews>]) => {
        if (cancelled) return
        setConversations(quality.length === 0 ? items : [...items, ...quality.map(qualityReviewView)].sort(byUpdatedDesc))
        setError(undefined)
      })
      .catch((cause: unknown) => {
        if (!cancelled && cause instanceof ApiRequestError) setError(cause.error)
      })
    return () => {
      cancelled = true
    }
  }, [round, withQuality])

  const reload = useCallback(() => setRound((current) => current + 1), [])
  return { conversations, error, reload }
}
