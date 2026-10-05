import { useEffect, useState } from 'react'
import {
  LoadingQ,
  loadingProgress,
  PhaseQ,
  QLogo,
  ResultQ,
  TypewriterText,
  TypingIndicator,
  type Phase,
  type StepEvent,
} from '../components/QMark/index.ts'
import { DemoButton } from './DemoButton.tsx'
import styles from './Catalog.module.css'

const PHASES: Phase[] = [1, 2, 3, 4]

// Secuencia de eventos SSE sintética para ver la Q de carga (1 s por paso, `generate` dura 4 s).
const SCRIPT: ReadonlyArray<{ at: number; event?: StepEvent; reviewReady?: boolean }> = [
  { at: 600, event: { node: 'load_origin', state: 'done' } },
  { at: 1600, event: { node: 'retrieve_context', state: 'done' } },
  { at: 1700, event: { node: 'generate', state: 'running' } },
  { at: 5700, event: { node: 'generate', state: 'done' } },
  { at: 6400, reviewReady: true },
]

const REPLY =
  'Versión 2 lista. Cambió el CA-03 y añadió la RN-02. Afecta también a DEMO-2: la reserva digital comparte el límite de préstamos.'

function LoadingDemo() {
  const [run, setRun] = useState(0)
  const [events, setEvents] = useState<StepEvent[]>([])
  const [reviewReady, setReviewReady] = useState(false)

  useEffect(() => {
    if (run === 0) return
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

  const progress = loadingProgress(events, reviewReady)
  const last = events.at(-1)

  return (
    <div className={styles.demo}>
      <LoadingQ done={progress.done} running={progress.running} />
      <div className={styles.demoText}>
        <span className="tabular-nums">
          {progress.done} de 4 cuartos{progress.running ? ' · generate en curso' : ''}
        </span>
        <span className={styles.muted}>
          {reviewReady ? 'review_ready' : last ? `progress: ${last.node} → ${last.state}` : 'Sin eventos'}
        </span>
        <DemoButton
          onClick={() => {
            setEvents([])
            setReviewReady(false)
            setRun((current) => current + 1)
          }}
        >
          Simular generación
        </DemoButton>
      </div>
    </div>
  )
}

function TypingDemo() {
  const [round, setRound] = useState(1)
  const [typing, setTyping] = useState(true)

  return (
    <div className={styles.section}>
      {typing && <TypingIndicator />}
      <p className={styles.reply}>
        <TypewriterText key={round} text={REPLY} onDone={() => setTyping(false)} />
      </p>
      <div>
        <DemoButton
          onClick={() => {
            setTyping(true)
            setRound((current) => current + 1)
          }}
        >
          Volver a escribir
        </DemoButton>
      </div>
    </div>
  )
}

export function QDemo() {
  const [phase, setPhase] = useState<Phase>(1)

  return (
    <section className={styles.section} aria-labelledby="q">
      <h2 id="q" className={styles.sectionTitle}>
        La Q animada
      </h2>
      <p className={styles.muted}>
        Prueba también con «reducir movimiento» activado en el sistema: ninguna Q debe verse llena por error.
      </p>

      <h3 className={styles.groupTitle}>Logotipo</h3>
      <div className={styles.row}>
        <QLogo size={34} label="Agente AF y QA" />
        <QLogo size={30} />
        <QLogo size={16} />
      </div>

      <h3 className={styles.groupTitle}>Q de fase (cabecera)</h3>
      <div className={styles.row}>
        <PhaseQ phase={phase} />
        <div className={styles.row} role="group" aria-label="Elegir fase">
          {PHASES.map((value) => (
            <DemoButton
              key={value}
              pressed={phase === value}
              onClick={() => setPhase(value)}
            >
              Fase {value}
            </DemoButton>
          ))}
        </div>
      </div>

      <h3 className={styles.groupTitle}>Q de carga por procesos (eventos SSE simulados)</h3>
      <LoadingDemo />

      <h3 className={styles.groupTitle}>Q del resultado</h3>
      <div className={styles.row}>
        {(['published', 'partial', 'simulated'] as const).map((outcome) => (
          <div key={outcome} className={styles.demo}>
            <ResultQ outcome={outcome} />
            <span className={styles.muted}>{outcome}</span>
          </div>
        ))}
      </div>

      <h3 className={styles.groupTitle}>Escribiendo la respuesta</h3>
      <TypingDemo />
    </section>
  )
}
