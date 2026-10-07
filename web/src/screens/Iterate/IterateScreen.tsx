import { useEffect, useId, useRef, useState } from 'react'
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
import { ErrorCard, Notice, presentError } from '../../components/States/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import { useSession } from '../../session/sessionContext.ts'
import { EditPanel, type EditCloseGuard } from '../Edit/EditPanel.tsx'
import { editedSummary, editedVersions, editNoteMessage } from '../Edit/editText.ts'
import type { UserStory } from '../Edit/storyDraft.ts'
import { qaHeaderTitle } from '../Generating/headline.ts'
import { requestStop, useGeneration } from '../Generating/useGeneration.ts'
import styles from './Iterate.module.css'
import { addCasesSuggestion, ITERATING_LABEL, MISSING_CASES_ITERATE_REASON, modelLabel, proposalVersions, QA_EDIT_SOON, QA_SUGGESTIONS, SUGGESTIONS } from './iterateText.ts'
import { SOON_BADGE } from '../Admin/adminText.ts'
import { missingCasesLabel } from '../Receipt/receiptText.ts'
import { countLabel } from '../../text/plural.ts'

export interface IterateScreenProps {
  conversation: ConversationOut
  /** La propuesta se descartó (POST /discard): vuelve a Inicio. */
  onDiscarded: () => void
  /** La conversación no puede continuar (error o «empezar de nuevo»): vuelve a Inicio. */
  onRestart: () => void
  /** *Revisar y aprobar*: abre el recibo con la revisión actual (UI.md §4.6). */
  onReview: (conversation: ConversationOut) => void
  /** Se guardó una versión editada a mano: la lista de conversaciones se vuelve a leer («Versión N+1»). */
  onEdited?: () => void
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
  // PA-430: al iterar se genera una versión nueva; el texto por defecto («Escribiendo…») es de otros usos.
  return <TypingIndicator label={stopping ? 'Deteniendo la generación…' : ITERATING_LABEL} />
}

/** La suite de una versión de QA, si el contenido lo es (trae `cases`); si no, `undefined` y se pinta como HU. */
function suiteOf(content: unknown): TestSuite | undefined {
  return typeof content === 'object' && content !== null && Array.isArray((content as Partial<TestSuite>).cases) ? (content as TestSuite) : undefined
}

