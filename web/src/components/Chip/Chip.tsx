import type { ButtonHTMLAttributes, ReactNode } from 'react'
import styles from './Chip.module.css'

export type ChipVariant = 'suggestion' | 'recent'

export interface ChipProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: ChipVariant
  /** Clave de Jira que va delante en negrita (recientes: «DEMO-3 · Renovar…»). */
  issueKey?: string
  children: ReactNode
}

// Píldora pulsable: sugerencias del chat y recientes del proyecto (UI.md §4.1 y §4.5).
export function Chip({ variant = 'suggestion', issueKey, className, type = 'button', children, ...rest }: ChipProps) {
  return (
    <button type={type} className={[styles.chip, styles[variant], className].filter(Boolean).join(' ')} {...rest}>
      {issueKey && (
        <>
          <span className={styles.key}>{issueKey}</span>{' '}
        </>
      )}
      <span>{children}</span>
    </button>
  )
}
