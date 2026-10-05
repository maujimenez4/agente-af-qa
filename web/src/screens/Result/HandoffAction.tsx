import { useRef, useState } from 'react'
import { api, toApiError } from '../../api/client.ts'
import type { ApiError, HandoffOut } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { ErrorCard } from '../../components/States/index.ts'
import styles from './Result.module.css'

export interface HandoffActionProps {
  conversationId: string
}

// *Pedir sus pruebas a QA* (T-54): deja la HU aprobada en «Pendientes de pruebas» de QA. Repetirlo es idempotente.
export function HandoffAction({ conversationId }: HandoffActionProps) {
  const [handoff, setHandoff] = useState<HandoffOut | undefined>()
  const [error, setError] = useState<ApiError | undefined>()
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)

  const send = async () => {
    if (sending.current) return
    sending.current = true
    setBusy(true)
    setError(undefined)
    try {
      setHandoff(await api.handoff(conversationId))
    } catch (cause) {
      setError(toApiError(cause))
    } finally {
      sending.current = false
      setBusy(false)
    }
  }

  if (handoff) {
    return (
      <p className={styles.handoffDone} role="status">
        <b>Enviada a QA.</b> La verá quien tenga el rol QA en Inicio, en «Pendientes de pruebas».
        {!handoff.story_key && ' Sin clave en Jira: QA podrá generar y revisar los casos, pero no publicarlos hasta que se publique la HU.'}
      </p>
    )
  }
  return (
    <>
      <Button variant="primary" disabled={busy} onClick={() => void send()}>
        Pedir sus pruebas a QA
      </Button>
      {error && (
        <div className={styles.handoffDone}>
          <ErrorCard key={`${error.code}-${error.message}`} error={error} onAction={() => void send()} />
        </div>
      )}
    </>
  )
}
