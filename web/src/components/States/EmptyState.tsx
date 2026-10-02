import { Button } from '../Button/index.ts'
import styles from './States.module.css'

export interface EmptyStateProps {
  title?: string
  text?: string
  actionLabel?: string
  onAction?: () => void
}

// Estado vacío. Por defecto, el panel sin propuesta de UI.md §7 (no el texto del lienzo, decisión §2).
export function EmptyState({
  title = 'Aún no hay propuesta',
  text = 'Elige un origen para generar la primera versión de la HU.',
  actionLabel = 'Elegir un origen',
  onAction,
}: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      <h2 className={styles.title}>{title}</h2>
      <p className={styles.text}>{text}</p>
      {onAction && (
        <Button size="md" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
