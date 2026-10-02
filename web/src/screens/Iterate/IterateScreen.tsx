import { useEffect, useId, useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, ChatLog, UserMessage } from '../../components/Chat/index.ts'
import { Chip } from '../../components/Chip/index.ts'
import { Composer, ModelTag } from '../../components/Composer/index.ts'
import { ChangesView, changesLabel, ImpactView, SourcesView, StoryView, Tabs, VersionSelector, versionSummary } from '../../components/Proposal/index.ts'
import { TypewriterText, TypingIndicator } from '../../components/QMark/index.ts'
import { ErrorCard } from '../../components/States/index.ts'
import { conversationTitle } from '../../components/ConversationList/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import { useGeneration } from '../Generating/useGeneration.ts'
import styles from './Iterate.module.css'
import { modelLabel, proposalVersions, SUGGESTIONS } from './iterateText.ts'

export interface IterateScreenProps {
  conversation: ConversationOut
  /** La propuesta se descartó (POST /discard): vuelve a Inicio. */
  onDiscarded: () => void
  /** La conversación no puede continuar (error o «empezar de nuevo»): vuelve a Inicio. */
  onRestart: () => void
}

type PanelTab = 'proposal' | 'changes' | 'impact' | 'sources'

type Entry = { kind: 'user'; text: string } | { kind: 'assistant'; version: number; animate: boolean }

const SOON_TEXT = 'Disponible pronto: llega después del punto de control de la demo.'

// Acción que aún no está en la demo (DESIGN-DECISIONS.md §4 bis): enfocable, con su descripción y sin efecto.
function SoonButton({ label, primary = false }: { label: string; primary?: boolean }) {
  const noteId = useId()
  return (
    <>
      <Button variant={primary ? 'primary' : 'secondary'} className={styles.soon} aria-disabled="true" aria-describedby={noteId}>
        {label}
      </Button>
      <span id={noteId} className="visually-hidden">
        {SOON_TEXT}
      </span>
    </>
  )
}

