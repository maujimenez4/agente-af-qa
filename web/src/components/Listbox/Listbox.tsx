import { useId, useState, type KeyboardEvent, type ReactNode } from 'react'
import styles from './Listbox.module.css'

export interface ListboxItem {
  id: string
  /** Clave que va delante en gris (DEMO, DEMO-3). */
  itemKey: string
  label: string
}

export interface ListboxProps {
  /** Nombre accesible de la lista («Proyectos», «Épicas de DEMO»…). */
  label: string
  /** Encabezado visible con el recuento. */
  heading: string
  items: readonly ListboxItem[]
  selectedId?: string
  onSelect: (id: string) => void
  /** Texto cuando no hay elementos (con la respuesta ya recibida). */
  emptyText: string
  /** PA-460: mientras llega la lista, este texto (con `aria-busy`) en lugar del vacío. */
  loadingText?: string
  /** PA-460: el error de esta carga (p. ej. su `ErrorCard`), en el sitio de la lista. */
  error?: ReactNode
  /** Nota bajo la lista (p. ej. para qué sirve elegir una épica). */
  note?: ReactNode
}

// Lista de una sola selección con teclado (patrón listbox de WAI-ARIA con aria-activedescendant):
// flechas, Inicio y Fin mueven y eligen; el texto de la API se pinta como texto.
export function Listbox({ label, heading, items, selectedId, onSelect, emptyText, loadingText, error, note }: ListboxProps) {
  const id = useId()
  const [active, setActive] = useState<string | undefined>()
  const activeId = items.some((item) => item.id === active) ? active : (selectedId ?? items[0]?.id)
  const optionId = (itemId: string) => `${id}-${itemId.replace(/[^a-zA-Z0-9_-]/g, '_')}`

  const move = (index: number) => {
    const item = items[Math.min(Math.max(index, 0), items.length - 1)]
    if (!item) return
    setActive(item.id)
    onSelect(item.id)
    document.getElementById(optionId(item.id))?.scrollIntoView?.({ block: 'nearest' })
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = items.findIndex((item) => item.id === activeId)
    const keys: Record<string, () => void> = {
      ArrowDown: () => move(index + 1),
      ArrowUp: () => move(index - 1),
      Home: () => move(0),
      End: () => move(items.length - 1),
      Enter: () => activeId && onSelect(activeId),
      ' ': () => activeId && onSelect(activeId),
    }
    const action = keys[event.key]
    if (!action) return
    event.preventDefault()
    action()
  }

  return (
    <div className={styles.column}>
      <span className={styles.heading} aria-hidden="true">
        {heading}
      </span>
      {error ? (
        <div className={styles.empty}>{error}</div>
      ) : loadingText !== undefined ? (
        <p className={styles.empty} role="status" aria-busy="true">
          {loadingText}
        </p>
      ) : items.length === 0 ? (
        <p className={styles.empty} role="status">
          {emptyText}
        </p>
      ) : (
        <div
          className={styles.listbox}
          role="listbox"
          aria-label={label}
          tabIndex={0}
          aria-activedescendant={activeId ? optionId(activeId) : undefined}
          onKeyDown={onKeyDown}
        >
          {items.map((item) => (
            // Patrón aria-activedescendant: el teclado lo gestiona la lista (onKeyDown arriba) y las
            // opciones no reciben el foco una a una.
            // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus
            <div
              key={item.id}
              id={optionId(item.id)}
              role="option"
              aria-selected={item.id === selectedId}
              className={`${styles.option} ${item.id === activeId ? styles.active : ''}`}
              onClick={() => {
                setActive(item.id)
                onSelect(item.id)
              }}
            >
              <span className={styles.key}>{item.itemKey}</span>{' '}
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      )}
      {note}
    </div>
  )
}
