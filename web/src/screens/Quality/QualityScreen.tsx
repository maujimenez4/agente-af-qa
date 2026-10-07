import { useEffect, useRef, useState } from 'react'
import { api, isAbortError, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut, QualityReport, QualityReviewOut } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, ChatLog, FoundIssue, UserMessage } from '../../components/Chat/index.ts'
import { DownloadButton } from '../../components/Download/index.ts'
import { ErrorCard, LoadingState, Skeleton } from '../../components/States/index.ts'
import { SidePanel, Workspace } from '../../components/Workspace/index.ts'
import { MarkdownBlocks } from '../../components/Markdown/index.ts'
import type { StartRequest } from '../Home/HomeScreen.tsx'
import styles from './Quality.module.css'
import {
  doneMessage,
  findingTag,
  FOOTER_NOTE,
  INTRO,
  investInOrder,
  INVEST_NAMES,
  NO_FINDINGS,
  NOT_FOUND,
  projectOf,
  QUALITY_MAX_WAIT_MS,
  qualityPollDelay,
  QUALITY_TITLE,
  qualityHeading,
  READ_ONLY,
  RECHECK,
  REPORT_TITLE,
  reportFileName,
  reportSummary,
  REVIEW_AGAIN,
  reviewCandidates,
  reviewStartedAt,
  RUNNING_NOTE,
  SOURCE_KINDS,
  STALE_REVIEW,
  VERDICT_LABELS,
} from './qualityText.ts'

export interface QualityScreenProps {
  /** Desde Inicio con el flujo «Revisar la calidad»: lo escrito y la propuesta (claves reconocidas). */
  request?: StartRequest
  /** Desde la lista: una revisión guardada («Informe listo» o en curso). */
  reviewId?: string
  onBack: () => void
  /** La revisión se creó o cambió de estado: la lista se vuelve a pedir. */
  onChanged: () => void
  /** *Evolucionar con esto* abrió una conversación nueva (202): pasa a Generando. */
  onEvolve: (conversation: ConversationOut) => void
}

