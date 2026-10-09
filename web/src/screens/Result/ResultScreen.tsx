import { safeHref } from '../../security/safeHref.ts'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { Button, ButtonLink, SoonButton } from '../../components/Button/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import { JiraKeyLink } from '../../components/Jira/index.ts'
import { useJiraBrowseUrl } from '../../hooks/useJiraBrowseUrl.ts'
import type { UserStory } from '../../components/Proposal/index.ts'
import { ResultQ } from '../../components/QMark/index.ts'
import { Notice } from '../../components/States/index.ts'
import { RESULT_SIMULATION_NOTICE } from '../../text/assistant.ts'
import { Workspace } from '../../components/Workspace/index.ts'
import { proposalVersions } from '../Iterate/iterateText.ts'
import { receiptOperations } from '../Receipt/receiptText.ts'
import { HandoffAction } from './HandoffAction.tsx'
import styles from './Result.module.css'
import { approvedLine, jiraIssueUrl, OUTCOME_TEXTS, outcomeOf, QA_OUTCOME_TEXTS } from './resultText.ts'
import { qaHeaderTitle } from '../Generating/headline.ts'

export interface ResultScreenProps {
  conversation: ConversationOut & { result: PublishOutcome }
  /** El analista puede pasar la HU a QA (T-54); QA y admin, no. Con el flujo unido desactivado, siempre `false`. */
  canHandoff?: boolean
  /** Flujo unido fuera de la entrega (`QA_HANDOFF_ENABLED`): *Pedir sus pruebas a QA* sale «disponible pronto». */
  handoffSoon?: boolean
  /** *Ver la memoria*: abre Memoria con la clave de la HU publicada (PA-329). Sin él, «disponible pronto». */
  onOpenMemory?: (key: string) => void
}

// Qué falta para cada acción del lienzo que aún no hace nada (DESIGN-DECISIONS.md §4 bis).
const SOON = {
  audit: 'El registro de auditoría aún no está en el contrato de la API.',
  history: 'El historial es solo para administración y llega después del punto de control de la demo.',
  jira: 'La dirección de Jira no está disponible.',
  memory: 'No hay una HU publicada con clave de la que abrir la memoria.',
  execution: 'Registrar la ejecución de las pruebas llega más adelante.',
  qa: 'No entra en esta entrega: QA prepara las pruebas escribiendo la clave de la HU.',
}

