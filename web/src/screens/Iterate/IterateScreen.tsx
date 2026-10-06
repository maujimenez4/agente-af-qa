import { useEffect, useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut, TestSuite } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { Button, SoonButton } from '../../components/Button/index.ts'
import { AssistantMessage, ChatLog, UserMessage } from '../../components/Chat/index.ts'
import { Chip } from '../../components/Chip/index.ts'
import { Composer, ModelTag } from '../../components/Composer/index.ts'
import {
  ChangesView,
  changesLabel,
  ImpactView,
  JIRA_VERSION,
  SourcesView,
  StoryView,
  Tabs,
  VersionSelector,
  versionSummary,
} from '../../components/Proposal/index.ts'
import { TypewriterText, TypingIndicator } from '../../components/QMark/index.ts'
import {
  casesLabel,
  CasesView,
  coverageBadge,
  coverageNote,
  CoverageView,
  DataRisksView,
  StrategyView,
  suiteCoverage,
  suiteSummary,
  UNKNOWN_COVERAGE,
  type SuiteCoverage,
} from '../../components/Suite/index.ts'
import { ErrorCard, presentError } from '../../components/States/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import { useSession } from '../../session/sessionContext.ts'
import { qaHeaderTitle } from '../Generating/headline.ts'
import { requestStop, useGeneration } from '../Generating/useGeneration.ts'
import styles from './Iterate.module.css'
import { modelLabel, proposalVersions, QA_SUGGESTIONS, SUGGESTIONS } from './iterateText.ts'

export interface IterateScreenProps {
  conversation: ConversationOut
  /** La propuesta se descartó (POST /discard): vuelve a Inicio. */
  onDiscarded: () => void
  /** La conversación no puede continuar (error o «empezar de nuevo»): vuelve a Inicio. */
  onRestart: () => void
  /** *Revisar y aprobar*: abre el recibo con la revisión actual (UI.md §4.6). */
  onReview: (conversation: ConversationOut) => void
}

type PanelTab = 'proposal' | 'changes' | 'impact' | 'sources' | 'cases' | 'coverage' | 'data' | 'strategy'

type Entry = { kind: 'user'; text: string } | { kind: 'assistant'; version: number; animate: boolean }

