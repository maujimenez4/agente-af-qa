import { useId, useState, type ReactNode } from 'react'
import { IconButton } from '../Button/index.ts'
import { PhaseQ, type Phase } from '../QMark/index.ts'
import styles from './Workspace.module.css'

export interface WorkspaceProps {
  /** Título de la conversación (cabecera, H1). */
  title: string
  phase: Phase
  /** Otro nombre para la fase (p. ej. «Aprobada»). */
  phaseName?: string
  /** Mensajes de la conversación. */
  children: ReactNode
  composer?: ReactNode
  panel?: ReactNode
}

// Pantalla de trabajo (UI.md §2): cabecera con la Q de fase, conversación, compositor y panel derecho.
export function Workspace({ title, phase, phaseName, children, composer, panel }: WorkspaceProps) {
  return (
    <div className={styles.workspace}>
      <section className={styles.conversation} aria-label="Conversación">
        <header className={styles.header}>
          <h1 className={styles.title}>{title}</h1>
          <PhaseQ phase={phase} name={phaseName} />
        </header>
        <div className={styles.scroll}>
          <div className={styles.column}>{children}</div>
        </div>
        {composer && <div className={styles.composer}>{composer}</div>}
      </section>
      {panel}
    </div>
  )
}

export interface SidePanelProps {
  title: string
  /** Línea bajo el título («Evolución de DEMO-3 · en revisión»). */
  subtitle?: string
  /** Controles a la derecha de la cabecera (p. ej. las versiones). */
  headerActions?: ReactNode
  /** Contenido fijo entre la cabecera y el cuerpo (p. ej. las pestañas). */
  toolbar?: ReactNode
  size?: 'sm' | 'md' | 'lg'
  children: ReactNode
  footer?: ReactNode
}

// Panel derecho (420/480/540 px, decisión 10) que se puede plegar (UI.md §2).
export function SidePanel({ title, subtitle, headerActions, toolbar, size = 'sm', children, footer }: SidePanelProps) {
  const [open, setOpen] = useState(true)
  const titleId = useId()
  const bodyId = useId()

  if (!open) {
    return (
      <div className={styles.collapsed}>
        <IconButton icon="panelRight" label={`Mostrar el panel «${title}»`} aria-expanded={false} onClick={() => setOpen(true)} />
      </div>
    )
  }

  return (
    <aside className={styles.panel} data-size={size} aria-labelledby={titleId}>
      <div className={styles.panelHeader}>
        <div className={styles.panelHeading}>
          <h2 id={titleId} className={styles.panelTitle}>
            {title}
          </h2>
          {subtitle && <span className={styles.panelSubtitle}>{subtitle}</span>}
        </div>
        {headerActions}
        <IconButton icon="panelRight" label="Plegar panel" aria-expanded aria-controls={bodyId} onClick={() => setOpen(false)} />
      </div>
      {toolbar}
      <div id={bodyId} className={styles.panelBody}>
        {children}
      </div>
      {footer && <div className={styles.panelFooter}>{footer}</div>}
    </aside>
  )
}
