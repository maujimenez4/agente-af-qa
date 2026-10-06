import { useCallback, useEffect, useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import { subscribeEvents } from '../../api/events.ts'
import type { ApiError, ConversationOut, ProgressStep } from '../../api/types.ts'

/** Cada cuánto se consulta el estado si el SSE se corta (DESIGN-DECISIONS.md §3). */
export const POLL_MS = 2000
/**
 * PA-333: vigilante del flujo. Si en `OPEN_TIMEOUT_MS` no han llegado las cabeceras de `/events`, la
 * petición no salió (p. ej. encolada tras otras en el navegador); si el flujo está abierto, cualquier
 * dato (también el `: ping` de cada 15 s de la API) es señal de vida y solo se consulta tras
 * `SILENCE_MS` sin nada. Mientras tanto, GET /conversations/{id} cada `WATCH_POLL_MS`, hasta un estado
 * final o hasta que vuelva a llegar algo del flujo.
 */
export const OPEN_TIMEOUT_MS = 5000
export const SILENCE_MS = 20000
export const WATCH_POLL_MS = 3000

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
    let watchTimer: number | undefined
    // Consultando el estado: porque el flujo se cortó (`disconnected`) o porque el vigilante saltó.
    let polling = false
    let disconnected = false
    // Cada cadena de consultas tiene su número: la respuesta de una cadena anterior no programa otra.
    let chain = 0

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
      const own = chain
      api
        .conversation(initial.id)
        .then((conversation) => {
          if (finished) return
          setState((current) => ({ ...current, steps: conversation.progress }))
          settle(conversation)
          if (!finished && polling && own === chain) pollTimer = window.setTimeout(poll, disconnected ? POLL_MS : WATCH_POLL_MS)
        })
        .catch((cause: unknown) => {
          if (finished) return
          // Consulta del vigilante con el flujo sin cortar: un fallo pasajero (503, red) no termina la
          // generación; se vuelve a consultar. Un 401 ya lo trata la sesión (PA-332).
          if (!disconnected && polling && own === chain) {
            pollTimer = window.setTimeout(poll, WATCH_POLL_MS)
            return
          }
          finished = true
          const error = toApiError(cause)
          setState((current) => ({ status: 'error', steps: current.steps, error, retryable: false }))
        })
    }

    const startPolling = () => {
      if (finished || polling) return
      polling = true
      chain += 1
      poll()
    }

    // El flujo vuelve a dar señales: deja de consultar (si sigue abierto) y vuelve a vigilar el silencio.
    const watch = (ms: number) => {
      window.clearTimeout(watchTimer)
      if (finished || disconnected) return
      watchTimer = window.setTimeout(startPolling, ms)
    }
    const alive = () => {
      if (finished || disconnected) return
      polling = false
      window.clearTimeout(pollTimer)
      watch(SILENCE_MS)
    }
    watch(OPEN_TIMEOUT_MS)

    const close = subscribeEvents(initial.id, {
      onOpen: () => watch(SILENCE_MS),
      onActivity: alive,
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
        if (finished) return
        disconnected = true
        window.clearTimeout(watchTimer)
        window.clearTimeout(pollTimer)
        polling = false
        startPolling()
      },
    })

    return () => {
      finished = true
      close()
      window.clearTimeout(pollTimer)
      window.clearTimeout(watchTimer)
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
