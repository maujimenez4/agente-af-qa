import { LoadingQ, loadingProgress } from '../QMark/index.ts'
import { ProcessSteps } from './ProcessSteps.tsx'
import { latestSteps, type ProgressEvent } from './progressSteps.ts'
import styles from './States.module.css'

export interface LoadingStateProps {
  /** «Generando la propuesta…», «Generando la suite…». */
  title: string
  /** Eventos `progress` recibidos por SSE, en orden. */
  events: readonly ProgressEvent[]
  /** Llegó `review_ready`: la Q se completa. */
  reviewReady?: boolean
  /** En curso sin eventos de pasos (p. ej. la revisión de calidad, que no tiene SSE): la Q late (PA-427). */
  running?: boolean
}

// Estado «cargando» de la generación (UI.md §4.4 y §6.2): Q por procesos y lista de pasos.
export function LoadingState({ title, events, reviewReady = false, running = false }: LoadingStateProps) {
  const progress = loadingProgress(events, reviewReady)
  return (
    <div className={styles.loading} role="status" aria-busy={!reviewReady}>
      <LoadingQ done={progress.done} running={progress.running || (running && !reviewReady)} />
      <h2 className={styles.title}>{title}</h2>
      <ProcessSteps steps={latestSteps(events)} />
    </div>
  )
}
