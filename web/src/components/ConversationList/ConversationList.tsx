import { useId, useRef, useState } from 'react'
import type { ApiError } from '../../api/types.ts'
import { useLayer } from '../../hooks/useLayer.ts'
import { useMediaQuery } from '../../hooks/useMediaQuery.ts'
import { Icon } from '../Icon/index.ts'
import { ErrorCard } from '../States/index.ts'
import styles from './ConversationList.module.css'
import { conversationTitle, groupByDay, matchesSearch, subtitle, type ConversationSummaryView } from './conversationLabels.ts'

export interface ConversationListProps {
  /** Id para enlazarla con `ConversationsToggle` (aria-controls). */
  id?: string
  conversations: readonly ConversationSummaryView[]
  /** Conversación abierta, si la hay. */
  currentId?: string
  onNew: () => void
  onSelect: (threadId: string) => void
  /** Fecha de referencia para «Hoy» y «Ayer»; por defecto, ahora. */
  now?: Date
  /** No se pudieron leer las conversaciones (UI.md §7): tarjeta de error en lugar de la lista. */
  error?: ApiError
  onRetry?: () => void
}

/** PA-335: por debajo de 1024 px CSS útiles (1280 al 150 %, 1024 al 125 %…), la lista pasa a capa. */
export const NARROW_QUERY = '(max-width: 1023.98px)'

// Lista de conversaciones de 248 px (UI.md §2, T-52): nueva, buscador y conversaciones por día. En ventanas
// estrechas (PA-335) se pliega en una franja con el botón «Conversaciones» y se abre como capa sobre la pantalla.
/** Los elementos que siguen a `element` en su contenedor (sin el velo, que va antes de la lista). */
function followingSiblings(element: Element | null): Element[] {
  const out: Element[] = []
  for (let next = element?.nextElementSibling; next; next = next.nextElementSibling) out.push(next)
  return out
}

export function ConversationList({ id, conversations, currentId, onNew, onSelect, now, error, onRetry }: ConversationListProps) {
  const [query, setQuery] = useState('')
  const searchId = useId()
  const ownId = useId()
  const listId = id ?? ownId
  const visible = conversations.filter((conversation) => matchesSearch(conversation, query))
  const groups = groupByDay(visible, now ?? new Date())

  const narrow = useMediaQuery(NARROW_QUERY)
  const [open, setOpen] = useState(false)
  const layer = narrow && open
  const listRef = useRef<HTMLElement>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)
  const onLayerKeyDown = useLayer({
    open: layer,
    layer: listRef,
    opener: () => toggleRef.current,
    onClose: () => setOpen(false),
    // PA-343: el área de trabajo, a la derecha y bajo el velo (lo que sigue a la lista en el marco).
    inertBehind: () => followingSiblings(listRef.current),
  })
  // Al ensancharse la ventana la lista vuelve a su sitio; si se estrecha otra vez, empieza plegada.
  const [narrowSeen, setNarrowSeen] = useState(narrow)
  if (narrow !== narrowSeen) {
    setNarrowSeen(narrow)
    setOpen(false)
  }
  const closeAfter = (action: () => void) => () => {
    setOpen(false)
    action()
  }

  return (
    <>
      {narrow && (
        <div className={styles.strip}>
          <button
            ref={toggleRef}
            type="button"
            className={styles.stripToggle}
            aria-label="Conversaciones"
            title="Conversaciones"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen(!open)}
          >
            <Icon name="panelLeft" />
          </button>
        </div>
      )}
      {/* Velo de la capa: un clic fuera de la lista la cierra (con el teclado, Esc). */}
      {layer && <div className={styles.backdrop} aria-hidden="true" onClick={() => setOpen(false)} />}
      {/* En capa, la lista es un diálogo: escucha Esc y Tab (patrón dialog de WAI-ARIA, como Modal). */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <aside
        ref={listRef}
        id={listId}
        className={styles.list}
        data-layer={narrow ? '' : undefined}
        hidden={narrow && !open}
        role={layer ? 'dialog' : undefined}
        aria-modal={layer ? 'true' : undefined}
        tabIndex={layer ? -1 : undefined}
        aria-label="Conversaciones"
        onKeyDown={onLayerKeyDown}
      >
        <button type="button" className={styles.newButton} onClick={closeAfter(onNew)}>
          <Icon name="new" />
          Nueva conversación
        </button>

        {conversations.length > 0 && (
          <>
            <label htmlFor={searchId} className="visually-hidden">
              Buscar conversaciones
            </label>
            <input
              id={searchId}
              className={styles.search}
              type="search"
              placeholder="Buscar conversaciones"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </>
        )}

        {error && <ErrorCard key={`${error.code}-${error.message}`} error={error} onAction={onRetry} />}

        <div className={styles.groups}>
          {groups.map((group) => (
            <section key={group.label} aria-label={group.label}>
              <h2 className={styles.groupLabel}>{group.label}</h2>
              <ul className={styles.items}>
                {group.items.map((conversation) => (
                  <li key={conversation.thread_id}>
                    <button
                      type="button"
                      className={styles.thread}
                      aria-current={conversation.thread_id === currentId ? 'true' : undefined}
                      onClick={closeAfter(() => onSelect(conversation.thread_id))}
                    >
                      <span className={styles.projectKey}>{conversation.project_key}</span>
                      <span className={styles.title}>{conversationTitle(conversation.title)}</span>
                      <span className={styles.subtitle}>{subtitle(conversation)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {conversations.length > 0 && visible.length === 0 && (
            <p className={styles.empty} role="status">
              No hay conversaciones que coincidan con la búsqueda.
            </p>
          )}
        </div>

        <div className={styles.spacer} />
        <p className={styles.note}>Las conversaciones se guardan y se pueden retomar después de cerrar la app.</p>
      </aside>
    </>
  )
}

export interface ConversationsToggleProps {
  expanded: boolean
  controls: string
  onToggle: () => void
}

// Botón de la cabecera para mostrar u ocultar la lista plegada (lienzo: «Mostrar conversaciones»).
export function ConversationsToggle({ expanded, controls, onToggle }: ConversationsToggleProps) {
  return (
    <button
      type="button"
      className={styles.toggle}
      aria-label={expanded ? 'Ocultar conversaciones' : 'Mostrar conversaciones'}
      aria-expanded={expanded}
      aria-controls={controls}
      onClick={onToggle}
    >
      <Icon name="panelLeft" />
    </button>
  )
}
