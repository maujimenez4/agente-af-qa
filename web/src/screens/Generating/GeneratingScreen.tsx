import { useEffect, useRef, useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, ChatEvent, ChatLog } from '../../components/Chat/index.ts'
import { Composer } from '../../components/Composer/index.ts'
import { ErrorCard, LoadingState, presentError, Skeleton } from '../../components/States/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import styles from './Generating.module.css'
import { VIEW_PROPOSAL, VIEW_SUITE, WRITING_PROPOSAL, WRITING_SUITE } from '../../text/assistant.ts'
import { qaHeaderTitle, readyHeadline } from './headline.ts'
import { useGeneration } from './useGeneration.ts'

export interface GeneratingScreenProps {
  conversation: ConversationOut
  /** La propuesta está lista (review_ready): abre Iterar. */
  onReady: (conversation: ConversationOut) => void
  /**
   * Sin conversación que reintentar (un fallo al leer el estado, o `/retry` sin nada que repetir):
   * vuelve a Origen y fuentes con la misma operación o, si no la hay, a Inicio.
   */
  onRetry: () => void
  /** Llegó la propuesta o la suite (review_ready): la lista de conversaciones deja de decir «En curso». */
  onReviewReady?: () => void
}

// Mixta 2b · Generando (UI.md §4.4): la Q de carga avanza con los eventos del SSE.
// *Detener* (PA-314) en el compositor; *Reintentar* repite el paso que falló con POST /retry (PA-276).
export function GeneratingScreen({ conversation, onReady, onRetry, onReviewReady }: GeneratingScreenProps) {
  const [current, setCurrent] = useState(conversation)
  const [retryError, setRetryError] = useState<ApiError | undefined>()
  const { state, stopping, stopError, stop } = useGeneration(current)
  const ready = state.status === 'ready' ? state.conversation : undefined
  // Una vez por propuesta lista, no en cada pintado: el callback se lee de una referencia.
  const reviewReady = useRef(onReviewReady)
  useEffect(() => {
    reviewReady.current = onReviewReady
  })
  const readyId = ready?.id
  useEffect(() => {
    if (readyId) reviewReady.current?.()
  }, [readyId])
  // QA 2 (UI.md §6.2): el mismo patrón con los textos de la suite.
  const qa = conversation.mode === 'qa'

  const retry = async () => {
    setRetryError(undefined)
    try {
      setCurrent(await api.retry(current.id))
    } catch (cause) {
      setRetryError(toApiError(cause))
    }
  }

  // «Actualizar» tras un `/retry` rechazado (p. ej. not_in_error): se lee el estado y se sigue desde ahí.
  const refresh = async () => {
    setRetryError(undefined)
    try {
      const next = await api.conversation(current.id)
      if (next.state === 'in_review') onReady(next)
      else if (next.state === 'generating') setCurrent(next)
      else onRetry()
    } catch (cause) {
      setRetryError(toApiError(cause))
    }
  }

  // Acción de la tarjeta si falla el propio /retry: un fallo pasajero (429, 503…) vuelve a pedir /retry,
  // no abandona la conversación; not_in_error lee el estado; lo demás vuelve a Origen o a Inicio.
  const retryAction = (failure: ApiError): (() => void) => {
    switch (presentError(failure).action) {
      case 'refresh':
        return () => void refresh()
      case 'retry':
      case 'regenerate':
        return () => void retry()
      default:
        return onRetry
    }
  }

  const panel = (
    <SidePanel title={qa ? 'Suite de pruebas' : 'Propuesta de HU'} size="md">
      {state.status === 'ready' ? (
        <p className={styles.note}>{qa ? 'La suite está lista. Ábrela para revisarla.' : 'La propuesta está lista. Ábrela para revisarla.'}</p>
      ) : (
        <>
          <p className={styles.note}>
            {qa ? 'La suite aparece aquí cuando la cobertura está comprobada.' : 'La propuesta aparece aquí cuando las citas están comprobadas.'}
          </p>
          {state.status === 'running' && <Skeleton lines={8} />}
        </>
      )}
    </SidePanel>
  )

  const loadingTitle = ready
    ? readyHeadline(ready)
    : stopping
      ? 'Deteniendo la generación…'
      : qa
        ? WRITING_SUITE
        : WRITING_PROPOSAL

  return (
    <Workspace
      title={qa ? qaHeaderTitle(conversationTitle(conversation.title)) : conversationTitle(conversation.title)}
      phase={2}
      panel={panel}
      composer={
        <Composer
          placeholder={qa ? 'Espera a la suite para pedir cambios' : 'Espera a la propuesta para pedir cambios'}
          value=""
          onChange={() => undefined}
          onSubmit={() => undefined}
          canSubmit={false}
          disabled
          onStop={state.status === 'running' ? stop : undefined}
          stopping={stopping}
        />
      }
    >
      <ChatLog>
        <ChatEvent>
          {qa ? 'Generar la suite' : 'Generar propuesta'} · {conversationTitle(conversation.title)}
        </ChatEvent>
        <AssistantMessage>
          {retryError ? (
            <ErrorCard key={`retry-${retryError.code}-${retryError.message}`} error={retryError} onAction={retryAction(retryError)} />
          ) : state.status === 'error' ? (
            <ErrorCard
              key={`${state.error.code}-${state.error.message}`}
              error={state.error}
              onAction={state.retryable ? () => void retry() : onRetry}
            />
          ) : (
            <LoadingState title={loadingTitle} events={state.steps} reviewReady={state.status === 'ready'} />
          )}
          {stopError && state.status === 'running' && <ErrorCard key={`stop-${stopError.code}`} error={stopError} />}
          {ready && (
            <div className={styles.rise}>
              <Button variant="primary" onClick={() => onReady(ready)}>
                {qa ? VIEW_SUITE : VIEW_PROPOSAL}
              </Button>
            </div>
          )}
        </AssistantMessage>
      </ChatLog>
    </Workspace>
  )
}
