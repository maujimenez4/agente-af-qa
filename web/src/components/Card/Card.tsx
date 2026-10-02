import { useId, type ReactNode } from 'react'
import { Icon, type IconName } from '../Icon/index.ts'
import styles from './Card.module.css'

export interface CardProps {
  title?: string
  description?: string
  /** Nivel del título dentro de la página. */
  headingLevel?: 2 | 3
  children?: ReactNode
}

// Tarjeta base (lienzo .card): superficie blanca, borde suave y radio de 16 px.
export function Card({ title, description, headingLevel = 2, children }: CardProps) {
  const titleId = useId()
  const Heading = headingLevel === 2 ? 'h2' : 'h3'
  return (
    <section className={styles.card} aria-labelledby={title ? titleId : undefined}>
      {title && (
        <Heading id={titleId} className={styles.title}>
          {title}
        </Heading>
      )}
      {description && <p className={styles.description}>{description}</p>}
      {children}
    </section>
  )
}

export interface FlowCardProps {
  label: string
  hint: string
  icon: IconName
  selected: boolean
  onSelect: () => void
  /** El rol no puede usar este flujo: se muestra desactivada con su ayuda (UI.md §3). */
  disabledHint?: string
}

// Tarjeta de flujo del inicio (UI.md §4.1): seleccionable con aria-pressed; desactivada con aria-disabled.
// El nombre accesible es solo la etiqueta; la ayuda va como descripción (aria-describedby).
export function FlowCard({ label, hint, icon, selected, onSelect, disabledHint }: FlowCardProps) {
  const disabled = disabledHint !== undefined
  const hintId = useId()
  return (
    <button
      type="button"
      className={styles.flow}
      aria-pressed={disabled ? false : selected}
      aria-disabled={disabled ? true : undefined}
      aria-describedby={hintId}
      onClick={disabled ? undefined : onSelect}
    >
      <Icon name={icon} className={styles.flowIcon} />
      <span className={styles.flowText}>
        <span className={styles.flowLabel}>{label}</span>
        <span id={hintId} className={styles.flowHint} aria-hidden="true">
          {disabled ? disabledHint : hint}
        </span>
      </span>
    </button>
  )
}
