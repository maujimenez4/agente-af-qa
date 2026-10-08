import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, ApiRequestError, onSessionChecked, onUnauthenticated, setCsrfToken, startSession } from '../api/client.ts'
import type { SessionOut } from '../api/types.ts'
import { OTHER_ACCOUNT_ERROR, SessionContext, type OpenKind, type SessionState } from './sessionContext.ts'

// Sesión del frontend: la cookie la gestiona el navegador; aquí solo el usuario y el CSRF en memoria.
export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' })
  // Lo abierto ahora (conversación o revisión): si la sesión caduca, se reabre al volver a entrar la misma persona.
  const opened = useRef<{ id: string; kind: OpenKind } | undefined>(undefined)
  // Quién ha iniciado sesión (para comparar con `/auth/me` tras un 403, PA-461).
  const username = useRef<string | undefined>(undefined)

  const accept = useCallback((session: SessionOut) => {
    startSession()
    username.current = session.user.username
    setCsrfToken(session.csrf_token)
    setState((previous) => {
      const resume = previous.status === 'anonymous' ? previous.resume : undefined
      return {
        status: 'authenticated',
        user: session.user,
        resume: resume?.username === session.user.username ? resume : undefined,
      }
    })
  }, [])

  // PA-332: un 401 en cualquier pantalla lleva al inicio de sesión con la tarjeta «Sesión caducada».
  useEffect(
    () =>
      onUnauthenticated((error) => {
        setCsrfToken(null)
        setState((previous) => {
          if (previous.status !== 'authenticated') return previous
          const open = opened.current
          return {
            status: 'anonymous',
            error,
            resume: open ? { username: previous.user.username, ...open } : undefined,
          }
        })
      }),
    [],
  )

  // PA-461: tras un 403, el cliente lee `/auth/me`. La misma persona sigue (el cliente guarda el token nuevo);
  // otra persona (otra pestaña) → inicio de sesión con el aviso, sin reabrir lo de la anterior.
  useEffect(
    () =>
      onSessionChecked((session) => {
        if (session.user.username === username.current) return true
        username.current = undefined
        opened.current = undefined
        setCsrfToken(null)
        setState({ status: 'anonymous', error: OTHER_ACCOUNT_ERROR })
        return false
      }),
    [],
  )

  const remember = useCallback((id: string | undefined, kind: OpenKind = 'conversation') => {
    opened.current = id ? { id, kind } : undefined
  }, [])

  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((session) => {
        if (!cancelled) accept(session)
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'anonymous' })
      })
    return () => {
      cancelled = true
    }
  }, [accept])

  const login = useCallback(
    async (username: string, password: string) => {
      try {
        accept(await api.login(username, password))
      } catch (cause) {
        if (!(cause instanceof ApiRequestError)) throw cause
        // Un intento fallido no olvida dónde estaba la persona si su sesión había caducado.
        setState((previous) => ({
          status: 'anonymous',
          error: cause.error,
          resume: previous.status === 'anonymous' ? previous.resume : undefined,
        }))
      }
    },
    [accept],
  )

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // Aunque la API no responda, la sesión local se cierra.
    }
    setCsrfToken(null)
    opened.current = undefined
    setState({ status: 'anonymous' })
  }, [])

  const value = useMemo(() => ({ state, login, logout, remember }), [state, login, logout, remember])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