// Mixta 4 · Resultado (UI.md §4.7): publicación simulada, real o en parte, tras aprobar en el recibo.
export function ResultScreen({ conversation, canHandoff = false, handoffSoon = false, onOpenMemory }: ResultScreenProps) {
  const { result } = conversation
  const outcome = outcomeOf(result)
  // QA 5 (UI.md §6.5): el resultado de una suite (`publish_suite` en el plan).
  const qa = conversation.mode === 'qa' || result.plan.some((item) => item.op === 'publish_suite')
  const texts = (qa ? QA_OUTCOME_TEXTS : OUTCOME_TEXTS)[outcome]
  const last = proposalVersions(conversation).at(-1)
  const story = last?.story as UserStory | undefined
  const operations = receiptOperations(result.plan, last?.version ?? 1, story?.title ?? '', last?.impact)
  // Solo con todo publicado se marca cada operación con ✓: en parte, `errors` es texto y no dice cuál falló.
  const done = outcome === 'published'
  const listLabel = { simulated: 'Operaciones que se habrían hecho', published: 'Operaciones hechas en Jira', partial: 'Operaciones aprobadas' }[outcome]
  // La HU que se abre en Jira: la actualizada o, en una suite, la HU de sus subtareas.
  const key =
    result.plan.find((item) => item.op === 'update_story')?.key ||
    result.plan.find((item) => item.op === 'publish_suite')?.story ||
    result.published_keys[0]
  const browseUrl = useJiraBrowseUrl(outcome !== 'simulated')
  const jiraUrl = jiraIssueUrl(browseUrl, key)

  return (
    <Workspace
      title={qa ? qaHeaderTitle(conversationTitle(conversation.title)) : conversationTitle(conversation.title)}
      phase={texts.phase}
      phaseName={texts.phaseName}
    >
      <section className={styles.result} aria-labelledby="result-title">
        <div className={styles.head}>
          <ResultQ outcome={outcome} />
          <Badge tone={outcome === 'simulated' ? 'warning' : outcome === 'partial' ? 'error' : 'new'}>{texts.badge}</Badge>
        </div>

        {outcome === 'simulated' && <Notice>{RESULT_SIMULATION_NOTICE}</Notice>}

        <h2 id="result-title" className={styles.title}>
          {texts.title}
        </h2>
        <p className={styles.lead}>{texts.lead}</p>

        <ol className={styles.operations} aria-label={listLabel}>
          {operations.map((operation, index) => (
            <li key={operation.id} className={styles.operation}>
              <span className={styles.mark} data-done={done ? '' : undefined} aria-hidden="true">
                {done ? '✓' : index + 1}
              </span>
              <span className={styles.operationText}>
                <b>{operation.label}</b>
                {operation.detail && <span className={styles.muted}>{operation.detail}</span>}
              </span>
            </li>
          ))}
        </ol>

        {result.published_keys.length > 0 && (
          <p className={styles.muted}>
            Claves en Jira:{' '}
            {result.published_keys.map((publishedKey, index) => (
              <span key={publishedKey}>
                {index > 0 && ', '}
                <JiraKeyLink jiraKey={publishedKey} browseUrl={browseUrl} />
              </span>
            ))}
          </p>
        )}

        {outcome === 'partial' && (
          <div className={styles.failed} role="alert">
            <b>Lo que no se pudo publicar</b>
            <ul>
              {result.errors.map((message, index) => (
                <li key={`${index}-${message}`}>{message}</li>
              ))}
            </ul>
            {result.failed_ids.length > 0 && <span className={styles.muted}>Fallaron: {result.failed_ids.join(', ')}</span>}
          </div>
        )}

        <p className={styles.note}>{texts.note}</p>

        <div className={styles.actions}>
          {outcome === 'simulated' ? (
            <>
              {canHandoff && !qa && <HandoffAction conversationId={conversation.id} />}
              <SoonButton label="Ver el registro de auditoría" note={SOON.audit} />
              {/* UI.md §6.5: en QA, la simulación solo ofrece la auditoría. */}
              {!qa && <SoonButton label="Ir al historial" note={SOON.history} />}
            </>
          ) : (
            <>
              {jiraUrl && key ? (
                <ButtonLink href={safeHref(jiraUrl)} external>
                  Abrir {key} en Jira
                </ButtonLink>
              ) : (
                <SoonButton label={key ? `Abrir ${key} en Jira` : 'Abrir en Jira'} note={SOON.jira} />
              )}
              {/* UI.md §6.5: *Registrar la ejecución* solo con la suite publicada entera; en parte, lo que toca es
                  *Reintentar solo los fallidos* (PA-05), fuera de alcance. */}
              {qa ? (
                outcome === 'published' && <SoonButton label="Registrar la ejecución" variant="primary" note={SOON.execution} />
              ) : onOpenMemory && key ? (
                // La memoria se genera al publicar la HU; si aún no está, Memoria muestra su 404 (`not_found`).
                <Button onClick={() => onOpenMemory(key)}>Ver la memoria</Button>
              ) : (
                <SoonButton label="Ver la memoria" note={SOON.memory} />
              )}
              {canHandoff && !qa && <HandoffAction conversationId={conversation.id} />}
              {handoffSoon && !qa && <SoonButton label="Pedir sus pruebas a QA" variant="primary" note={SOON.qa} />}
            </>
          )}
        </div>

        <p className={styles.approved}>{approvedLine(last?.version, result, qa)}</p>
      </section>
    </Workspace>
  )
}
