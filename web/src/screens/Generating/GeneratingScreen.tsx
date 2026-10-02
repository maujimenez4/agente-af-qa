import type { ConversationOut } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, ChatEvent, ChatLog } from '../../components/Chat/index.ts'
import { Composer } from '../../components/Composer/index.ts'
import { ErrorCard, LoadingState, Skeleton } from '../../components/States/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import styles from './Generating.module.css'
import { readyHeadline } from './headline.ts'
import { useGeneration } from './useGeneration.ts'

export interface GeneratingScreenProps {
  conversation: ConversationOut
  /** La propuesta está lista (review_ready): abre Iterar. */
  onReady: (conversation: ConversationOut) => void
  /** «Volver a generar» tras un error: vuelve a Origen y fuentes con la misma operación. */
  onRetry: () => void
}

// Mixta 2b · Generando (UI.md §4.4): la Q de carga avanza con los eventos del SSE.
export function GeneratingScreen({ conversation, onReady, onRetry }: GeneratingScreenProps) {
  const state = useGeneration(conversation)
  const ready = state.status === 'ready' ? state.conversation : undefined

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

  return (
    <Workspace
      title={conversation.title}
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
        />
      }
    >
      <ChatLog>
        <ChatEvent>Generar propuesta · {conversation.title}</ChatEvent>
        <AssistantMessage>
          {state.status === 'error' ? (
            <ErrorCard key={`${state.error.code}-${state.error.message}`} error={state.error} onAction={onRetry} />
          ) : (
            <LoadingState
              title={ready ? readyHeadline(ready) : 'Generando la propuesta…'}
              events={state.steps}
              reviewReady={state.status === 'ready'}
            />
          )}
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