// Mixta 3 · Iterar (UI.md §4.5): conversación para pedir cambios y panel de la propuesta con sus versiones.
// En QA es QA 3 · Iterar la suite (§6.3): la misma conversación y un panel con Casos, Cobertura, Datos y riesgos y Estrategia.
export function IterateScreen({ conversation: initial, onDiscarded, onRestart, onReview, onEdited }: IterateScreenProps) {
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
  // Editar a mano (RF-32, parte B): el editor sustituye al panel de la propuesta mientras se edita la versión en revisión.
  const [editing, setEditing] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const closeGuardRef = useRef<EditCloseGuard | null>(null)
  const saveRef = useRef<(() => boolean) | null>(null)
  const edited = editedVersions(conversation.versions)
  // Solo la HU: editar la suite de QA queda para un bloque aparte (PA-340).
  const canEdit = !qa && !iterating && Boolean(conversation.review)

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

  // Con el editor abierto, lo que lo cierra o lo cambia pasa antes por «¿Descartar los cambios?» (PA-344). Sin cambios
  // sin guardar sigue en el acto; `exit` sale además del editor (abrir otra versión), si no se queda abierto.
  const guarded = (then: () => void, { exit }: { exit: boolean }) => {
    // El editor deja `closeGuardRef` a null al cerrarse: así no depende del `editing` de un render anterior (*Reintentar*).
    const guard = closeGuardRef.current
    if (!guard) return then()
    if (!guard(then)) {
      setPanelOpen(true) // la pregunta va en el pie del editor: que se vea aunque el panel estuviera plegado
      return
    }
    if (exit) {
      setEditing(false)
      setEditError(null)
    }
    then()
  }

  // «Actualizar» (not_in_review, operation_failed…): vuelve a leer el estado de la conversación. El editor sigue abierto
  // si la versión en revisión no cambió; con una más nueva se abre sobre ella (`key` del panel).
  const refresh = () => guarded(() => void reload(), { exit: false })
  const reload = async () => {
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
      fail(toApiError(cause), refresh)
    }
  }

  // Acción de la tarjeta de error según su código (DESIGN-DECISIONS.md §6).
  const errorAction = (failure: ApiError): (() => void) => {
    switch (presentError(failure).action) {
      case 'restart':
        return onRestart
      case 'refresh':
        return refresh
      case 'login':
        return () => void logout()
      case 'regenerate':
      case 'retry':
        return retry ? retry.run : () => setError(undefined)
      default:
        return () => setError(undefined)
    }
  }

  const startEditing = () => {
    setEditError(null)
    setEditing(true)
    setPanelOpen(true)
  }

  // Guardar la versión N+1 con la huella de la que se muestra. Un rechazo de la API llega en `review.error` (misma
  // versión): se queda en el editor con el motivo tal cual. Un error HTTP (409, 503…) sale en la conversación.
  const saveEdit = async (content: UserStory, note: string | null) => {
    const review = conversation.review
    if (!review) return
    setSaving(true)
    setEditError(null)
    setError(undefined)
    try {
      const next = await api.edit(conversation.id, review.fingerprint, content, note)
      setConversation(next)
      if (next.review?.error) {
        setEditError(next.review.error)
        return
      }
      const version = next.review?.version ?? proposalVersions(next).at(-1)?.version ?? selected
      onEdited?.()
      setEditing(false)
      setSelected(version)
      setTab(firstTab)
      setEntries((current) => [...current, ...(note?.trim() ? [{ kind: 'user' as const, text: editNoteMessage(note) }] : []), { kind: 'assistant', version, animate: true }])
    } catch (cause) {
      // *Reintentar* guarda lo que haya entonces en el editor, no esta copia (PA-344); fuera del editor, solo se cierra.
      fail(toApiError(cause), () => {
        if (!saveRef.current?.()) setError(undefined)
      })
    } finally {
      setSaving(false)
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
  // Un CA sin caso bloquea la aprobación en el recibo; aquí se avisa (de la versión en revisión) y se sugiere pedirlo.
  // *Revisar y aprobar* sigue activo: el recibo explica el bloqueo (decisión del responsable, 2026-10-07).
  const reviewCoverage = conversation.review ? coverageOf(conversation.review.version) : UNKNOWN_COVERAGE
  const missingCriteria = reviewCoverage.kind === 'gaps' ? reviewCoverage.criteria : []
  // Del CA sin caso de la versión en revisión, que es la que se aprueba, aunque se esté mirando otra (security-reviewer).
  const shownMissing = missingCasesLabel(missingCriteria)
  const missingId = useId()
  const qaSuggestions = [addCasesSuggestion(missingCriteria), ...QA_SUGGESTIONS].filter((item): item is string => Boolean(item))
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

  const panel = editing && conversation.review ? (
    <EditPanel
      key={conversation.review.version}
      title={conversationTitle(conversation.title)}
      story={conversation.review.artifact.content as UserStory}
      version={conversation.review.version}
      reviewError={editError}
      busy={saving}
      onSave={(content, note) => void saveEdit(content, note)}
      onCancel={() => {
        setEditing(false)
        setEditError(null)
      }}
      closeGuardRef={closeGuardRef}
      saveRef={saveRef}
      onClosePanel={() => setPanelOpen(false)}
    />
  ) : shown && (
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
            {qa && (
              // PA-346: el motivo se ve (no solo lo oyen los lectores de pantalla), con el distintivo de Ajustes (PA-431).
              <p className={styles.soonNote}>
                <Badge tone="neutral">{SOON_BADGE}</Badge> {QA_EDIT_SOON}
              </p>
            )}
            {qa ? (
              <SoonButton label="Editar a mano" note={`${SOON_BADGE}: ${QA_EDIT_SOON}`} />
            ) : (
              <Button variant="secondary" disabled={!canEdit} onClick={startEditing}>
                Editar a mano
              </Button>
            )}
            <Button variant="ghost" disabled={Boolean(iterating)} onClick={() => setConfirmDiscard(true)}>
              Descartar
            </Button>
            <span className={styles.spacer} />
            <Button
              variant="primary"
              disabled={Boolean(iterating) || !conversation.review}
              aria-describedby={suite && shownMissing ? missingId : undefined}
              onClick={() => onReview(conversation)}
            >
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
          {suite && shownMissing && (
            <div id={missingId} className={styles.missing}>
              <Notice>
                <b>{shownMissing}.</b> {MISSING_CASES_ITERATE_REASON}
              </Notice>
            </div>
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
      onPanelCloseRequest={() => closeGuardRef.current?.() ?? true}
      composer={
        <Composer
          placeholder={
            editing
              ? 'Guarda o cancela la edición para pedir cambios'
              : qa
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
          disabled={Boolean(iterating) || editing}
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
            : edited.has(item.version)
              ? editedSummary(item.story, item.version, item.impact)
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
                aria-pressed={!editing && panelOpen && selected === item.version}
                onClick={() =>
                  // Mientras se edita, abrir una versión sale del editor (PA-344): con cambios, tras confirmarlo.
                  guarded(
                    () => {
                      setSelected(item.version)
                      setTab(firstTab)
                      setPanelOpen(true)
                    },
                    { exit: true },
                  )
                }
              >
                <span className={styles.artifactTitle}>
                  {itemSuite ? 'Suite de pruebas' : 'Propuesta de HU'}, versión {item.version}
                </span>
                <span className={styles.meta}>
                  {!editing && panelOpen && selected === item.version ? 'Abierta en el panel' : 'Abrir en el panel'}
                  {itemSuite && ` · ${casesLabel(itemSuite.cases.length)}`}
                  {againstJira && ` · ${changesLabel(item.impact?.diffs.length ?? 0)}`}
                </span>
              </button>
              {edited.has(item.version) ? (
                <span className={styles.meta}>Editada a mano · {countLabel(sourceCount, 'fuente', 'fuentes')}</span>
              ) : model && (
                <span className={styles.meta}>
                  Generado con {model} · {countLabel(sourceCount, 'fuente', 'fuentes')}{coverage && ` · ${coverage}`}
                </span>
              )}
              {index === lastAssistant && !iterating && !editing && (
                <ul className={styles.suggestions} aria-label="Cambios sugeridos">
                  {(qa ? qaSuggestions : SUGGESTIONS).map((suggestion) => (
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
                fail(failure, retryable ? () => void retryIteration() : refresh)
              }}
            />
          </AssistantMessage>
        )}

        {error && (
          <AssistantMessage>
            <ErrorCard
              key={`${error.code}-${error.message}`}
              error={error}
              // Se elige al pulsar: *Actualizar* puede leer la pregunta del editor (`closeGuardRef`, PA-344).
              onAction={() => errorAction(error)()}
            />
          </AssistantMessage>
        )}
      </ChatLog>
    </Workspace>
  )
}