// Mixta 5 · Revisar la calidad (UI.md §4.8; T-48): flujo propio y de solo lectura, sin restricciones ni conversación.
// La API no tiene SSE para la calidad: una revisión `running` se consulta (2 s y después 10 s) hasta `done`, `error`
// o el tope de 30 min (PA-406).
export function QualityScreen({ request, reviewId, onBack, onChanged, onEvolve }: QualityScreenProps) {
  const [review, setReview] = useState<QualityReviewOut | undefined>()
  const [pending, setPending] = useState<string | undefined>(reviewId)
  const [error, setError] = useState<ApiError | undefined>()
  const [attempt, setAttempt] = useState(0)
  const [starting, setStarting] = useState(false)
  // PA-406: el tope de 30 min cuenta desde `created_at` (o desde que se abrió la pantalla) o, tras *Volver a
  // consultar*, desde ese clic. Al pasarlo, deja de consultar y sale la tarjeta `stale`.
  const [openedAt] = useState(() => Date.now())
  const [windowStart, setWindowStart] = useState<number | undefined>()
  const [stale, setStale] = useState(false)
  const recheckNow = useRef(false)
  // Un solo POST aunque se pulse dos veces *Revisar* (el `disabled` llega con el siguiente render).
  const startingNow = useRef(false)

  // Consulta la revisión pendiente: al abrirla desde la lista y, mientras está en curso, cada 2 s los dos
  // primeros minutos y después cada 10 s, hasta el tope.
  useEffect(() => {
    if (!pending || stale) return
    const controller = new AbortController()
    const since = (value: QualityReviewOut) => windowStart ?? reviewStartedAt(value.created_at, openedAt)
    const load = () =>
      api
        .qualityReview(pending, controller.signal)
        .then((value) => {
          if (controller.signal.aborted) return
          setReview(value)
          setError(undefined)
          if (value.state !== 'running') {
            setPending(undefined)
            onChanged()
          } else if (Date.now() - since(value) >= QUALITY_MAX_WAIT_MS) {
            setStale(true)
          }
        })
        .catch((cause: unknown) => {
          if (!isAbortError(cause)) setError(toApiError(cause))
        })
    const first = review?.state === 'running' && !recheckNow.current
    recheckNow.current = false
    const timer = first && review ? window.setTimeout(() => void load(), qualityPollDelay(Date.now() - since(review))) : undefined
    if (!first) void load()
    return () => {
      controller.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
    // `review` cambia en cada consulta: vuelve a programar la siguiente mientras siga en curso.
  }, [pending, review, attempt, onChanged, stale, windowStart, openedAt])

  // *Volver a consultar*: una consulta ya y otra ventana de 30 min desde ahora.
  const recheck = () => {
    recheckNow.current = true
    setWindowStart(Date.now())
    setStale(false)
  }

  const start = async (issueKey: string) => {
    if (startingNow.current) return
    startingNow.current = true
    setStarting(true)
    setError(undefined)
    try {
      const created = await api.startQualityReview({ issue_key: issueKey, excluded_sources: [] })
      // Revisión nueva, ventana nueva: aunque su `created_at` no se pueda leer, no hereda la de la apertura.
      setWindowStart(Date.now())
      setStale(false)
      setReview(created)
      setPending(created.state === 'running' ? created.id : undefined)
      onChanged()
    } catch (cause) {
      setError(toApiError(cause))
    } finally {
      startingNow.current = false
      setStarting(false)
    }
  }

  const retryLoad = () => {
    setError(undefined)
    setAttempt((count) => count + 1)
  }

  if (!review) {
    if (reviewId) {
      return (
        <Workspace title={QUALITY_TITLE} phaseName={READ_ONLY}>
          {error ? (
            <ErrorCard key={attempt} error={error} onAction={retryLoad} />
          ) : (
            <div role="status" aria-label="Cargando la revisión">
              <Skeleton lines={4} />
            </div>
          )}
        </Workspace>
      )
    }
    return <ChooseIssue request={request} starting={starting} error={error} onStart={(key) => void start(key)} onBack={onBack} />
  }

  const key = review.issue_key
  const report = review.state === 'done' ? review.report : null
  return (
    <Workspace
      title={qualityHeading(key)}
      phaseName={READ_ONLY}
      panel={report ? <ReportPanel review={review} report={report} onEvolve={onEvolve} /> : undefined}
    >
      <ChatLog>
        <UserMessage>Revisa la calidad de {key}.</UserMessage>
        {review.state === 'running' && !stale && (
          <AssistantMessage>
            <LoadingState title={`Revisando la calidad de ${key}…`} events={[]} running />
            <p className={styles.muted}>{RUNNING_NOTE}</p>
            {error && <ErrorCard key={attempt} error={error} onAction={retryLoad} />}
          </AssistantMessage>
        )}
        {review.state === 'running' && stale && (
          <AssistantMessage>
            {/* PA-406: pasado el tope ya no se consulta; la persona decide si esperar otra ventana o empezar otra. */}
            <ErrorCard error={STALE_REVIEW} />
            {error && <ErrorCard key={`start-${attempt}`} error={error} />}
            <div className={styles.actions}>
              <Button size="md" onClick={recheck}>
                {RECHECK}
              </Button>
              <Button variant="primary" size="md" disabled={starting} onClick={() => void start(key)}>
                {starting ? 'Empezando…' : REVIEW_AGAIN}
              </Button>
            </div>
          </AssistantMessage>
        )}
        {review.state === 'error' && (
          <AssistantMessage>
            {/* El fallo llega en `QualityReviewOut.error`, no como error HTTP; su mensaje, tal cual. */}
            <ErrorCard
              key={review.id}
              error={review.error ?? { code: 'quality_failed', message: 'No se pudo revisar la calidad.' }}
              onAction={() => void start(key)}
            />
            {error && <ErrorCard key={`start-${attempt}`} error={error} />}
            <p className={styles.muted}>Nada se ha escrito en Jira.</p>
          </AssistantMessage>
        )}
        {report && (
          <AssistantMessage animate>
            {doneMessage(review).map((line) => (
              <p key={line}>{line}</p>
            ))}
            <FoundIssue icon="searchSource" title={`${REPORT_TITLE} de ${key}`} detail="En el panel" />
          </AssistantMessage>
        )}
      </ChatLog>
    </Workspace>
  )
}

function ChooseIssue({
  request,
  starting,
  error,
  onStart,
  onBack,
}: {
  request?: StartRequest
  starting: boolean
  error?: ApiError
  onStart: (key: string) => void
  onBack: () => void
}) {
  const candidates = request ? reviewCandidates(request) : []
  return (
    <Workspace title={QUALITY_TITLE} phaseName={READ_ONLY}>
      <ChatLog>
        {request?.text && <UserMessage>{request.text}</UserMessage>}
        <AssistantMessage animate>
          {candidates.length > 0 ? (
            <>
              <p>{INTRO}</p>
              {candidates.map((issue) => (
                <FoundIssue
                  key={issue.key}
                  title={issue.key}
                  detail={issue.summary}
                  actions={
                    <Button variant="primary" size="md" disabled={starting} onClick={() => onStart(issue.key)}>
                      {starting ? 'Empezando…' : `Revisar ${issue.key}`}
                    </Button>
                  }
                />
              ))}
            </>
          ) : (
            <p>{NOT_FOUND}</p>
          )}
          <span>
            <Button size="md" onClick={onBack}>
              Volver al inicio
            </Button>
          </span>
        </AssistantMessage>
        {error && (
          <AssistantMessage>
            <ErrorCard key={`${error.code}-${error.message}`} error={error} />
          </AssistantMessage>
        )}
      </ChatLog>
    </Workspace>
  )
}

function ReportPanel({
  review,
  report,
  onEvolve,
}: {
  review: QualityReviewOut
  report: QualityReport
  onEvolve: (conversation: ConversationOut) => void
}) {
  const key = review.issue_key
  const [evolving, setEvolving] = useState(false)
  const [evolveError, setEvolveError] = useState<ApiError | undefined>()

  // Conversación nueva para evolucionar la HU con las mejoras del informe como punto de partida (T-52).
  const evolve = async () => {
    setEvolving(true)
    setEvolveError(undefined)
    try {
      onEvolve(
        await api.createConversation({
          flow: 'evolve',
          origin: { kind: 'story', key, project: projectOf(key) },
          excluded_sources: [],
          feedback: review.evolve_feedback,
        }),
      )
    } catch (cause) {
      setEvolveError(toApiError(cause))
    } finally {
      setEvolving(false)
    }
  }

  return (
    <SidePanel
      title={REPORT_TITLE}
      subtitle={key}
      // Resumen contado sin IA a partir del veredicto, fijo bajo el título (puede ocupar varias líneas).
      toolbar={<p className={styles.summary}>{reportSummary(report)}</p>}
      size="md"
      footer={
        <>
          <div className={styles.actions}>
            <DownloadButton label="Descargar informe" fileName={reportFileName(key)} text={review.report_markdown} size="md" />
            {review.evolve_feedback.length > 0 && (
              <Button variant="primary" size="md" disabled={evolving} onClick={() => void evolve()}>
                {evolving ? 'Abriendo…' : `Evolucionar ${key} con esto`}
              </Button>
            )}
          </div>
          {evolveError && <ErrorCard key={`${evolveError.code}-${evolveError.message}`} error={evolveError} />}
          <p className={styles.note}>{FOOTER_NOTE}</p>
        </>
      }
    >
      <section aria-labelledby="quality-invest" className={styles.section}>
        <h3 id="quality-invest" className={styles.sectionTitle}>
          INVEST
        </h3>
        <ul className={styles.invest}>
          {investInOrder(report.invest).map((check) => (
            <li key={check.letter} className={styles.letter} data-verdict={check.verdict}>
              <b className={styles.letterName} aria-hidden="true">
                {check.letter}
              </b>
              <span className={styles.letterLabel}>{INVEST_NAMES[check.letter]}</span>
              <span className={styles.verdict}>{VERDICT_LABELS[check.verdict]}</span>
              <span className="visually-hidden">: {check.reason}</span>
            </li>
          ))}
        </ul>
        <ul className={styles.reasons}>
          {investInOrder(report.invest)
            .filter((check) => check.verdict === 'improvable')
            .map((check) => (
              <li key={check.letter} aria-hidden="true">
                <b>{INVEST_NAMES[check.letter]}:</b> {check.reason}
              </li>
            ))}
        </ul>
      </section>

      <section aria-labelledby="quality-findings" className={styles.section}>
        <h3 id="quality-findings" className={styles.sectionTitle}>
          Hallazgos
        </h3>
        {report.findings.length === 0 ? (
          <p className={styles.muted}>{NO_FINDINGS}</p>
        ) : (
          <ul className={styles.findings}>
            {report.findings.map((finding, index) => (
              <li key={index} className={styles.finding} data-kind={finding.kind}>
                <span className={styles.kind}>{findingTag(finding)}</span>
                <span>{finding.explanation}</span>
                <span className={styles.muted}>Propuesta: {finding.proposal}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {report.open_questions.length > 0 && (
        <section aria-labelledby="quality-questions" className={styles.section}>
          <h3 id="quality-questions" className={styles.sectionTitle}>
            Preguntas para negocio
          </h3>
          <ul className={styles.list}>
            {report.open_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </section>
      )}

      {report.sources.length > 0 && (
        <section aria-labelledby="quality-sources" className={styles.section}>
          <h3 id="quality-sources" className={styles.sectionTitle}>
            Fuentes
          </h3>
          <ul className={styles.sources}>
            {report.sources.map((source) => (
              <li key={`${source.kind}-${source.ref}`} className={styles.source}>
                <Badge tone="cite">{SOURCE_KINDS[source.kind]}</Badge>
                <span className={styles.sourceRef}>{source.ref}</span>
                {source.excerpt && <MarkdownBlocks className={`${styles.muted} ${styles.sourceExcerpt}`} text={source.excerpt} />}
              </li>
            ))}
          </ul>
        </section>
      )}
    </SidePanel>
  )
}
