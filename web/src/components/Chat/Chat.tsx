import type { ReactNode } from 'react'
import { Icon, type IconName } from '../Icon/index.ts'
import { QLogo } from '../QMark/index.ts'
import styles from './Chat.module.css'

// Conversación: role="log" (aria-live="polite") anuncia cada mensaje nuevo una sola vez
// (DESIGN-DECISIONS.md §3). Los textos de la API se pintan como texto.
export function ChatLog({ label = 'Conversación', children }: { label?: string; children: ReactNode }) {
  return (
    <ol className={styles.log} role="log" aria-label={label}>
      {children}
    </ol>
  )
}

/** Mensaje de la persona (burbuja a la derecha con forma Q). */
export function UserMessage({ children }: { children: ReactNode }) {
  return (
    <li className={styles.user}>
      <span className="visually-hidden">Tú: </span>
      {children}
    </li>
  )
}

/** Mensaje del asistente, con su avatar de la Q. */
export function AssistantMessage({ children, animate = false }: { children: ReactNode; animate?: boolean }) {
  return (
    <li className={`${styles.assistant} ${animate ? styles.rise : ''}`}>
      <span className={styles.avatar} aria-hidden="true">
        <QLogo size={16} />
      </span>
      <div className={styles.body}>
        <span className="visually-hidden">Asistente: </span>
        {children}
      </div>
    </li>
  )
}

export interface FoundIssueProps {
  icon?: IconName
  title: string
  detail?: string
  actions?: ReactNode
}

/** HU encontrada o reconocida en Jira (UI.md §4.3), con sus acciones. */
export function FoundIssue({ icon = 'work', title, detail, actions }: FoundIssueProps) {
  return (
    <div className={styles.found}>
      <Icon name={icon} size={22} />
      <span className={styles.foundText}>
        <b className={styles.foundTitle}>{title}</b>
        {detail && <span className={styles.muted}>{detail}</span>}
      </span>
      {actions && <span className={styles.actions}>{actions}</span>}
    </div>
  )
}

/** «Operación fijada» (UI.md §4.3): no cambia durante la conversación. */
export function FixedOperation({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={styles.fixed}>
      <Icon name="lock" className={styles.fixedIcon} />
      <span className={styles.fixedText}>
        <b>{title}</b>
        <span className={styles.muted}>{children}</span>
      </span>
    </div>
  )
}

/** Evento del sistema en la conversación (lienzo .event): «Generar propuesta · evolucionar DEMO-3». */
export function ChatEvent({ icon = 'lock', children }: { icon?: IconName; children: ReactNode }) {
  return (
    <li className={styles.event}>
      <Icon name={icon} size={16} />
      <span>{children}</span>
    </li>
  )
}
