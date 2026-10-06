import { useEffect, useState } from 'react'
import { api, isAbortError, toApiError } from '../../api/client.ts'
import type { AdminModelOut, AdminModelsOut, ApiError, ConnectionCheckOut, SettingsOut } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { Button, SoonButton } from '../../components/Button/index.ts'
import { ErrorCard, Notice, Skeleton } from '../../components/States/index.ts'
import styles from './Admin.module.css'
import {
  ADMIN_FOOTER,
  ADMIN_SUBTITLE,
  ADMIN_TITLE,
  CONNECTION_FAILED,
  CONNECTION_OK,
  CONNECTIONS_IDLE,
  CONNECTIONS_TESTING,
  CONNECTIONS_TITLE,
  DOCUMENTS_TEXT,
  DOCUMENTS_TITLE,
  durationLabel,
  EMBEDDINGS_LABEL,
  MODELS_NOTE,
  MODELS_TITLE,
  modelName,
  NO_FALLBACK,
  PUBLISH_LIVE_TEXT,
  PUBLISH_MODE_LABELS,
  PUBLISH_SIMULATION_NOTICE,
  PUBLISH_TITLE,
  SOON_ADMIN_TEXT,
  taskLabel,
  TEST_CONNECTIONS,
  USERS_TEXT,
  USERS_TITLE,
} from './adminText.ts'

type Load<T> = { status: 'loading' } | { status: 'error'; error: ApiError } | { status: 'ready'; data: T }

/** Lectura de solo consulta al entrar; `attempt` la repite (Reintentar). */
function useLoad<T>(fetcher: (signal: AbortSignal) => Promise<T>, attempt: number): Load<T> {
  const [answer, setAnswer] = useState<{ attempt: number; load: Load<T> }>()
  useEffect(() => {
    const controller = new AbortController()
    fetcher(controller.signal)
      .then((data) => setAnswer({ attempt, load: { status: 'ready', data } }))
      .catch((cause: unknown) => {
        if (!isAbortError(cause)) setAnswer({ attempt, load: { status: 'error', error: toApiError(cause) } })
      })
    return () => controller.abort()
  }, [fetcher, attempt])
  return answer?.attempt === attempt ? answer.load : { status: 'loading' }
}

const loadModels = (signal: AbortSignal) => api.adminModels(signal)
const loadSettings = () => api.settings()

// Administración mínima (T-29; UI.md §3 y §10): solo admin. Probar conexiones, modelos por tarea y modo de
// publicación, de solo lectura; usuarios, documentos e historial, «disponible pronto».
export function AdminScreen() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>{ADMIN_TITLE}</h1>
        <p className={styles.subtitle}>{ADMIN_SUBTITLE}</p>
      </header>
      <div className={styles.grid}>
        <ConnectionsCard />
        <ModelsCard />
        <PublishModeCard />
        <SoonCard />
      </div>
      <p className={styles.footer}>{ADMIN_FOOTER}</p>
    </div>
  )
}

type ConnectionsState =
  | { status: 'idle' }
  | { status: 'testing'; previous?: ConnectionCheckOut[] }
  | { status: 'ready'; checks: ConnectionCheckOut[] }
  | { status: 'error'; error: ApiError; attempt: number; previous?: ConnectionCheckOut[] }

