import { useEffect, useRef, useState } from 'react'
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion.ts'
import { charsPerTick, TICK_MS } from './qGeometry.ts'
import styles from './QMark.module.css'

export interface TypewriterTextProps {
  /** Respuesta completa de la API. Para una respuesta nueva, cambia la `key` del componente. */
  text: string
  /** Se llama una vez cuando el texto ya se ve entero. */
  onDone?: () => void
}

/**
 * Escritura simulada: la API no envía el texto por streaming. La animación es solo visual;
 * el texto completo está en un nodo para lectores de pantalla, que el chat (role="log") anuncia.
 * Con «reducir movimiento», el texto aparece entero de inmediato y sin caret.
 */
export function TypewriterText({ text, onDone }: TypewriterTextProps) {
  const reducedMotion = usePrefersReducedMotion()
  const [typed, setTyped] = useState(0)
  const shown = reducedMotion ? text.length : Math.min(typed, text.length)
  const finished = shown >= text.length

  useEffect(() => {
    if (reducedMotion) return
    const step = charsPerTick(text.length)
    const timer = window.setInterval(() => {
      setTyped((current) => {
        const next = Math.min(current + step, text.length)
        if (next >= text.length) window.clearInterval(timer)
        return next
      })
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [text, reducedMotion])

  const doneNotified = useRef(false)
  useEffect(() => {
    if (finished && !doneNotified.current) {
      doneNotified.current = true
      onDone?.()
    }
  }, [finished, onDone])

  return (
    <span data-typing={finished ? 'done' : 'typing'}>
      <span aria-hidden="true">
        {text.slice(0, shown)}
        {!finished && <span className={styles.caret} data-caret="" />}
      </span>
      <span className="visually-hidden">{text}</span>
    </span>
  )
}
