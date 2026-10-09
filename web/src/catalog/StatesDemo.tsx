import { useEffect, useState } from 'react'
import { Button } from '../components/Button/index.ts'
import {
  EmptyState,
  ErrorCard,
  LoadingState,
  Notice,
  SIMULATION_NOTICE,
  Skeleton,
  type ApiError,
  type ProgressEvent,
} from '../components/States/index.ts'
import styles from './Catalog.module.css'
import { WRITING_PROPOSAL } from '../text/assistant.ts'

// Eventos SSE sintéticos con los textos de UI.md §4.4.
const SCRIPT: ReadonlyArray<{ at: number; event?: ProgressEvent; reviewReady?: boolean }> = [
  { at: 0, event: { node: 'load_origin', label: 'Cargar el origen', state: 'running' } },
  { at: 500, event: { node: 'load_origin', label: 'Cargar el origen', state: 'done' } },
  { at: 600, event: { node: 'retrieve_context', label: 'Recuperar contexto', state: 'running' } },
  { at: 1600, event: { node: 'retrieve_context', label: 'Recuperar contexto · 5 fuentes y 3.150 tokens', state: 'done' } },
  { at: 1700, event: { node: 'generate', label: 'Generar la versión 1 · ollama · qwen3:4b-instruct', state: 'running' } },
  { at: 5700, event: { node: 'generate', label: 'Generar la versión 1 · ollama · qwen3:4b-instruct', state: 'done' } },
  { at: 6200, reviewReady: true },
]

// Mensajes de ejemplo del contrato (docs/api/openapi.yaml).
const ERRORS: ApiError[] = [
  {
    code: 'rate_limited',
    message:
      'Todos los proveedores de la tarea «generate_story» han alcanzado su límite de uso. Espera unos minutos o elige otro modelo.',
    retry_after: 45,
  },
  { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' },
  { code: 'not_found', message: 'No existe esa conversación o no es tuya.' },
  { code: 'approval_rejected', message: 'La aprobación no corresponde a la versión revisada; empieza de nuevo.' },
  { code: 'unauthenticated', message: 'Inicia sesión para continuar.' },
]

function LoadingDemo() {
  const [run, setRun] = useState(1)
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [reviewReady, setReviewReady] = useState(false)

  useEffect(() => {
    const timers = SCRIPT.map((step) =>
      window.setTimeout(() => {
        if (step.event) {
          const event = step.event
          setEvents((current) => [...current, event])
        }
        if (step.reviewReady) setReviewReady(true)
      }, step.at),
    )
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [run])

  return (
    <div className={styles.section}>
      <LoadingState
        title={reviewReady ? 'Propuesta lista · Versión 1 · 3 cambios frente a Jira' : WRITING_PROPOSAL}
        events={events}
        reviewReady={reviewReady}
      />
      <div>
        <Button
          size="md"
          onClick={() => {
            setEvents([])
            setReviewReady(false)
            setRun((current) => current + 1)
          }}
        >
          Repetir
        </Button>
      </div>
    </div>
  )
}

export function StatesDemo() {
  const [round, setRound] = useState(0)

  return (
    <section className={styles.section} aria-labelledby="estados">
      <h2 id="estados" className={styles.sectionTitle}>
        Estados vacío, cargando y error
      </h2>

      <h3 className={styles.groupTitle}>Aviso del modo de prueba</h3>
      <Notice>{SIMULATION_NOTICE}</Notice>

      <div className={styles.statesGrid}>
        <div className={styles.stateCard}>
          <h3 className={styles.groupTitle}>Vacío</h3>
          <EmptyState onAction={() => undefined} />
        </div>
        <div className={styles.stateCard}>
          <h3 className={styles.groupTitle}>Cargando (eventos SSE simulados)</h3>
          <LoadingDemo />
        </div>
        <div className={styles.stateCard}>
          <h3 className={styles.groupTitle}>Panel mientras se genera</h3>
          <p className={styles.muted}>La propuesta aparece aquí cuando las citas están comprobadas.</p>
          <Skeleton lines={6} />
        </div>
      </div>

      <h3 className={styles.groupTitle}>Errores por código (mensaje de la API tal cual)</h3>
      <div className={styles.statesGrid}>
        {ERRORS.map((error) => (
          <ErrorCard key={`${error.code}-${round}`} error={error} onAction={() => setRound((current) => current + 1)} />
        ))}
        <ErrorCard error={{ code: 'algo_nuevo', message: 'Código que la UI aún no conoce: título genérico.' }} />
      </div>
    </section>
  )
}
