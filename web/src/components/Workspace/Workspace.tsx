import { createContext, useContext, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react'
import { useLayer } from '../../hooks/useLayer.ts'
import { Button } from '../Button/index.ts'
import { PhaseQ, type Phase } from '../QMark/index.ts'
import styles from './Workspace.module.css'

export interface WorkspaceProps {
  /** Título de la conversación (cabecera, H1). */
  title: string
  /** Fase de la Q; sin ella (flujos sin fases, como Revisar la calidad), la cabecera muestra solo `phaseName` como texto. */
  phase?: Phase
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

/** PA-335: por debajo de este ancho del área de trabajo (conversación 360 + panel 320), el panel pasa a capa. */
export const PANEL_LAYER_BELOW = 680

// Estado del panel derecho: lo pliega el botón de la cabecera de la conversación. En capa (PA-335), además,
// la referencia y el teclado del diálogo.
const PanelContext = createContext<{
  id: string
  open: boolean
  layer: boolean
  ref: RefObject<HTMLElement | null>
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void
} | null>(null)

/** Ancho del elemento (0 sin `ResizeObserver`, como en jsdom: entonces nunca hay capa). */
function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(entry?.contentRect.width ?? 0))
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
  return width
}

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

  // PA-335: si el área no da para la conversación y el panel, el panel se abre como capa sobre la conversación
  // con el mismo botón. Al pasar a capa empieza plegado, para que se vea la conversación.
  const workspaceRef = useRef<HTMLDivElement>(null)
  const width = useWidth(workspaceRef)
  const layer = Boolean(panel) && width > 0 && width < PANEL_LAYER_BELOW
  // Al salir de la capa (ventana más ancha), el panel vuelve a como estaba antes de entrar.
  const [layerSeen, setLayerSeen] = useState<{ layer: boolean; openBefore: boolean }>({ layer: false, openBefore: open })
  if (layer !== layerSeen.layer) {
    setLayerSeen({ layer, openBefore: layer ? open : layerSeen.openBefore })
    if (layer && open) setOpen(false)
    if (!layer && layerSeen.openBefore !== open) setOpen(layerSeen.openBefore)
  }
  const panelRef = useRef<HTMLElement>(null)
  const onPanelKeyDown = useLayer({
    open: layer && open,
    layer: panelRef,
    // El botón de la cabecera (`Button` no reenvía `ref`): el que controla este panel.
    opener: () => workspaceRef.current?.querySelector<HTMLElement>(`[aria-controls="${CSS.escape(panelId)}"]`),
    onClose: () => setOpen(false),
  })

  return (
    <div ref={workspaceRef} className={styles.workspace} data-layer={layer ? '' : undefined}>
      <section className={styles.conversation} aria-label="Conversación">
        <header className={styles.header}>
          <h1 className={styles.title}>{title}</h1>
          {phase ? <PhaseQ phase={phase} name={phaseName} /> : phaseName && <span className={styles.headerNote}>{phaseName}</span>}
          {panel && (
            <Button
              variant="secondary"
              size="sm"
              icon="panelRight"
              aria-controls={panelId}
              aria-expanded={open}
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
      {/* Velo de la capa: un clic fuera del panel lo pliega (con el teclado, Esc). */}
      {panel && layer && open && <div className={styles.layerBackdrop} aria-hidden="true" onClick={() => setOpen(false)} />}
      {panel && (
        <PanelContext.Provider value={{ id: panelId, open, layer, ref: panelRef, onKeyDown: onPanelKeyDown }}>{panel}</PanelContext.Provider>
      )}
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
    // En capa, el panel es un diálogo: escucha Esc y Tab (patrón dialog de WAI-ARIA, como Modal).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <aside
      ref={control?.ref}
      id={control?.id}
      hidden={control ? !control.open : undefined}
      className={styles.panel}
      data-size={size}
      role={control?.layer ? 'dialog' : undefined}
      aria-modal={control?.layer ? 'true' : undefined}
      // En capa, el propio panel recibe el foco si no tiene controles (p. ej. el historial del recibo).
      tabIndex={control?.layer ? -1 : undefined}
      aria-labelledby={titleId}
      onKeyDown={control?.onKeyDown}
    >
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
