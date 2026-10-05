import { useEffect, useId, useRef, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { IconButton } from '../Button/index.ts'
import { Icon, type IconName } from '../Icon/index.ts'
import styles from './Composer.module.css'

export interface ComposerProps {
  /** Texto de ayuda; también es la etiqueta (oculta) del cuadro de texto. */
  placeholder: string
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  /** Si se puede enviar ya (texto escrito u origen elegido). */
  canSubmit: boolean
  /** Desactivado mientras se genera (UI.md §4.4: «Espera a la propuesta para pedir cambios»). */
  disabled?: boolean
  /** Algo fijado encima del texto (p. ej. el origen elegido en Jira). */
  attachment?: ReactNode
  /** Herramientas a la izquierda del botón de enviar. */
  tools?: ReactNode
  submitLabel?: string
  /** Mientras se genera: el botón de enviar pasa a «Detener la generación» (lienzo Mixta 2b, PA-314). */
  onStop?: () => void
  /** Ya se pidió detener: el botón queda desactivado («Deteniendo…»). */
  stopping?: boolean
}

/** Ayuda de teclado: visible bajo el cuadro y parte de su nombre accesible. */
export const COMPOSER_KEYS_HINT = 'Intro para enviar, Mayús+Intro para nueva línea'

// Si nada cambia tras un envío (p. ej. falló y el texto sigue), Intro vuelve a enviar pasado este tiempo.
const RESEND_AFTER_MS = 1000

// Compositor del chat (UI.md §2): cuadro de texto, herramientas y enviar. Intro (o Ctrl/Cmd + Intro) envía;
// Mayús + Intro hace un salto de línea.
export function Composer({
  placeholder,
  value,
  onChange,
  onSubmit,
  canSubmit,
  disabled = false,
  attachment,
  tools,
  submitLabel = 'Continuar',
  onStop,
  stopping = false,
}: ComposerProps) {
  const id = useId()
  const ready = canSubmit && !disabled
  // Un envío por pulsación: Intro repetido antes de que la pantalla reaccione no envía dos veces.
  const sent = useRef(false)
  useEffect(() => {
    sent.current = false
  }, [value, disabled, canSubmit])

  const send = () => {
    if (!ready || sent.current) return
    sent.current = true
    window.setTimeout(() => {
      sent.current = false
    }, RESEND_AFTER_MS)
    onSubmit()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    send()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.altKey) return // Mayús + Intro: salto de línea.
    // Composición en curso (acentos, IME): Intro confirma el carácter, no envía.
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    event.preventDefault()
    // Generando (con «Detener») no se envía nada; solo espacios tampoco.
    if (onStop || event.repeat || !value.trim()) return
    send()
  }

  return (
    <form className={styles.composer} onSubmit={submit} data-disabled={disabled ? '' : undefined}>
      {attachment}
      <label htmlFor={id} className="visually-hidden">
        {disabled ? placeholder : `${placeholder} (${COMPOSER_KEYS_HINT})`}
      </label>
      <textarea
        id={id}
        className={styles.textarea}
        rows={3}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className={styles.toolbar}>
        {tools}
        <span className={styles.spacer} />
        {!disabled && (
          <span className={styles.hint} aria-hidden="true">
            {COMPOSER_KEYS_HINT}
          </span>
        )}
        {onStop ? (
          <IconButton
            icon="stop"
            label={stopping ? 'Deteniendo la generación…' : 'Detener la generación'}
            variant="secondary"
            size="lg"
            disabled={stopping}
            onClick={onStop}
          />
        ) : (
          <IconButton type="submit" icon="send" label={submitLabel} variant="primary" size="lg" disabled={!ready} />
        )}
      </div>
    </form>
  )
}

export interface ToolButtonProps {
  icon: IconName
  children: ReactNode
  onClick: () => void
  disabled?: boolean
}

// Herramienta del compositor (lienzo .tool): «Elegir en Jira».
export function ToolButton({ icon, children, onClick, disabled }: ToolButtonProps) {
  return (
    <button type="button" className={styles.tool} onClick={onClick} disabled={disabled}>
      <Icon name={icon} />
      {children}
    </button>
  )
}

export interface ProjectButtonProps {
  projectKey?: string
  projectName?: string
  onClick: () => void
  disabled?: boolean
}

// Proyecto de la conversación (UI.md §4.1, T-50): abre «Elegir en Jira» para cambiarlo.
export function ProjectButton({ projectKey, projectName, onClick, disabled }: ProjectButtonProps) {
  const label = projectKey
    ? `Proyecto de Jira: ${projectKey}${projectName ? `, ${projectName}` : ''}. Cambiar`
    : 'Elegir proyecto de Jira'
  return (
    <button type="button" className={styles.project} onClick={onClick} disabled={disabled} aria-label={label}>
      <Icon name="folder" />
      {projectKey ? (
        <>
          <b>{projectKey}</b>
          {projectName && <span className={styles.projectName}>{projectName}</span>}
        </>
      ) : (
        <span>Elegir proyecto</span>
      )}
      <Icon name="chevronDown" size={14} />
    </button>
  )
}

// Modelo de la sesión, de solo lectura hasta Iterar (DESIGN-DECISIONS.md §4 bis).
export function ModelTag({ label }: { label: string }) {
  return (
    <span className={styles.model}>
      <Icon name="model" />
      {label}
    </span>
  )
}
