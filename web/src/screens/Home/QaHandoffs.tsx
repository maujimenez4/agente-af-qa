import { useEffect, useRef, useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut, HandoffOut } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { Button } from '../../components/Button/index.ts'
import { ErrorCard, Notice } from '../../components/States/index.ts'
import { handoffMeta } from './handoffText.ts'
import styles from './Home.module.css'

export interface QaHandoffsProps {
  /** Recogida: la conversación de QA, ya generando (202 de `/take`). */
  onTaken: (conversation: ConversationOut) => void
}

// QA encadenada (T-54) en Inicio, solo para QA: las HU aprobadas que un analista pasó a QA. *Recoger* empieza su
// conversación de QA; solo una persona puede recogerla (409 `handoff_unavailable`).
export function QaHandoffs({ onTaken }: QaHandoffsProps) {
  const [handoffs, setHandoffs] = useState<HandoffOut[] | undefined>()
  const [error, setError] = useState<ApiError | undefined>()
  const [taken, setTaken] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const taking = useRef(false)
  const [round, setRound] = useState(0)

  useEffect(() => {
    let cancelled = false
    api
      .qaHandoffs()
      .then((items) => {
        if (cancelled) return
        setError(undefined)
        setHandoffs(items)
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(toApiError(cause))
      })
    return () => {
      cancelled = true
    }
  }, [round])

  const take = async (handoff: HandoffOut) => {
    // Una sola petición aunque se pulse dos veces antes de que la pantalla reaccione.
    if (taking.current) return
    taking.current = true
    setBusy(true)
    setError(undefined)
    setTaken(undefined)
    try {
      onTaken(await api.takeHandoff(handoff.id))
    } catch (cause) {
      const failure = toApiError(cause)
      if (failure.code === 'handoff_unavailable') {
        // Otra persona se adelantó: se dice y se vuelve a leer la lista.
        setTaken(handoff.story_key ?? handoff.title)
        setRound((current) => current + 1)
      } else {
        setError(failure)
      }
    } finally {
      taking.current = false
      setBusy(false)
    }
  }

  return (
    <section className={styles.handoffs} aria-labelledby="handoffs-title">
      <h2 id="handoffs-title" className={styles.handoffsTitle}>
        Pendientes de pruebas
      </h2>
      {taken && <Notice>Otra persona ya recogió {taken}. La lista está actualizada.</Notice>}
      {error && (
        <ErrorCard
          key={`${error.code}-${error.message}`}
          error={error}
          onAction={() => {
            setError(undefined)
            setRound((current) => current + 1)
          }}
        />
      )}
      {handoffs && handoffs.length === 0 && <p className={styles.handoffsEmpty}>No hay HU pendientes de pruebas.</p>}
      {handoffs && handoffs.length > 0 && (
        <ul className={styles.handoffList}>
          {handoffs.map((handoff) => (
            <li key={handoff.id} className={styles.handoff}>
              <span className={styles.handoffText}>
                <span className={styles.handoffHead}>
                  {handoff.story_key ? <b>{handoff.story_key}</b> : <Badge tone="warning">Sin clave en Jira</Badge>}
                  <span className={styles.handoffTitle}>{handoff.title}</span>
                </span>
                <span className={styles.handoffMeta}>
                  {handoff.project} · {handoffMeta(handoff)}
                </span>
                {!handoff.story_key && (
                  <span className={styles.handoffMeta}>Aprobada en simulación: podrás generar y revisar los casos, pero no publicarlos.</span>
                )}
              </span>
              <Button
                size="sm"
                disabled={busy}
                aria-label={`Recoger ${handoff.story_key ?? handoff.title}`}
                onClick={() => void take(handoff)}
              >
                Recoger
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
