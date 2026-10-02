import { useEffect, useState } from 'react'
import { api, ApiRequestError } from '../../api/client.ts'
import { subscribeEvents } from '../../api/events.ts'
import type { ApiError, ConversationOut, ProgressStep } from '../../api/types.ts'

/** Cada cuánto se consulta el estado si el SSE se corta (DESIGN-DECISIONS.md §3). */
export const POLL_MS = 2000

export type GenerationState =
  | { status: 'running'; steps: ProgressStep[] }
  | { status: 'ready'; steps: ProgressStep[]; conversation: ConversationOut }
  | { status: 'error'; steps: ProgressStep[]; error: ApiError }

function upsert(steps: readonly ProgressStep[], step: ProgressStep): ProgressStep[] {
  const index = steps.findIndex((item) => item.node === step.node)
  if (index < 0) return [...steps, step]
  return steps.map((item, position) => (position === index ? step : item))
}

/**
 * Sigue una conversación que está generando: eventos SSE y, si el flujo se corta sin evento final,
 * GET /conversations/{id} cada POLL_MS hasta que deja de generar.
 */
export function useGeneration(initial: ConversationOut): GenerationState {
  const [state, setState] = useState<GenerationState>({ status: 'running', steps: initial.progress })

  useEffect(() => {
    let finished = false
    let pollTimer: number | undefined

    const settle = (conversation: ConversationOut) => {
      if (finished) return
      if (conversation.state === 'generating') return
      finished = true
      if (conversation.state === 'error') {
        setState({
          status: 'error',
          steps: conversation.progress,
          error: conversation.error ?? { code: 'restart', message: 'Esta conversación no puede continuar. Empieza una nueva; nada se ha escrito en Jira.' },
        })
      } else {
        setState({ status: 'ready', steps: conversation.progress, conversation })
      }
    }

    const poll = () => {
      api
        .conversation(initial.id)
        .then((conversation) => {
          if (finished) return
          setState((current) => ({ ...current, steps: conversation.progress }))
          settle(conversation)
          if (!finished) pollTimer = window.setTimeout(poll, POLL_MS)
        })
        .catch((cause: unknown) => {
          if (finished) return
          finished = true
          const error = cause instanceof ApiRequestError ? cause.error : { code: 'unexpected', message: 'Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo.' }
          setState((current) => ({ status: 'error', steps: current.steps, error }))
        })
    }

    const close = subscribeEvents(initial.id, {
      onProgress: (step) => setState((current) => (current.status === 'running' ? { ...current, steps: upsert(current.steps, step) } : current)),
      onReviewReady: settle,
      onResult: settle,
      onError: (error, conversation) => {
        if (finished) return
        // Un error al abrir el flujo (p. ej. too_many_streams) no es un fallo de la generación: se consulta.
        if (!conversation && (error.code === 'too_many_streams' || error.code === 'not_found')) return
        finished = true
        setState((current) => ({ status: 'error', steps: conversation?.progress ?? current.steps, error }))
      },
      onDisconnect: () => {
        if (!finished) poll()
      },
    })

    return () => {
      finished = true
      close()
      window.clearTimeout(pollTimer)
    }
  }, [initial])

  return state
}
