import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import styles from './Proposal.module.css'

export interface TabItem<T extends string> {
  id: T
  label: string
}

export interface TabsProps<T extends string> {
  label: string
  tabs: readonly TabItem<T>[]
  selected: T
  onSelect: (id: T) => void
  children: ReactNode
}

// Pestañas (patrón tabs de WAI-ARIA): flechas, Inicio y Fin; solo la pestaña activa está en el orden de Tab.
export function Tabs<T extends string>({ label, tabs, selected, onSelect, children }: TabsProps<T>) {
  const id = useId()
  const refs = useRef(new Map<T, HTMLButtonElement>())

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = tabs.findIndex((tab) => tab.id === selected)
    const moves: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }
    const target = moves[event.key]
    if (target === undefined) return
    event.preventDefault()
    const tab = tabs[(target + tabs.length) % tabs.length]
    if (!tab) return
    onSelect(tab.id)
    refs.current.get(tab.id)?.focus()
  }

  return (
    <>
      <div className={styles.tabs} role="tablist" aria-label={label}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            ref={(element) => {
              if (element) refs.current.set(tab.id, element)
            }}
            id={`${id}-tab-${tab.id}`}
            type="button"
            role="tab"
            className={styles.tab}
            aria-selected={tab.id === selected}
            aria-controls={`${id}-panel`}
            tabIndex={tab.id === selected ? 0 : -1}
            onKeyDown={onKeyDown}
            onClick={() => onSelect(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-tab-${selected}`} className={styles.tabPanel}>
        {children}
      </div>
    </>
  )
}
