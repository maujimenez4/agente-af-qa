import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, ApiRequestError, onUnauthenticated, setCsrfToken } from '../api/client.ts'
import type { SessionOut } from '../api/types.ts'
import { SessionContext, type SessionState } from './sessionContext.ts'

// Sesión del frontend: la cookie la gestiona el navegador; aquí solo el usuario y el CSRF en memoria.
export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' })
  // Conversación abierta ahora: si la sesión caduca, se reabre al volver a entrar la misma persona.
  const openConversation = useRef<string | undefined>(undefined)

  const accept = useCallback((session: SessionOut) => {
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
          const conversationId = openConversation.current
          return {
            status: 'anonymous',
            error,
            resume: conversationId ? { username: previous.user.username, conversationId } : undefined,
          }
        })
      }),
    [],
  )

  const remember = useCallback((conversationId: string | undefined) => {
    openConversation.current = conversationId
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
    openConversation.current = undefined
    setState({ status: 'anonymous' })
  }, [])

  const value = useMemo(() => ({ state, login, logout, remember }), [state, login, logout, remember])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
