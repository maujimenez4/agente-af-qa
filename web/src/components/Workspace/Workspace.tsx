import { createContext, useContext, useId, useState, type ReactNode } from 'react'
import { Button } from '../Button/index.ts'
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
  /** Panel abierto o plegado, si lo controla la pantalla (p. ej. «Abrir en el panel» lo vuelve a abrir). */
  panelOpen?: boolean
  onPanelOpenChange?: (open: boolean) => void
}

// Estado del panel derecho: lo pliega el botón de la cabecera de la conversación.
const PanelContext = createContext<{ id: string; open: boolean } | null>(null)

// Pantalla de trabajo (UI.md §2): cabecera con la Q de fase, conversación, compositor y panel derecho.
// El botón para plegar el panel va siempre en el mismo sitio, arriba a la derecha y con texto
// (DESIGN-DECISIONS.md §4 bis): plegado, el panel se oculta sin desmontarse y conserva su estado.
export function Workspace({ title, phase, phaseName, children, composer, panel, panelOpen, onPanelOpenChange }: WorkspaceProps) {
  const [ownOpen, setOwnOpen] = useState(true)
  const open = panelOpen ?? ownOpen
  const setOpen = (next: boolean) => {
    setOwnOpen(next)
    onPanelOpenChange?.(next)
  }
  const panelId = useId()
  return (
    <div className={styles.workspace}>
      <section className={styles.conversation} aria-label="Conversación">
        <header className={styles.header}>
          <h1 className={styles.title}>{title}</h1>
          <PhaseQ phase={phase} name={phaseName} />
          {panel && (
            <Button
              variant="secondary"
              size="sm"
              icon="panelRight"
              aria-controls={panelId}
              onClick={() => setOpen(!open)}
            >
              <span className={styles.toggleLabel}>{open ? 'Ocultar el panel' : 'Mostrar el panel'}</span>
            </Button>
          )}
        </header>
        <div className={styles.scroll}>
          <div className={styles.column}>{children}</div>
        </div>
        {composer && <div className={styles.composer}>{composer}</div>}
      </section>
      {panel && <PanelContext.Provider value={{ id: panelId, open }}>{panel}</PanelContext.Provider>}
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

// Panel derecho (420/480/540 px, decisión 10) que se puede plegar (UI.md §2) desde la cabecera del Workspace.
export function SidePanel({ title, subtitle, headerActions, toolbar, size = 'sm', children, footer }: SidePanelProps) {
  const control = useContext(PanelContext)
  const titleId = useId()

  return (
    <aside id={control?.id} hidden={control ? !control.open : undefined} className={styles.panel} data-size={size} aria-labelledby={titleId}>
      <div className={styles.panelHeader}>
        <div className={styles.panelHeading}>
          <h2 id={titleId} className={styles.panelTitle}>
            {title}
          </h2>
          {subtitle && <span className={styles.panelSubtitle}>{subtitle}</span>}
        </div>
        {headerActions}
      </div>
      {toolbar}
      <div className={styles.panelBody}>
        {children}
      </div>
      {footer && <div className={styles.panelFooter}>{footer}</div>}
    </aside>
  )
}
