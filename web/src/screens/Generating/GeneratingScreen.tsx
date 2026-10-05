import { useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, ChatEvent, ChatLog } from '../../components/Chat/index.ts'
import { Composer } from '../../components/Composer/index.ts'
import { ErrorCard, LoadingState, presentError, Skeleton } from '../../components/States/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import styles from './Generating.module.css'
import { readyHeadline } from './headline.ts'
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
}

// Mixta 2b · Generando (UI.md §4.4): la Q de carga avanza con los eventos del SSE.
// *Detener* (PA-314) en el compositor; *Reintentar* repite el paso que falló con POST /retry (PA-276).
export function GeneratingScreen({ conversation, onReady, onRetry }: GeneratingScreenProps) {
  const [current, setCurrent] = useState(conversation)
  const [retryError, setRetryError] = useState<ApiError | undefined>()
  const { state, stopping, stopError, stop } = useGeneration(current)
  const ready = state.status === 'ready' ? state.conversation : undefined

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

  const retryAction = (failure: ApiError) => (presentError(failure).action === 'refresh' ? () => void refresh() : onRetry)

  const panel = (
    <SidePanel title="Propuesta de HU" size="md">
      {state.status === 'ready' ? (
        <p className={styles.note}>La propuesta está lista. Ábrela para revisarla.</p>
      ) : (
        <>
          <p className={styles.note}>La propuesta aparece aquí cuando las citas están comprobadas.</p>
          {state.status === 'running' && <Skeleton lines={8} />}
        </>
      )}
    </SidePanel>
  )

  const loadingTitle = ready ? readyHeadline(ready) : stopping ? 'Deteniendo la generación…' : 'Generando la propuesta…'

  return (
    <Workspace
      title={conversationTitle(conversation.title)}
      phase={2}
      panel={panel}
      composer={
        <Composer
          placeholder="Espera a la propuesta para pedir cambios"
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
        <ChatEvent>Generar propuesta · {conversationTitle(conversation.title)}</ChatEvent>
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
                Ver la propuesta
              </Button>
            </div>
          )}
        </AssistantMessage>
      </ChatLog>
    </Workspace>
  )
}
