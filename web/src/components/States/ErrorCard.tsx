import { useEffect, useState } from 'react'
import { Button } from '../Button/index.ts'
import { Icon } from '../Icon/index.ts'
import { ACTION_LABELS, presentError, retryDelay, type ApiError } from './errorPresentation.ts'
import styles from './States.module.css'

export interface ErrorCardProps {
  error: ApiError
  /** Acción de la tarjeta (reintentar, iniciar sesión…). Sin ella, no hay botón. Para un error nuevo, cambia la `key`. */
  onAction?: () => void
}

// Tarjeta de error (UI.md §7): título por `code` y el mensaje de la API TAL CUAL, como texto.
export function ErrorCard({ error, onAction }: ErrorCardProps) {
  const presentation = presentError(error)
  const waitFor = presentation.action === 'retry' ? retryDelay(error) : 0
  const [remaining, setRemaining] = useState(waitFor)

  useEffect(() => {
    if (waitFor === 0) return
    const timer = window.setInterval(() => {
      setRemaining((current) => {
        const next = Math.max(current - 1, 0)
        if (next === 0) window.clearInterval(timer)
        return next
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [waitFor])

  const actionLabel = presentation.action ? ACTION_LABELS[presentation.action] : undefined

  return (
    <div className={styles.error} role="alert" data-tone={presentation.tone}>
      <h2 className={styles.errorTitle}>
        <Icon name="warning" />
        {presentation.title}
      </h2>
      <p className={styles.errorMessage}>{error.message}</p>
      {waitFor > 0 && <p className="visually-hidden">Podrás reintentar dentro de {waitFor} segundos.</p>}
      {remaining > 0 && (
        // Visual: la alerta no se vuelve a anunciar cada segundo; el aviso para lectores es la frase fija de arriba.
        <p className={`${styles.errorNote} tabular-nums`} aria-hidden="true">
          Reintento disponible en {remaining} s
        </p>
      )}
      {onAction && actionLabel && (
        <div className={styles.errorActions}>
          <Button size="md" variant={presentation.tone === 'error' ? 'danger' : 'secondary'} onClick={onAction} disabled={remaining > 0}>
            {actionLabel}
          </Button>
        </div>
      )}
    </div>
  )
}
