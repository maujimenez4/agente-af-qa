import { useId, type ReactNode } from 'react'
import { Button } from '../../components/Button/index.ts'
import styles from './Editor.module.css'
import type { EditIssue } from './storyValidation.ts'

// Piezas comunes de Editar a mano (HU y suite, PA-158): campo con su error o aviso asociado, grupo con título y las
// herramientas de un elemento de una lista (subir, bajar, quitar). Todo es texto: nada se pinta como HTML.

export interface FieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  issue?: EditIssue
  /** Un aviso no bloquea: no marca el campo como inválido y va en ámbar. */
  warning?: boolean
  hint?: string
  multiline?: boolean
  rows?: number
}

export function Field({ label, value, onChange, issue, warning = false, hint, multiline = false, rows = 2 }: FieldProps) {
  const id = useId()
  const describedBy = [hint ? `${id}-hint` : '', issue ? `${id}-issue` : ''].filter(Boolean).join(' ') || undefined
  const common = {
    id,
    value,
    className: styles.input,
    'aria-invalid': issue && !warning ? true : undefined,
    'aria-describedby': describedBy,
  } as const
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {hint && (
        <span id={`${id}-hint`} className={styles.hint}>
          {hint}
        </span>
      )}
      {multiline ? (
        <textarea {...common} rows={rows} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input {...common} type="text" onChange={(event) => onChange(event.target.value)} />
      )}
      {issue && (
        <span id={`${id}-issue`} className={warning ? styles.warning : styles.issue}>
          {issue.message}
        </span>
      )}
    </div>
  )
}

export function Group({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  const id = useId()
  return (
    <section className={styles.group} aria-labelledby={id}>
      <h3 id={id} className={styles.groupTitle}>
        {title}
      </h3>
      {children}
      {actions}
    </section>
  )
}

export function ItemTools({ label, index, count, onMove, onRemove }: { label: string; index: number; count: number; onMove: (step: -1 | 1) => void; onRemove: () => void }) {
  return (
    <span className={styles.tools}>
      <Button variant="ghost" size="sm" disabled={index === 0} aria-label={`Subir ${label}`} onClick={() => onMove(-1)}>
        Subir
      </Button>
      <Button variant="ghost" size="sm" disabled={index === count - 1} aria-label={`Bajar ${label}`} onClick={() => onMove(1)}>
        Bajar
      </Button>
      <Button variant="ghost" size="sm" aria-label={`Quitar ${label}`} onClick={onRemove}>
        Quitar
      </Button>
    </span>
  )
}
