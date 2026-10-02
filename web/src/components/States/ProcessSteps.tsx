import { Icon } from '../Icon/index.ts'
import type { ProgressEvent } from './progressSteps.ts'
import styles from './States.module.css'

const STATE_TEXT = { pending: 'pendiente', running: 'en curso', done: 'hecho' } as const

// Lista de procesos de la generación (UI.md §4.4): hecho, en curso (aria-current="step") y pendiente.
export function ProcessSteps({ steps }: { steps: readonly ProgressEvent[] }) {
  return (
    <ol className={styles.steps}>
      {steps.map((step, index) => (
        <li
          key={step.node}
          className={styles.step}
          data-state={step.state}
          aria-current={step.state === 'running' ? 'step' : undefined}
        >
          <span className={styles.mark} aria-hidden="true">
            {step.state === 'done' ? <Icon name="done" size={14} /> : index + 1}
          </span>
          <span>{step.label}</span>
          <span className="visually-hidden">({STATE_TEXT[step.state]})</span>
        </li>
      ))}
    </ol>
  )
}