// Seguir una iteración en curso: cuando llega review_ready, la propuesta nueva sustituye a la anterior.
function Iterating({
  conversation,
  onReady,
  onError,
}: {
  conversation: ConversationOut
  onReady: (conversation: ConversationOut) => void
  onError: (error: ApiError) => void
}) {
  const state = useGeneration(conversation)
  useEffect(() => {
    if (state.status === 'ready') onReady(state.conversation)
    if (state.status === 'error') onError(state.error)
    // Solo al cambiar de estado: los manejadores cambian en cada render del padre.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.status])
  return <TypingIndicator />
}

// Mixta 3 · Iterar (UI.md §4.5): conversación para pedir cambios y panel de la propuesta con sus versiones.
export function IterateScreen({ conversation: initial, onDiscarded, onRestart }: IterateScreenProps) {
  const [conversation, setConversation] = useState(initial)
  const versions = proposalVersions(conversation)
  const latest = versions.at(-1)
  const [selected, setSelected] = useState(latest?.version ?? 1)
  const [tab, setTab] = useState<PanelTab>('proposal')
  const [entries, setEntries] = useState<Entry[]>(() => [{ kind: 'assistant', version: latest?.version ?? 1, animate: false }])
  const [draft, setDraft] = useState('')
  const [iterating, setIterating] = useState<ConversationOut | undefined>()
  const [error, setError] = useState<ApiError | undefined>()
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [busy, setBusy] = useState(false)

  const shown = versions.find((item) => item.version === selected) ?? latest
  const diffs = shown?.impact?.diffs ?? []

  const send = async (feedback: string) => {
    const text = feedback.trim()
    if (!text) return
    setError(undefined)
    setDraft('')
    setEntries((current) => [...current, { kind: 'user', text }])
    try {
      setIterating(await api.iterate(conversation.id, text))
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

  const tabs = [
    { id: 'proposal' as const, label: 'Propuesta' },
    { id: 'changes' as const, label: `Cambios (${diffs.length})` },
    { id: 'impact' as const, label: `Impacto (${shown?.impact?.affected.length ?? 0})` },
    { id: 'sources' as const, label: `Fuentes (${shown?.story.sources.length ?? 0})` },
  ]

  const panel = shown && (
    <SidePanel
      title="Propuesta de HU"
      subtitle={`${conversationTitle(conversation.title)} · ${iterating ? 'generando' : 'en revisión'}`}
      size="md"
      headerActions={<VersionSelector versions={versions.map((item) => item.version)} selected={selected} onSelect={setSelected} />}
      footer={
        confirmDiscard ? (
          <div className={styles.confirm} role="group" aria-label="Confirmar el descarte">
            <span>¿Descartar la propuesta? No se publicará nada en Jira y la conversación terminará.</span>
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
            <SoonButton label="Revisar y aprobar" primary />
          </div>
        )
      }
    >
      <Tabs label="Contenido del panel" tabs={tabs} selected={tab} onSelect={setTab}>
        {tab === 'proposal' && <StoryView key={shown.version} story={shown.story} version={shown.version} diffs={diffs} />}
        {tab === 'changes' && <ChangesView diffs={diffs} />}
        {tab === 'impact' && <ImpactView impact={shown.impact} />}
        {tab === 'sources' && <SourcesView sources={shown.story.sources} />}
      </Tabs>
    </SidePanel>
  )

  const lastAssistant = entries.map((entry) => entry.kind).lastIndexOf('assistant')

  return (
    <Workspace
      title={conversationTitle(conversation.title)}
      phase={2}
      panel={panel}
      composer={
        <Composer
          placeholder={iterating ? 'Espera a la propuesta para pedir cambios' : 'Pide un cambio a la propuesta'}
          value={draft}
          onChange={setDraft}
          canSubmit={draft.trim().length > 0}
          disabled={Boolean(iterating)}
          submitLabel="Enviar"
          onSubmit={() => void send(draft)}
          tools={<ModelTag label="Modelo automático" />}
        />
      }
    >
      <ChatLog>
        {conversation.feedback.length > 0 && entries.length === 1 && (
          <>
            {conversation.feedback.map((item, index) => (
              <UserMessage key={`previo-${index}`}>{item}</UserMessage>
            ))}
          </>
        )}
        {entries.map((entry, index) => {
          if (entry.kind === 'user') return <UserMessage key={`u-${index}`}>{entry.text}</UserMessage>
          const item = versions.find((candidate) => candidate.version === entry.version)
          if (!item) return null
          const summary = versionSummary(item.story, item.version, item.impact)
          const model = modelLabel(item.artifact.model_used)
          return (
            <AssistantMessage key={`a-${entry.version}`} animate={entry.animate}>
              <span>{entry.animate ? <TypewriterText text={summary} /> : summary}</span>
              <button
                type="button"
                className={styles.artifact}
                aria-pressed={selected === item.version}
                onClick={() => {
                  setSelected(item.version)
                  setTab('proposal')
                }}
              >
                <span className={styles.artifactTitle}>Propuesta de HU, versión {item.version}</span>
                <span className={styles.meta}>
                  {selected === item.version ? 'Abierta en el panel' : 'Abrir en el panel'} · {changesLabel(item.impact?.diffs.length ?? 0)}
                </span>
              </button>
              {model && (
                <span className={styles.meta}>
                  Generado con {model} · {item.story.sources.length} fuentes
                </span>
              )}
              {index === lastAssistant && !iterating && (
                <ul className={styles.suggestions} aria-label="Cambios sugeridos">
                  {SUGGESTIONS.map((suggestion) => (
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
              onReady={(next) => {
                const version = proposalVersions(next).at(-1)?.version ?? selected
                setConversation(next)
                setIterating(undefined)
                setSelected(version)
                setTab('proposal')
                setEntries((current) => [...current, { kind: 'assistant', version, animate: true }])
              }}
              onError={(failure) => {
                setIterating(undefined)
                setError(failure)
              }}
            />
          </AssistantMessage>
        )}

        {error && (
          <AssistantMessage>
            <ErrorCard
              key={`${error.code}-${error.message}`}
              error={error}
              onAction={error.code === 'restart' || error.code === 'approval_rejected' ? onRestart : () => setError(undefined)}
            />
          </AssistantMessage>
        )}
      </ChatLog>
    </Workspace>
  )
}
