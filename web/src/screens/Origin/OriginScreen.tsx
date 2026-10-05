import { useEffect, useRef, useState } from 'react'
import { api, ApiRequestError, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut, IssueCard, IssueSummary, SourcePreview } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, ChatLog, FixedOperation, FoundIssue, UserMessage } from '../../components/Chat/index.ts'
import { Composer } from '../../components/Composer/index.ts'
import { ErrorCard } from '../../components/States/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import type { StartRequest } from '../Home/HomeScreen.tsx'
import styles from './Origin.module.css'
import { createBody, fixedTitle, operationFromIssue, operationFromOption, sourceDetail, type Operation } from './operation.ts'

export interface OriginScreenProps {
  request: StartRequest
  /** «Cambiar» la operación: vuelve a Inicio (solo antes de generar). */
  onBack: () => void
  /** POST /conversations aceptado (202): la conversación empieza a generar. */
  onGenerating: (conversation: ConversationOut) => void
}

const FIXED_TEXT = 'No cambia durante la conversación; es lo único que se podrá aprobar y publicar.'

function issueDetail(issue: IssueSummary, card: IssueCard | undefined): string {
  if (!card) return `${issue.issue_type} · ${issue.status}`
  const parts = [card.epic_key ? `Épica ${card.epic_key}` : undefined, `${card.criteria_count} criterios y ${card.rules_count} reglas`]
  return parts.filter(Boolean).join(' · ')
}

