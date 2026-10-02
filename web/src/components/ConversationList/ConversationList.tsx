import { useId, useState } from 'react'
import type { ApiError } from '../../api/types.ts'
import { Icon } from '../Icon/index.ts'
import { ErrorCard } from '../States/index.ts'
import styles from './ConversationList.module.css'
import { groupByDay, matchesSearch, subtitle, type ConversationSummaryView } from './conversationLabels.ts'

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

// Lista de conversaciones de 248 px (UI.md §2, T-52): nueva, buscador y conversaciones por día.
export function ConversationList({ id, conversations, currentId, onNew, onSelect, now, error, onRetry }: ConversationListProps) {
  const [query, setQuery] = useState('')
  const searchId = useId()
  const visible = conversations.filter((conversation) => matchesSearch(conversation, query))
  const groups = groupByDay(visible, now ?? new Date())

  return (
    <aside id={id} className={styles.list} aria-label="Conversaciones">
      <button type="button" className={styles.newButton} onClick={onNew}>
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
                    onClick={() => onSelect(conversation.thread_id)}
                  >
                    <span className={styles.projectKey}>{conversation.project_key}</span>
                    <span className={styles.title}>{conversation.title}</span>
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