/** No se prueba al entrar: la prueba llama a servicios externos y admite una cada 10 s. */
function ConnectionsCard() {
  const [state, setState] = useState<ConnectionsState>({ status: 'idle' })
  const previous = state.status === 'ready' ? state.checks : state.status === 'idle' ? undefined : state.previous
  const testing = state.status === 'testing'

  const test = () => {
    if (testing) return
    setState({ status: 'testing', previous })
    api
      .adminConnectionsTest()
      .then((result) => setState({ status: 'ready', checks: result.checks }))
      .catch((cause: unknown) =>
        setState((current) => ({
          status: 'error',
          error: toApiError(cause),
          attempt: (current.status === 'error' ? current.attempt : 0) + 1,
          previous,
        })),
      )
  }

  const canRetry = state.status === 'error' && state.error.code !== 'forbidden'

  return (
    <section className={styles.card} aria-labelledby="admin-connections">
      <div className={styles.cardHead}>
        <h2 id="admin-connections" className={styles.cardTitle}>
          {CONNECTIONS_TITLE}
        </h2>
      </div>
      {state.status === 'error' && (
        <ErrorCard key={state.attempt} error={state.error} onAction={canRetry ? test : undefined} />
      )}
      {previous ? (
        <ul className={styles.checks} aria-busy={testing}>
          {previous.map((check) => (
            <ConnectionRow key={check.service} check={check} />
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>{testing ? CONNECTIONS_TESTING : CONNECTIONS_IDLE}</p>
      )}
      <p className="visually-hidden" role="status">
        {testing ? CONNECTIONS_TESTING : ''}
      </p>
      {/* Con un 429, el botón de la tarjeta de error lleva la cuenta atrás; este queda oculto hasta que acabe. */}
      {state.status !== 'error' && (
        <div className={styles.cardActions}>
          <Button size="md" variant="secondary" icon="model" onClick={test} disabled={testing}>
            {testing ? CONNECTIONS_TESTING : TEST_CONNECTIONS}
          </Button>
        </div>
      )}
    </section>
  )
}

function ConnectionRow({ check }: { check: ConnectionCheckOut }) {
  return (
    <li className={styles.check}>
      <span className={styles.dot} data-ok={check.ok ? '' : undefined} aria-hidden="true" />
      <span className={styles.service}>{check.service}</span>
      <Badge tone={check.ok ? 'success' : 'warning'}>{check.ok ? CONNECTION_OK : CONNECTION_FAILED}</Badge>
      {/* `detail` llega de la API sin secretos; se pinta como texto, nunca como HTML. */}
      <span className={styles.detail}>{check.detail}</span>
      <span className={`${styles.duration} tabular-nums`}>{durationLabel(check.duration_ms)}</span>
    </li>
  )
}

function ModelsCard() {
  const [attempt, setAttempt] = useState(0)
  const load = useLoad<AdminModelsOut>(loadModels, attempt)
  return (
    <section className={styles.card} aria-labelledby="admin-models">
      <div className={styles.cardHead}>
        <h2 id="admin-models" className={styles.cardTitle}>
          {MODELS_TITLE}
        </h2>
        <p className={styles.muted}>{MODELS_NOTE}</p>
      </div>
      {load.status === 'loading' && (
        <div role="status" aria-label="Cargando los modelos">
          <Skeleton lines={4} />
        </div>
      )}
      {load.status === 'error' && (
        <ErrorCard
          key={attempt}
          error={load.error}
          onAction={load.error.code === 'forbidden' ? undefined : () => setAttempt((n) => n + 1)}
        />
      )}
      {load.status === 'ready' && <ModelsTable models={load.data} />}
    </section>
  )
}

function ModelCell({ model }: { model: AdminModelOut }) {
  return (
    <>
      <span className={styles.model}>{modelName(model)}</span>
      <span className={styles.host}>{model.host}</span>
    </>
  )
}

function ModelsTable({ models }: { models: AdminModelsOut }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Tarea</th>
            <th scope="col">Principal</th>
            <th scope="col">Respaldo</th>
          </tr>
        </thead>
        <tbody>
          {models.tasks.map(({ task, chain, override }) => {
            const [main, ...fallback] = chain
            return (
              <tr key={task}>
                <th scope="row">
                  {taskLabel(task)}
                  {override && (
                    <span className={styles.override}>
                      <Badge tone="info">Esta sesión usa {modelName(override)}</Badge>
                    </span>
                  )}
                </th>
                <td>{main && <ModelCell model={main} />}</td>
                <td>
                  {fallback.length === 0 ? (
                    <span className={styles.muted}>{NO_FALLBACK}</span>
                  ) : (
                    fallback.map((model) => (
                      <div key={`${model.provider}/${model.model}`} className={styles.fallback}>
                        <ModelCell model={model} />
                      </div>
                    ))
                  )}
                </td>
              </tr>
            )
          })}
          <tr className={styles.embeddings}>
            <th scope="row">{EMBEDDINGS_LABEL}</th>
            <td colSpan={2}>
              <ModelCell model={models.embeddings} />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function PublishModeCard() {
  const [attempt, setAttempt] = useState(0)
  const load = useLoad<SettingsOut>(loadSettings, attempt)
  return (
    <section className={styles.card} aria-labelledby="admin-publish">
      <div className={styles.cardHead}>
        <h2 id="admin-publish" className={styles.cardTitle}>
          {PUBLISH_TITLE}
        </h2>
      </div>
      {load.status === 'loading' && (
        <div role="status" aria-label="Cargando el modo de publicación">
          <Skeleton lines={2} />
        </div>
      )}
      {load.status === 'error' && (
        <ErrorCard key={attempt} error={load.error} onAction={() => setAttempt((n) => n + 1)} />
      )}
      {load.status === 'ready' && (
        <>
          <p className={styles.mode}>
            <Badge tone={load.data.publish_mode === 'simulation' ? 'warning' : 'success'} size="md">
              {PUBLISH_MODE_LABELS[load.data.publish_mode]}
            </Badge>
          </p>
          {load.data.publish_mode === 'simulation' ? (
            <Notice>{PUBLISH_SIMULATION_NOTICE}</Notice>
          ) : (
            <p className={styles.muted}>{PUBLISH_LIVE_TEXT}</p>
          )}
        </>
      )}
    </section>
  )
}

function SoonCard() {
  return (
    <section className={`${styles.card} ${styles.soon}`} aria-labelledby="admin-soon">
      <h2 id="admin-soon" className={styles.cardTitle}>
        {DOCUMENTS_TITLE}
      </h2>
      <p className={styles.muted}>{DOCUMENTS_TEXT}</p>
      <div className={styles.cardActions}>
        <SoonButton label="Elegir archivos" note={SOON_ADMIN_TEXT} />
      </div>
      <h3 className={styles.soonSubtitle}>{USERS_TITLE}</h3>
      <p className={styles.muted}>{USERS_TEXT}</p>
      <div className={styles.cardActions}>
        <SoonButton label="Gestionar usuarios" note={SOON_ADMIN_TEXT} />
      </div>
      <p className={styles.soonNote}>{SOON_ADMIN_TEXT}</p>
    </section>
  )
}
