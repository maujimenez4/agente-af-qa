import { useCallback, useEffect, useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import { subscribeEvents } from '../../api/events.ts'
import type { ApiError, ConversationOut, ProgressStep } from '../../api/types.ts'

/** Cada cuánto se consulta el estado si el SSE se corta (DESIGN-DECISIONS.md §3). */
export const POLL_MS = 2000

export type GenerationState =
  | { status: 'running'; steps: ProgressStep[] }
  | { status: 'ready'; steps: ProgressStep[]; conversation: ConversationOut }
  /** `retryable`: la conversación quedó en `state=error` y se puede repetir con POST /retry (PA-276). */
  | { status: 'error'; steps: ProgressStep[]; error: ApiError; retryable: boolean }

export interface Generation {
  state: GenerationState
  /** Se pidió detener (POST /cancel): «Deteniendo…» hasta que termine el paso en curso (PA-314). */
  stopping: boolean
  /** Error al pedir detener (salvo `not_cancellable`, que solo significa que ya terminó). */
  stopError?: ApiError
  stop: () => void
}

function upsert(steps: readonly ProgressStep[], step: ProgressStep): ProgressStep[] {
  const index = steps.findIndex((item) => item.node === step.node)
  if (index < 0) return [...steps, step]
  return steps.map((item, position) => (position === index ? step : item))
}

/**
 * Pide detener la generación (POST /cancel, PA-314). `stopping`: sigue deteniéndose hasta que termine el
 * paso en curso. Un `not_cancellable` no es un error para la persona: ya no estaba generando y el SSE
 * trae el final.
 */
export async function requestStop(id: string): Promise<{ stopping: boolean; error?: ApiError }> {
  try {
    const conversation = await api.cancel(id)
    return { stopping: conversation.cancel_requested || conversation.state === 'generating' }
  } catch (cause) {
    const error = toApiError(cause)
    return error.code === 'not_cancellable' ? { stopping: false } : { stopping: false, error }
  }
}

/**
 * Sigue una conversación que está generando: eventos SSE y, si el flujo se corta sin evento final,
 * GET /conversations/{id} cada POLL_MS hasta que deja de generar.
 */
export function useGeneration(initial: ConversationOut): Generation {
  const [state, setState] = useState<GenerationState>({ status: 'running', steps: initial.progress })
  const [stopping, setStopping] = useState(initial.cancel_requested)
  const [stopError, setStopError] = useState<ApiError | undefined>()
  // Otra conversación que seguir (p. ej. tras POST /retry): se vuelve a «generando» en el mismo render.
  const [followed, setFollowed] = useState(initial)
  if (followed !== initial) {
    setFollowed(initial)
    setState({ status: 'running', steps: initial.progress })
    setStopping(initial.cancel_requested)
    setStopError(undefined)
  }

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
          retryable: true,
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
          const error = toApiError(cause)
          setState((current) => ({ status: 'error', steps: current.steps, error, retryable: false }))
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
        setState((current) => ({
          status: 'error',
          steps: conversation?.progress ?? current.steps,
          error,
          retryable: conversation?.state === 'error',
        }))
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

  const stop = useCallback(() => {
    setStopError(undefined)
    setStopping(true)
    void requestStop(initial.id).then(({ stopping: still, error }) => {
      setStopping(still)
      setStopError(error)
    })
  }, [initial])

  return { state, stopping: stopping && state.status === 'running', stopError, stop }
}