// Mixta 2 · Origen fijado (UI.md §4.3): HU parecida o reconocida sin IA, operación fijada y fuentes.
export function OriginScreen({ request, onBack, onGenerating }: OriginScreenProps) {
  const proposal = request.proposal
  const project = proposal?.project ?? request.project
  const [operation, setOperation] = useState<Operation | undefined>(
    request.origin ? operationFromIssue(request.origin, project, request.flow, request.text) : undefined,
  )
  const [card, setCard] = useState<IssueCard | undefined>()
  const [sources, setSources] = useState<SourcePreview[]>([])
  const [excluded, setExcluded] = useState<string[]>([])
  const [restrictions, setRestrictions] = useState('')
  const [details, setDetails] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<ApiError | undefined>()
  const [generating, setGenerating] = useState(false)

  const shown = proposal?.recognized[0] ?? proposal?.similar[0] ?? request.origin
  const recognized = (proposal?.recognized.length ?? 0) > 0

  // PA-313: si el arranque guiado cambió de proyecto, se fija (una vez) y se avisa en la conversación.
  const projectFixed = useRef(false)
  useEffect(() => {
    if (!proposal?.project_changed || projectFixed.current) return
    projectFixed.current = true
    api.chooseProject(proposal.project).catch((cause: unknown) => {
      if (cause instanceof ApiRequestError) setError(cause.error)
    })
  }, [proposal])

  useEffect(() => {
    if (!shown) return
    let cancelled = false
    api
      .issue(shown.key)
      .then((value) => !cancelled && setCard(value))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [shown])

  useEffect(() => {
    if (!operation) return
    let cancelled = false
    api
      .sources(operation.origin)
      .then((value) => !cancelled && setSources(value.sources))
      .catch((cause: unknown) => {
        if (!cancelled && cause instanceof ApiRequestError) setError(cause.error)
      })
    return () => {
      cancelled = true
    }
  }, [operation])

  const toggle = (ref: string) =>
    setExcluded((current) => (current.includes(ref) ? current.filter((item) => item !== ref) : [...current, ref]))

  const generate = async () => {
    if (!operation) return
    setGenerating(true)
    setError(undefined)
    const allRestrictions = [restrictions, ...details].map((item) => item.trim()).filter(Boolean).join('\n')
    try {
      onGenerating(await api.createConversation(createBody(operation, allRestrictions, excluded)))
    } catch (cause) {
      setError(toApiError(cause))
    } finally {
      setGenerating(false)
    }
  }

  const title = request.text ? request.text.split('\n')[0] ?? '' : (operation?.label ?? 'Nueva conversación')

  const panel = (
    <SidePanel
      title="Antes de generar"
      footer={
        <>
          <Button variant="primary" className={styles.generate} disabled={!operation || generating} onClick={() => void generate()}>
            {generating ? 'Generando…' : 'Generar propuesta'}
          </Button>
          <p className={styles.note}>Una llamada al modelo. Después itera conversando.</p>
        </>
      }
    >
      {!operation ? (
        <p className={styles.hint}>Elige la operación en la conversación para ver las fuentes que se usarán.</p>
      ) : (
        <>
          <div className={styles.card}>
            <div className={styles.cardHead}>
              <span className={styles.label}>Operación</span>
              <Button size="sm" variant="ghost" onClick={onBack}>
                Cambiar
              </Button>
            </div>
            <span className={styles.operation}>
              {operation.label}
              {operation.issue ? ` · ${operation.issue.summary}` : ''}
            </span>
            <span className={styles.hint}>Se puede cambiar solo antes de generar.</span>
          </div>

          <div className={styles.field}>
            <label htmlFor="restrictions" className={styles.label}>
              Restricciones (opcional)
            </label>
            <textarea
              id="restrictions"
              className={styles.textarea}
              rows={2}
              value={restrictions}
              onChange={(event) => setRestrictions(event.target.value)}
            />
          </div>

          <fieldset className={styles.sources}>
            <legend className={styles.legend}>Fuentes que se usarán</legend>
            {sources.map((source) => {
              const included = !excluded.includes(source.ref)
              return (
                <label
                  key={source.ref}
                  htmlFor={`source-${source.ref}`}
                  className={styles.source}
                  data-required={source.required ? '' : undefined}
                >
                  <input
                    id={`source-${source.ref}`}
                    type="checkbox"
                    checked={included}
                    disabled={source.required}
                    onChange={() => toggle(source.ref)}
                  />
                  <span className={styles.sourceText}>
                    {source.title}
                    <span className={styles.code}>{sourceDetail(source, included)}</span>
                  </span>
                </label>
              )
            })}
          </fieldset>
        </>
      )}
    </SidePanel>
  )

  return (
    <Workspace
      title={title}
      phase={1}
      panel={panel}
      composer={
        <Composer
          placeholder="Añade detalles a la necesidad (opcional)"
          value={draft}
          onChange={setDraft}
          canSubmit={draft.trim().length > 0}
          submitLabel="Enviar"
          onSubmit={() => {
            setDetails((current) => [...current, draft.trim()])
            setDraft('')
          }}
        />
      }
    >
      <ChatLog>
        {request.text && <UserMessage>{request.text}</UserMessage>}

        {proposal && (
          <AssistantMessage>
            {proposal.project_changed && (
              <p>
                La clave es del proyecto <b>{proposal.project}</b>: la conversación pasa a {proposal.project}.
              </p>
            )}
            {proposal.ignored_projects.length > 0 && (
              <p>Las claves de otros proyectos ({proposal.ignored_projects.join(', ')}) no se usan en esta conversación.</p>
            )}
            {shown ? (
              <>
                <Badge icon="search">{recognized ? 'Clave reconocida en Jira · sin IA' : 'Búsqueda en Jira por texto · sin IA'}</Badge>
                <p>
                  {recognized
                    ? `He reconocido ${shown.key} en el proyecto ${project}.`
                    : `En el proyecto ${project} hay una HU parecida. ¿La evolucionamos o creamos una nueva?`}
                </p>
              </>
            ) : (
              <p>No he encontrado HU parecidas en el proyecto {project}.</p>
            )}
            <FoundIssue
              title={shown ? `${shown.key}, ${shown.summary}` : 'HU nueva'}
              detail={shown ? issueDetail(shown, card) : `En el proyecto ${project}`}
              actions={proposal.options.map((option, index) => (
                <Button
                  key={option.label}
                  size="md"
                  variant={index === 0 ? 'primary' : 'secondary'}
                  disabled={operation !== undefined}
                  onClick={() => setOperation(operationFromOption(option, project))}
                >
                  {option.label}
                </Button>
              ))}
            />
          </AssistantMessage>
        )}

        {operation && (
          <>
            {proposal && <UserMessage>{operation.label}</UserMessage>}
            <AssistantMessage animate>
              <FixedOperation title={fixedTitle(operation)}>{FIXED_TEXT}</FixedOperation>
              <p>He preparado el contexto. Revisa las fuentes en el panel, añade restricciones si las hay y genera cuando quieras.</p>
            </AssistantMessage>
          </>
        )}

        {details.map((detail, index) => (
          <UserMessage key={`${index}-${detail}`}>{detail}</UserMessage>
        ))}

        {error && (
          <AssistantMessage>
            <ErrorCard key={`${error.code}-${error.message}`} error={error} onAction={() => setError(undefined)} />
          </AssistantMessage>
        )}
      </ChatLog>
    </Workspace>
  )
}
