import type { ReactNode } from 'react'
import { Icon } from '../Icon/index.ts'
import styles from './States.module.css'

// Aviso fijo en ámbar (UI.md §2: modo de prueba). Es una nota, no una alerta.
export function Notice({ children }: { children: ReactNode }) {
  return (
    <p className={styles.notice} role="note">
      <Icon name="warning" />
      <span>{children}</span>
    </p>
  )
}
