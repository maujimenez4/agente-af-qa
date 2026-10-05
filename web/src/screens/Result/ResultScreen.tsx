import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import { safeHref } from '../../security/safeHref.ts'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { ButtonLink, SoonButton } from '../../components/Button/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import type { UserStory } from '../../components/Proposal/index.ts'
import { ResultQ } from '../../components/QMark/index.ts'
import { Notice } from '../../components/States/index.ts'
import { Workspace } from '../../components/Workspace/index.ts'
import { proposalVersions } from '../Iterate/iterateText.ts'
import { receiptOperations } from '../Receipt/receiptText.ts'
import styles from './Result.module.css'
import { approvedLine, jiraIssueUrl, OUTCOME_TEXTS, outcomeOf } from './resultText.ts'

export interface ResultScreenProps {
  conversation: ConversationOut & { result: PublishOutcome }
}

// Qué falta para cada acción del lienzo que aún no hace nada (DESIGN-DECISIONS.md §4 bis).
const SOON = {
  audit: 'El registro de auditoría aún no está en el contrato de la API.',
  history: 'El historial es solo para administración y llega después del punto de control de la demo.',
  jira: 'La dirección de Jira no está disponible.',
  memory: 'La pestaña Memoria llega después del punto de control de la demo.',
  qa: 'Pasar la HU a QA llega en el paso siguiente del plan.',
}

// Mixta 4 · Resultado (UI.md §4.7): publicación simulada, real o en parte, tras aprobar en el recibo.
export function ResultScreen({ conversation }: ResultScreenProps) {
  const { result } = conversation
  const outcome = outcomeOf(result)
  const texts = OUTCOME_TEXTS[outcome]
  const last = proposalVersions(conversation).at(-1)
  const story = last?.story as UserStory | undefined
  const operations = receiptOperations(result.plan, last?.version ?? 1, story?.title ?? '', last?.impact)
  // Solo con todo publicado se marca cada operación con ✓: en parte, `errors` es texto y no dice cuál falló.
  const done = outcome === 'published'
  const listLabel = { simulated: 'Operaciones que se habrían hecho', published: 'Operaciones hechas en Jira', partial: 'Operaciones aprobadas' }[outcome]
  const key = result.plan.find((item) => item.op === 'update_story')?.key ?? result.published_keys[0]
  const jiraUrl = jiraIssueUrl(useJiraBrowseUrl(outcome !== 'simulated'), key)

  return (
    <Workspace title={conversationTitle(conversation.title)} phase={texts.phase} phaseName={texts.phaseName}>
      <section className={styles.result} aria-labelledby="result-title">
        <div className={styles.head}>
          <ResultQ outcome={outcome} />
          <Badge tone={outcome === 'simulated' ? 'warning' : outcome === 'partial' ? 'error' : 'new'}>{texts.badge}</Badge>
        </div>

        {outcome === 'simulated' && <Notice>Modo de prueba activo: el agente no escribe en Jira. Lo cambia el administrador.</Notice>}

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

        {result.published_keys.length > 0 && <p className={styles.muted}>Claves en Jira: {result.published_keys.join(', ')}</p>}

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
              <SoonButton label="Ver el registro de auditoría" note={SOON.audit} />
              <SoonButton label="Ir al historial" note={SOON.history} />
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
              <SoonButton label="Ver la memoria" note={SOON.memory} />
              <SoonButton label="Pedir sus pruebas a QA" variant="primary" note={SOON.qa} />
            </>
          )}
        </div>

        <p className={styles.approved}>{approvedLine(last?.version, result)}</p>
      </section>
    </Workspace>
  )
}

/** `SettingsOut.jira_browse_url` (PA-318). Solo se pide si hay algo que abrir en Jira; si falla, no hay enlace. */
function useJiraBrowseUrl(needed: boolean): string | null {
  const [browseUrl, setBrowseUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!needed) return
    let cancelled = false
    api
      .settings()
      .then((settings) => {
        if (!cancelled) setBrowseUrl(settings.jira_browse_url ?? null)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [needed])
  return browseUrl
}
