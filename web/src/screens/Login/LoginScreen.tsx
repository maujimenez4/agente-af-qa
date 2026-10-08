import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button } from '../../components/Button/index.ts'
import { QaracterLogo } from '../../components/QMark/index.ts'
import { ErrorCard, retryDelay } from '../../components/States/index.ts'
import { TextField } from '../../components/TextField/index.ts'
import { useSession } from '../../session/sessionContext.ts'
import styles from './Login.module.css'

const MOCK_API = import.meta.env.DEV && (import.meta.env.MODE === 'mock' || import.meta.env.VITE_API_MOCK === '1')

/** Alto del logotipo en el inicio de sesión: por encima del mínimo de marca (24 px) y cabe a 1024 al 125 %. */
const LOGO_HEIGHT = 40

// Inicio de sesión mínimo (PA-311: no está en UI.md ni en el lienzo; pendiente de validar).
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
      <section className={styles.card} aria-labelledby="login-title">
        <header className={styles.header}>
          {/* PA-444: el logotipo completo de Qaracter (40 px de alto, margen libre de media Q). */}
          <QaracterLogo height={LOGO_HEIGHT} className={styles.logo} />
          <h1 id="login-title" className={styles.title}>
            Agente AF y QA
          </h1>
          <p className={styles.lead}>Inicia sesión para continuar.</p>
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
            {submitting ? 'Entrando…' : 'Iniciar sesión'}
          </Button>
        </form>

        {MOCK_API && (
          <p className={styles.note}>
            API simulada: usuarios af-demo, qa-demo o admin-demo, con la contraseña ficticia «demo».
          </p>
        )}
      </section>
    </main>
  )
}
