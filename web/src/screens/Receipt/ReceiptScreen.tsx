import { useEffect, useState } from 'react'
import { flushSync } from 'react-dom'
import { api, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import type { UserStory } from '../../components/Proposal/index.ts'
import { ErrorCard, LoadingState, Notice, presentError } from '../../components/States/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import { useGeneration } from '../Generating/useGeneration.ts'
import { modelLabel, proposalVersions } from '../Iterate/iterateText.ts'
import styles from './Receipt.module.css'
import { aiNotice, receiptOperations, reviewedCounter } from './receiptText.ts'

export interface ReceiptScreenProps {
  conversation: ConversationOut
  /** «Volver a la propuesta»: Iterar con la conversación tal como está. */
  onBack: (conversation: ConversationOut) => void
  /** La aprobación terminó (simulada, publicada o con error) o la conversación cambió de estado. */
  onDone: (conversation: ConversationOut) => void
  onDiscarded: () => void
  /** `approval_rejected` o `restart`: hay que empezar una conversación nueva. */
  onRestart: () => void
}

const TIME = new Intl.DateTimeFormat('es-ES', { hour: '2-digit', minute: '2-digit' })

function timeOf(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : TIME.format(date)
}

// Seguir la publicación tras POST /approve: el final llega por el SSE (`result` o `review_ready`).
function Publishing({
  conversation,
  onSettled,
  onFailed,
}: {
  conversation: ConversationOut
  onSettled: (conversation: ConversationOut) => void
  /** `retryable`: la conversación quedó en `state=error` (p. ej. `publish_failed`). */
  onFailed: (error: ApiError, retryable: boolean) => void
}) {
  const { state } = useGeneration(conversation)
  useEffect(() => {
    if (state.status === 'ready') onSettled(state.conversation)
    if (state.status === 'error') onFailed(state.error, state.retryable)
    // Solo al cambiar de estado: el manejador cambia en cada render del padre.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.status])
  return <LoadingState title="Aprobando y publicando…" events={state.steps} reviewReady={false} />
}

// Recibo de aprobación (UI.md §4.6, contrato §5): una casilla por operación de `review.plan`.
// *Aprobar y publicar* se activa con todas marcadas y devuelve exactamente `review.fingerprint`.
export function ReceiptScreen({ conversation: initial, onBack, onDone, onDiscarded, onRestart }: ReceiptScreenProps) {
  const [conversation, setConversation] = useState(initial)
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set())
  const [publishing, setPublishing] = useState<ConversationOut | undefined>()
  const [error, setError] = useState<ApiError | undefined>()
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [busy, setBusy] = useState(false)
  // La publicación falló: *Aprobar* queda desactivado (un nuevo intento daría 409 not_in_review).
  const [failed, setFailed] = useState(false)

  const review = conversation.review
  const story = review?.artifact.content as UserStory | undefined
  const operations = review && story ? receiptOperations(review.plan, review.version, story.title, review.impact) : []
  const allChecked = operations.length > 0 && operations.every((operation) => checked.has(operation.id))
  const title = conversationTitle(conversation.title)

  const toggle = (id: string) =>
    setChecked((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  // Una revisión nueva (p. ej. tras una huella rechazada) se vuelve a revisar entera.
  const showReview = (next: ConversationOut) => {
    setConversation(next)
    setChecked(new Set())
  }

  const settle = (outcome: ConversationOut) => {
    setPublishing(undefined)
    if (outcome.state === 'in_review') showReview(outcome)
    else onDone(outcome)
  }

  // Falló la publicación ya en marcha: la revisión no sigue abierta, así que no se vuelve a aprobar desde
  // aquí. Con la conversación en error se abre su vista, que reintenta con POST /retry (nunca dos escrituras).
  const publishFailed = (failure: ApiError, retryable: boolean) => {
    setPublishing(undefined)
    setFailed(true)
    if (retryable) void refresh()
    else setError(failure)
  }

  const approve = async () => {
    if (!review || !allChecked || busy) return
    // `busy` se pinta en el acto: un segundo clic ya encuentra el botón desactivado (un solo POST /approve).
    flushSync(() => {
      setError(undefined)
      setBusy(true)
    })
    try {
      // La huella tal cual la dio el último payload: nunca se guarda ni se reconstruye (UI.md §5.4).
      const next = await api.approve(conversation.id, review.fingerprint)
      if (next.state === 'generating') setPublishing(next)
      else settle(next)
    } catch (cause) {
      setError(toApiError(cause))
    } finally {
      setBusy(false)
    }
  }

  const refresh = async () => {
    setError(undefined)
    try {
      const next = await api.conversation(conversation.id)
      if (next.state === 'in_review') {
        setFailed(false)
        showReview(next)
      } else onDone(next)
    } catch (cause) {
      setError(toApiError(cause))
    }
  }

  const discard = async () => {
    setBusy(true)
    try {
      await api.discard(conversation.id)
      onDiscarded()
    } catch (cause) {
      setError(toApiError(cause))
    } finally {
      setBusy(false)
      setConfirmDiscard(false)
    }
  }

  const errorAction = (failure: ApiError): (() => void) | undefined => {
    switch (presentError(failure).action) {
      case 'restart':
        return onRestart
      case 'refresh':
      case 'backToReceipt':
        return () => void refresh()
      case 'retry':
        // Solo si falló la propia petición POST /approve; tras un fallo de la publicación, se lee el estado.
        return failed ? () => void refresh() : () => void approve()
      default:
        return undefined
    }
  }

  const versions = proposalVersions(conversation)
  // La hora de cada versión está en `VersionOut`; la que está en revisión puede no estar aún en la lista.
  const createdAt = new Map(conversation.versions.map((item) => [item.version, item.created_at]))
  const history = (
    <SidePanel title="Historial de la HU" subtitle={`${title} · en revisión`}>
      <ol className={styles.history} aria-label="Versiones de la propuesta">
        {[...versions].reverse().map((item) => (
          <li key={item.version} className={styles.historyItem}>
            <b>Versión {item.version} generada</b>
            <span className={styles.muted}>
              {[modelLabel(item.artifact.model_used), item.artifact.prompt_version ? `prompt v${item.artifact.prompt_version}` : undefined, timeOf(createdAt.get(item.version) ?? '')]
                .filter(Boolean)
                .join(', ')}
            </span>
          </li>
        ))}
        {conversation.jira_baseline && (
          <li className={styles.historyItem}>
            <b>Versión de partida desde Jira</b>
            <span className={styles.muted}>La HU tal como está en Jira</span>
          </li>
        )}
      </ol>
    </SidePanel>
  )

  return (
    <Workspace title={title} phase={3} panel={history}>
      <section className={styles.receipt} aria-labelledby="receipt-title">
        <h2 id="receipt-title" className={styles.heading}>
          Versión {review?.version ?? '—'} lista para revisar
        </h2>

        {review?.error && (
          // Respuesta rechazada (UI.md §5.3): la revisión sigue y el motivo se muestra tal cual.
          <div className={styles.rejected} role="alert">
            <b>No se aprobó</b>
            <span>{review.error}</span>
          </div>
        )}

        {operations.length === 0 ? (
          <Notice>Esta propuesta no tiene operaciones de Jira que aprobar.</Notice>
        ) : (
          <fieldset className={styles.operations} disabled={Boolean(publishing)}>
            <legend className={styles.legend}>
              Qué se hará en Jira
              <span className={styles.counter} aria-live="polite">
                {reviewedCounter(operations.filter((operation) => checked.has(operation.id)).length, operations.length)}
              </span>
            </legend>
            {operations.map((operation) => (
              <label key={operation.id} className={styles.operation} data-checked={checked.has(operation.id) ? '' : undefined}>
                <input type="checkbox" checked={checked.has(operation.id)} onChange={() => toggle(operation.id)} />
                <span className={styles.operationText}>
                  <b>{operation.label}</b>
                  {operation.detail && <span className={styles.muted}>{operation.detail}</span>}
                </span>
              </label>
            ))}
          </fieldset>
        )}

        <p className={styles.notice}>{aiNotice(story?.sources.length ?? 0)}</p>

        {publishing && <Publishing key={publishing.id} conversation={publishing} onSettled={settle} onFailed={publishFailed} />}
        {error && <ErrorCard key={`${error.code}-${error.message}`} error={error} onAction={errorAction(error)} />}

        {confirmDiscard ? (
          <div className={styles.confirm} role="group" aria-label="Confirmar el descarte">
            <span>¿Descartar la propuesta? No se publicará nada en Jira y la conversación terminará.</span>
            <span className={styles.actions}>
              <Button variant="danger" size="md" disabled={busy} onClick={() => void discard()}>
                Sí, descartar
              </Button>
              <Button size="md" onClick={() => setConfirmDiscard(false)}>
                Seguir revisando
              </Button>
            </span>
          </div>
        ) : (
          <div className={styles.actions}>
            <Button variant="ghost" disabled={busy || Boolean(publishing)} onClick={() => setConfirmDiscard(true)}>
              Descartar
            </Button>
            <Button disabled={busy || Boolean(publishing)} onClick={() => onBack(conversation)}>
              Volver a la propuesta
            </Button>
            <span className={styles.spacer} />
            <Button variant="primary" disabled={!allChecked || busy || failed || Boolean(publishing)} onClick={() => void approve()}>
              Aprobar y publicar
            </Button>
          </div>
        )}

        <p className={styles.footnote}>Al publicar quedará registrado quién aprobó, cuándo y qué claves se crearon.</p>
      </section>
    </Workspace>
  )
}
