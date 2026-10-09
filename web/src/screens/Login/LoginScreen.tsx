import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button } from '../../components/Button/index.ts'
import { FaqLogo, QaracterLogo } from '../../components/QMark/index.ts'
import { ErrorCard, retryDelay } from '../../components/States/index.ts'
import { TextField } from '../../components/TextField/index.ts'
import { useSession } from '../../session/sessionContext.ts'
import { ASSISTANT_NAME, BRAND_NAME, LOGIN_BUTTON, LOGIN_LEAD } from '../../text/assistant.ts'
import styles from './Login.module.css'

const MOCK_API = import.meta.env.DEV && (import.meta.env.MODE === 'mock' || import.meta.env.VITE_API_MOCK === '1')

/** Alto del logo de Qaracter en la mitad blanca (docs/diseno/faq/README.md §1; mínimo de marca: 24 px). */
const LOGO_HEIGHT = 30

// Inicio de sesión (PA-478, docs/diseno/faq/README.md §1): mitad azul con el logotipo «FAQ», el mensaje y «un asistente
// de Qaracter»; mitad blanca con el logo de Qaracter y el formulario. La lógica es la de PA-311.
export function LoginScreen() {
  const { state, login } = useSession()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [missing, setMissing] = useState<{ username?: string; password?: string }>({})
  const [submitting, setSubmitting] = useState(false)
  const [blockedFor, setBlockedFor] = useState(0)
  const usernameRef = useRef<HTMLInputElement>(null)
  const error = state.status === 'anonymous' ? state.error : undefined

  useEffect(() => {
    usernameRef.current?.focus()
  }, [])

  // too_many_attempts: el botón espera a retry_after (la tarjeta muestra la cuenta atrás).
  const [seenError, setSeenError] = useState(error)
  if (error !== seenError) {
    setSeenError(error)
    setBlockedFor(error?.code === 'too_many_attempts' ? retryDelay(error) : 0)
  }
  useEffect(() => {
    if (blockedFor === 0) return
    const timer = window.setTimeout(() => setBlockedFor((current) => Math.max(current - 1, 0)), 1000)
    return () => window.clearTimeout(timer)
  }, [blockedFor])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const nextMissing = {
      username: username.trim() ? undefined : 'Escribe tu usuario.',
      password: password ? undefined : 'Escribe tu contraseña.',
    }
    setMissing(nextMissing)
    if (nextMissing.username || nextMissing.password) return
    setSubmitting(true)
    await login(username.trim(), password)
    setSubmitting(false)
    setPassword('')
  }

  return (
    <main className={styles.page}>
      <section className={styles.brand} aria-label={`${BRAND_NAME} · ${ASSISTANT_NAME}`}>
        <FaqLogo />
        <p className={styles.message}>
          Historias de usuario y pruebas en segundos. <span className={styles.accent}>Siempre con tu aprobación.</span>
        </p>
        <p className={styles.footer}>
          un asistente de <b>{BRAND_NAME}</b>
        </p>
      </section>

      <section className={styles.side} aria-labelledby="login-title">
        <div className={styles.card}>
          {/* PA-444: el logo completo de Qaracter, aquí a 30 px (PA-478). */}
          <QaracterLogo height={LOGO_HEIGHT} />
          <header className={styles.header}>
            <h1 id="login-title" className={styles.title}>
              Hola de nuevo
            </h1>
            <p className={styles.lead}>{LOGIN_LEAD}</p>
          </header>

          {error && <ErrorCard key={`${error.code}-${error.message}`} error={error} />}

          <form className={styles.form} onSubmit={(event) => void submit(event)} noValidate>
            <TextField
              ref={usernameRef}
              label="Usuario"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              error={missing.username}
            />
            <TextField
              label="Contraseña"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              error={missing.password}
            />
            <Button type="submit" variant="primary" className={styles.submit} disabled={submitting || blockedFor > 0}>
              {submitting ? 'Entrando…' : LOGIN_BUTTON}
            </Button>
          </form>

          {MOCK_API && (
            <p className={styles.note}>
              API simulada: usuarios af-demo, qa-demo o admin-demo, con la contraseña ficticia «demo».
            </p>
          )}
        </div>
      </section>
    </main>
  )
}
