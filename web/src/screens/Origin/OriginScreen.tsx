import { useEffect, useRef, useState } from 'react'
import { api, ApiRequestError, toApiError } from '../../api/client.ts'
import type { ApiError, ContextBudget, ConversationOut, SourcePreview, StartOption, StartProposal } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, ChatLog, FixedOperation, UserMessage } from '../../components/Chat/index.ts'
import { Composer } from '../../components/Composer/index.ts'
import { ErrorCard } from '../../components/States/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import type { StartRequest } from '../Home/HomeScreen.tsx'
import styles from './Origin.module.css'
import { ProposalMessage, type ProposalMessageProps } from './ProposalMessage.tsx'
import { BUDGET_DEBOUNCE_MS, BUDGET_FAILED, budgetView } from './budget.ts'
import { NOTED, composerPlaceholder, detailsOf, latestProposal, type Turn } from './conversation.ts'
import { createBody, fixedTitle, operationFromIssue, operationFromOption, sourceDetail, type Operation } from './operation.ts'

export interface OriginScreenProps {
  request: StartRequest
  /** «Cambiar» la operación: vuelve a Inicio (solo antes de generar). */
  onBack: () => void
  /** POST /conversations aceptado (202): la conversación empieza a generar. */
  onGenerating: (conversation: ConversationOut) => void
}

const FIXED_TEXT = 'No cambia durante la conversación; es lo único que se podrá aprobar y publicar.'

