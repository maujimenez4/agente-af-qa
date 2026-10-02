import type { ReactNode } from 'react'
import { QLogo } from '../components/QMark/index.ts'
import styles from './AppShell.module.css'

export interface SoonScreenProps {
  title: string
  text: string
  /** Contenido debajo del texto (p. ej. la tarjeta del error). */
  children?: ReactNode
}

// Pantalla «Disponible pronto» (DESIGN-DECISIONS.md §4 bis): lo que aún no está en el contrato.
export function SoonScreen({ title, text, children }: SoonScreenProps) {
  return (
    <div className={styles.centered}>
      <section className={styles.soon} aria-labelledby="soon-title">
        <QLogo size={40} />
        <h1 id="soon-title" className={styles.soonTitle}>
          {title}
        </h1>
        <p className={styles.soonText}>{text}</p>
        {children}
      </section>
    </div>
  )
}