// Seguir una iteración en curso: cuando llega review_ready, la propuesta nueva sustituye a la anterior.
function Iterating({
  conversation,
  stopping,
  onReady,
  onError,
}: {
  conversation: ConversationOut
  /** Se pidió detener: «Deteniendo…» hasta que termine el paso en curso. */
  stopping: boolean
  onReady: (conversation: ConversationOut) => void
  /** `retryable`: quedó en `state=error` y se repite con POST /retry. */
  onError: (error: ApiError, retryable: boolean) => void
}) {
  const { state } = useGeneration(conversation)
  useEffect(() => {
    if (state.status === 'ready') onReady(state.conversation)
    if (state.status === 'error') onError(state.error, state.retryable)
    // Solo al cambiar de estado: los manejadores cambian en cada render del padre.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.status])
  return <TypingIndicator label={stopping ? 'Deteniendo la generación…' : undefined} />
}

/** La suite de una versión de QA, si el contenido lo es (trae `cases`); si no, `undefined` y se pinta como HU. */
function suiteOf(content: unknown): TestSuite | undefined {
  return typeof content === 'object' && content !== null && Array.isArray((content as Partial<TestSuite>).cases) ? (content as TestSuite) : undefined
}

// Mixta 3 · Iterar (UI.md §4.5): conversación para pedir cambios y panel de la propuesta con sus versiones.
// En QA es QA 3 · Iterar la suite (§6.3): la misma conversación y un panel con Casos, Cobertura, Datos y riesgos y Estrategia.
export function IterateScreen({ conversation: initial, onDiscarded, onRestart, onReview }: IterateScreenProps) {
  const [conversation, setConversation] = useState(initial)
  // Cambios pedidos antes de abrir la pantalla (retomar, T-52): se pintan siempre, antes de lo nuevo.
  const [earlierFeedback] = useState(initial.feedback)
  const [panelOpen, setPanelOpen] = useState(true)
  const { logout } = useSession()
  // La operación que falló, para *Reintentar* o *Volver a generar*: repite esa y no otra.
  const [retry, setRetry] = useState<{ run: () => void } | undefined>()

  const fail = (failure: ApiError, again: () => void) => {
    setError(failure)
    setRetry({ run: again })
  }
  // Solo al evolucionar hay una HU de Jira con la que comparar (DESIGN-DECISIONS.md §4 bis).
  const againstJira = conversation.flow === 'evolve'
  const qa = conversation.mode === 'qa'
  const versions = proposalVersions(conversation)
  const latest = versions.at(-1)
  const [selected, setSelected] = useState(latest?.version ?? 1)
  const [tab, setTab] = useState<PanelTab>(initial.mode === 'qa' ? 'cases' : 'proposal')
  const firstTab: PanelTab = qa ? 'cases' : 'proposal'
  const [entries, setEntries] = useState<Entry[]>(() => [{ kind: 'assistant', version: latest?.version ?? 1, animate: false }])
  const [draft, setDraft] = useState('')
  const [iterating, setIterating] = useState<ConversationOut | undefined>()
  const [error, setError] = useState<ApiError | undefined>()
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [busy, setBusy] = useState(false)
  const [stopping, setStopping] = useState(false)

  // Versión «Jira» (PA-316): la HU tal como está en Jira, solo al evolucionar; la v1 se compara con ella.
  const baseline = conversation.jira_baseline ?? undefined
  const showingJira = selected === JIRA_VERSION && baseline !== undefined
  const shown = versions.find((item) => item.version === selected) ?? latest
  const previousStory = shown ? (versions[versions.indexOf(shown) - 1]?.story ?? baseline) : undefined
  const diffs = shown?.impact?.diffs ?? []

  const send = async (feedback: string, { repeat = false } = {}) => {
    const text = feedback.trim()
    if (!text) return
    setError(undefined)
    setDraft('')
    if (!repeat) setEntries((current) => [...current, { kind: 'user', text }])
    try {
      setIterating(await api.iterate(conversation.id, text))
    } catch (cause) {
      fail(toApiError(cause), () => void send(text, { repeat: true }))
    }
  }

  // Detener la iteración en curso (PA-314): termina como `cancelled`, que se reintenta con /retry.
  const stop = async () => {
    if (!iterating) return
    setStopping(true)
    const { stopping: still, error: failure } = await requestStop(iterating.id)
    setStopping(still)
    if (failure) fail(failure, () => void stop())
  }

  // Repite el paso que falló (POST /retry, PA-276): la iteración vuelve a generar con el mismo cambio.
  const retryIteration = async () => {
    setError(undefined)
    try {
      setIterating(await api.retry(conversation.id))
    } catch (cause) {
      fail(toApiError(cause), () => void retryIteration())
    }
  }

  // «Actualizar» (not_in_review, operation_failed…): vuelve a leer el estado de la conversación.
  const refresh = async () => {
    setError(undefined)
    try {
      const next = await api.conversation(conversation.id)
      if (next.state !== 'in_review') {
        onRestart()
        return
      }
      setConversation(next)
      setSelected(proposalVersions(next).at(-1)?.version ?? selected)
    } catch (cause) {
      fail(toApiError(cause), () => void refresh())
    }
  }

  // Acción de la tarjeta de error según su código (DESIGN-DECISIONS.md §6).
  const errorAction = (failure: ApiError): (() => void) => {
    switch (presentError(failure).action) {
      case 'restart':
        return onRestart
      case 'refresh':
        return () => void refresh()
      case 'login':
        return () => void logout()
      case 'regenerate':
      case 'retry':
        return retry ? retry.run : () => setError(undefined)
      default:
        return () => setError(undefined)
    }
  }

  const discard = async () => {
    setBusy(true)
    try {
      await api.discard(conversation.id)
      onDiscarded()
    } catch (cause) {
      fail(toApiError(cause), () => void discard())
    } finally {
      setBusy(false)
      setConfirmDiscard(false)
    }
  }

  const suite = qa && shown ? suiteOf(shown.artifact.content) : undefined
  const previousSuite = qa && shown ? versions[versions.indexOf(shown) - 1] : undefined
  // PA-326: `uncovered` y `coverage_md` son de la versión en revisión; las anteriores no los traen («no se sabe»).
  const coverageOf = (version: number): SuiteCoverage =>
    conversation.review && version === conversation.review.version ? suiteCoverage(conversation.review.uncovered) : UNKNOWN_COVERAGE
  const shownCoverage = shown ? coverageOf(shown.version) : UNKNOWN_COVERAGE
  const shownCoverageMd = conversation.review && shown?.version === conversation.review.version ? conversation.review.coverage_md : null
  const badge = coverageBadge(shownCoverage)
  const tabs: { id: PanelTab; label: string }[] = suite
    ? [
        { id: 'cases', label: `Casos (${suite.cases.length})` },
        { id: 'coverage', label: 'Cobertura' },
        { id: 'data', label: 'Datos y riesgos' },
        { id: 'strategy', label: 'Estrategia' },
      ]
    : [
        { id: 'proposal', label: 'Propuesta' },
        { id: 'changes', label: againstJira ? `Cambios (${diffs.length})` : 'Cambios' },
        { id: 'impact', label: `Impacto (${shown?.impact?.affected.length ?? 0})` },
        { id: 'sources', label: `Fuentes (${shown?.story.sources.length ?? 0})` },
      ]

  const panel = shown && (
    <SidePanel
      title={qa ? 'Suite de pruebas' : 'Propuesta de HU'}
      subtitle={`${conversationTitle(conversation.title)} · ${iterating ? 'generando' : 'en revisión'}`}
      size={qa ? 'lg' : 'md'}
      headerActions={
        <VersionSelector versions={versions.map((item) => item.version)} selected={showingJira ? JIRA_VERSION : shown.version} jira={baseline !== undefined} onSelect={setSelected} />
      }
      footer={
        confirmDiscard ? (
          <div className={styles.confirm} role="group" aria-label="Confirmar el descarte">
            <span>¿Descartar {qa ? 'la suite' : 'la propuesta'}? No se publicará nada en Jira y la conversación terminará.</span>
            <span className={styles.confirmActions}>
              <Button variant="danger" size="md" disabled={busy} onClick={() => void discard()}>
                Sí, descartar
              </Button>
              <Button size="md" onClick={() => setConfirmDiscard(false)}>
                Seguir revisando
              </Button>
            </span>
          </div>
        ) : (
          <div className={styles.footer}>
            <SoonButton label="Editar a mano" />
            <Button variant="ghost" disabled={Boolean(iterating)} onClick={() => setConfirmDiscard(true)}>
              Descartar
            </Button>
            <span className={styles.spacer} />
            <Button variant="primary" disabled={Boolean(iterating) || !conversation.review} onClick={() => onReview(conversation)}>
              Revisar y aprobar
            </Button>
          </div>
        )
      }
    >
      {showingJira ? (
        <div className={styles.jira}>
          <p className={styles.jiraNote}>Así está la HU en Jira ahora. Elige una versión para ver qué cambia.</p>
          <StoryView key="jira" story={baseline} version={JIRA_VERSION} previous={baseline} diffs={[]} />
        </div>
      ) : (
        <Tabs label="Contenido del panel" tabs={tabs} selected={tab} onSelect={setTab}>
          {suite && badge && (
            <p className={styles.covered}>
              <Badge tone={badge.tone} icon={badge.tone === 'success' ? 'done' : 'warning'}>
                {badge.text}
              </Badge>
            </p>
          )}
          {suite && tab === 'cases' && (
            <CasesView key={shown.version} suite={suite} version={shown.version} previous={previousSuite && suiteOf(previousSuite.artifact.content)} />
          )}
          {suite && tab === 'coverage' && <CoverageView suite={suite} coverage={shownCoverage} coverageMd={shownCoverageMd} />}
          {suite && tab === 'data' && <DataRisksView suite={suite} />}
          {suite && tab === 'strategy' && <StrategyView suite={suite} />}
          {!suite && tab === 'proposal' && <StoryView key={shown.version} story={shown.story} version={shown.version} previous={previousStory} diffs={diffs} />}
          {!suite && tab === 'changes' && <ChangesView diffs={diffs} againstJira={againstJira} />}
          {!suite && tab === 'impact' && <ImpactView impact={shown.impact} />}
          {!suite && tab === 'sources' && <SourcesView sources={shown.story.sources} />}
        </Tabs>
      )}
    </SidePanel>
  )

  const lastAssistant = entries.map((entry) => entry.kind).lastIndexOf('assistant')

  return (
    <Workspace
      title={qa ? qaHeaderTitle(conversationTitle(conversation.title)) : conversationTitle(conversation.title)}
      phase={2}
      panel={panel}
      panelOpen={panelOpen}
      onPanelOpenChange={setPanelOpen}
      composer={
        <Composer
          placeholder={
            qa
              ? iterating
                ? 'Espera a la suite para pedir cambios'
                : 'Pide un cambio a la suite'
              : iterating
                ? 'Espera a la propuesta para pedir cambios'
                : 'Pide un cambio a la propuesta'
          }
          value={draft}
          onChange={setDraft}
          canSubmit={draft.trim().length > 0}
          disabled={Boolean(iterating)}
          submitLabel="Enviar"
          onStop={iterating ? () => void stop() : undefined}
          stopping={stopping}
          onSubmit={() => void send(draft)}
          tools={<ModelTag label="Modelo automático" />}
        />
      }
    >
      <ChatLog>
        {earlierFeedback.map((item, index) => (
          <UserMessage key={`previo-${index}`}>{item}</UserMessage>
        ))}
        {entries.map((entry, index) => {
          if (entry.kind === 'user') return <UserMessage key={`u-${index}`}>{entry.text}</UserMessage>
          const item = versions.find((candidate) => candidate.version === entry.version)
          if (!item) return null
          const itemSuite = qa ? suiteOf(item.artifact.content) : undefined
          const before = versions[versions.indexOf(item) - 1]
          const summary = itemSuite
            ? suiteSummary(itemSuite, item.version, before && suiteOf(before.artifact.content), coverageOf(item.version))
            : versionSummary(item.story, item.version, item.impact)
          const model = modelLabel(item.artifact.model_used)
          const sourceCount = itemSuite ? itemSuite.sources.length : item.story.sources.length
          // «cobertura validada» solo con `uncovered` vacío; con huecos, cuántos (PA-326).
          const coverage = itemSuite ? coverageNote(coverageOf(item.version)) : undefined
          return (
            <AssistantMessage key={`a-${entry.version}`} animate={entry.animate}>
              <span>{entry.animate ? <TypewriterText text={summary} /> : summary}</span>
              <button
                type="button"
                className={styles.artifact}
                aria-pressed={panelOpen && selected === item.version}
                onClick={() => {
                  setSelected(item.version)
                  setTab(firstTab)
                  setPanelOpen(true)
                }}
              >
                <span className={styles.artifactTitle}>
                  {itemSuite ? 'Suite de pruebas' : 'Propuesta de HU'}, versión {item.version}
                </span>
                <span className={styles.meta}>
                  {panelOpen && selected === item.version ? 'Abierta en el panel' : 'Abrir en el panel'}
                  {itemSuite && ` · ${casesLabel(itemSuite.cases.length)}`}
                  {againstJira && ` · ${changesLabel(item.impact?.diffs.length ?? 0)}`}
                </span>
              </button>
              {model && (
                <span className={styles.meta}>
                  Generado con {model} · {sourceCount} fuentes{coverage && ` · ${coverage}`}
                </span>
              )}
              {index === lastAssistant && !iterating && (
                <ul className={styles.suggestions} aria-label="Cambios sugeridos">
                  {(qa ? QA_SUGGESTIONS : SUGGESTIONS).map((suggestion) => (
                    <li key={suggestion}>
                      <Chip onClick={() => setDraft(suggestion)}>{suggestion}</Chip>
                    </li>
                  ))}
                </ul>
              )}
            </AssistantMessage>
          )
        })}

        {iterating && (
          <AssistantMessage>
            <Iterating
              key={iterating.id + iterating.feedback.length}
              conversation={iterating}
              stopping={stopping}
              onReady={(next) => {
                setStopping(false)
                // Un error anterior (p. ej. al pedir detener) ya no aplica a la versión nueva.
                setError(undefined)
                setRetry(undefined)
                const version = proposalVersions(next).at(-1)?.version ?? selected
                setConversation(next)
                setIterating(undefined)
                setSelected(version)
                setTab(firstTab)
                setEntries((current) => [...current, { kind: 'assistant', version, animate: true }])
              }}
              onError={(failure, retryable) => {
                setIterating(undefined)
                setStopping(false)
                // En error (también `cancelled`) se repite con /retry; si no, se vuelve a leer el estado.
                fail(failure, retryable ? () => void retryIteration() : () => void refresh())
              }}
            />
          </AssistantMessage>
        )}

        {error && (
          <AssistantMessage>
            <ErrorCard
              key={`${error.code}-${error.message}`}
              error={error}
              onAction={errorAction(error)}
            />
          </AssistantMessage>
        )}
      </ChatLog>
    </Workspace>
  )
}