// Mixta 2 · Origen fijado (UI.md §4.3): HU parecida o reconocida sin IA, operación fijada y fuentes.
export function OriginScreen({ request, onBack, onGenerating }: OriginScreenProps) {
  const mode = request.flow === 'tests' ? 'qa' : 'functional'
  const [operation, setOperation] = useState<Operation | undefined>(
    request.origin
      ? operationFromIssue(request.origin, request.proposal?.project ?? request.project, request.flow, request.text)
      : undefined,
  )
  // La conversación en orden: el primer turno es lo escrito en Inicio con su propuesta.
  const [turns, setTurns] = useState<Turn[]>([{ kind: 'ask', text: request.text, proposal: request.proposal }])
  // Esperando a POST /start/propose: composer y opciones desactivados.
  const [proposing, setProposing] = useState(false)
  const [sources, setSources] = useState<SourcePreview[]>([])
  const [budget, setBudget] = useState<ContextBudget | undefined>()
  // Fuentes excluidas con las que se calculó `budget` (clave estable de la lista).
  const budgetFor = useRef('')
  const [excluded, setExcluded] = useState<string[]>([])
  const [restrictions, setRestrictions] = useState('')
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<ApiError | undefined>()
  const [generating, setGenerating] = useState(false)

  const latest = latestProposal(turns)
  // Proyecto de la conversación: el de la última propuesta. Panel y fuentes solo cambian al elegir.
  const project = latest?.project ?? request.project

  // PA-313: si una propuesta cambió de proyecto, se fija (una vez por propuesta) y se avisa con ella.
  const projectFixed = useRef(new WeakSet<object>())
  useEffect(() => {
    if (!latest?.project_changed || projectFixed.current.has(latest)) return
    projectFixed.current.add(latest)
    api.chooseProject(latest.project).catch((cause: unknown) => {
      if (cause instanceof ApiRequestError) setError(cause.error)
    })
  }, [latest])

  useEffect(() => {
    if (!operation) return
    let cancelled = false
    api
      .sources(operation.origin)
      .then((value) => {
        if (cancelled) return
        // La lista sale de la consulta sin exclusiones: con ellas, el backend ya no devuelve las desmarcadas.
        setSources(value.sources)
        setBudget(value.budget)
        budgetFor.current = ''
      })
      .catch((cause: unknown) => {
        if (!cancelled && cause instanceof ApiRequestError) setError(cause.error)
      })
    return () => {
      cancelled = true
    }
  }, [operation])

  // Al cambiar las casillas, solo se vuelve a pedir el presupuesto (PA-102), con una espera entre clics.
  useEffect(() => {
    if (!operation) return
    const key = excluded.join('\n')
    if (key === budgetFor.current) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      api
        .sources(operation.origin, excluded)
        .then((value) => {
          if (cancelled) return
          budgetFor.current = key
          setBudget(value.budget)
        })
        .catch(() => {
          if (cancelled) return
          // Sin presupuesto válido: la próxima vez se vuelve a pedir aunque las casillas coincidan.
          budgetFor.current = BUDGET_FAILED
          setBudget(undefined)
        })
    }, BUDGET_DEBOUNCE_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [operation, excluded])

  const budgetInfo = budgetView(budget)

  const toggle = (ref: string) =>
    setExcluded((current) => (current.includes(ref) ? current.filter((item) => item !== ref) : [...current, ref]))

  const generate = async () => {
    if (!operation) return
    setGenerating(true)
    setError(undefined)
    const allRestrictions = [restrictions, ...detailsOf(turns)].map((item) => item.trim()).filter(Boolean).join('\n')
    try {
      onGenerating(await api.createConversation(createBody(operation, allRestrictions, excluded)))
    } catch (cause) {
      setError(toApiError(cause))
    } finally {
      setGenerating(false)
    }
  }

  const choose = (option: StartOption, optionProject: string) => setOperation(operationFromOption(option, optionProject))

  // Sin operación, un mensaje vuelve a pedir la propuesta; con ella, es un detalle para generar.
  const send = async () => {
    const text = draft.trim()
    if (!text) return
    setDraft('')
    if (operation) {
      setTurns((current) => [...current, { kind: 'detail', text }])
      return
    }
    const index = turns.length
    setTurns((current) => [...current, { kind: 'ask', text }])
    setError(undefined)
    setProposing(true)
    try {
      const proposal = await api.propose({ text, project, mode })
      setTurns((current) => current.map((turn, at) => (at === index && turn.kind === 'ask' ? { ...turn, proposal } : turn)))
    } catch (cause) {
      setError(toApiError(cause))
    } finally {
      setProposing(false)
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

          {budgetInfo && (
            <div className={styles.budget} data-warning={budgetInfo.warning ? '' : undefined} aria-live="polite">
              <span className={styles.budgetLabel}>{budgetInfo.label}</span>
              <span className={styles.budgetTrack} aria-hidden="true">
                <span className={styles.budgetValue} style={{ width: `${budgetInfo.percent}%` }} />
              </span>
              {budgetInfo.notes.map((note) => (
                <span key={note} className={styles.budgetNote}>
                  {note}
                </span>
              ))}
            </div>
          )}
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
          placeholder={composerPlaceholder(operation !== undefined)}
          value={draft}
          onChange={setDraft}
          canSubmit={draft.trim().length > 0}
          disabled={proposing}
          submitLabel="Enviar"
          onSubmit={() => void send()}
        />
      }
    >
      <ChatLog>
        {turns.map((turn, index) =>
          turn.kind === 'ask' ? (
            <AskTurn
              key={`ask-${index}`}
              text={turn.text}
              proposal={turn.proposal}
              mode={mode}
              disabled={operation !== undefined || proposing || turn.proposal !== latest}
              onChoose={choose}
              origin={index === 0 ? request.origin : undefined}
            />
          ) : undefined,
        )}

        {operation && (
          <>
            {latest && <UserMessage>{operation.label}</UserMessage>}
            <AssistantMessage animate>
              <FixedOperation title={fixedTitle(operation)}>{FIXED_TEXT}</FixedOperation>
              <p>He preparado el contexto. Revisa las fuentes en el panel, añade restricciones si las hay y genera cuando quieras.</p>
            </AssistantMessage>
          </>
        )}

        {turns.map((turn, index) =>
          turn.kind === 'detail' ? (
            <DetailTurn key={`detail-${index}`} text={turn.text} />
          ) : undefined,
        )}

        {error && (
          <AssistantMessage>
            <ErrorCard key={`${error.code}-${error.message}`} error={error} onAction={() => setError(undefined)} />
          </AssistantMessage>
        )}
      </ChatLog>
    </Workspace>
  )
}

function AskTurn({
  text,
  proposal,
  ...props
}: { text: string; proposal?: StartProposal } & Omit<ProposalMessageProps, 'proposal'>) {
  return (
    <>
      {text && <UserMessage>{text}</UserMessage>}
      {proposal && <ProposalMessage proposal={proposal} {...props} />}
    </>
  )
}

function DetailTurn({ text }: { text: string }) {
  return (
    <>
      <UserMessage>{text}</UserMessage>
      <AssistantMessage>
        <p>{NOTED}</p>
      </AssistantMessage>
    </>
  )
}
