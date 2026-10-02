import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiRequestError, setCsrfToken } from '../api/client.ts'
import type { SessionOut } from '../api/types.ts'
import { SessionContext, type SessionState } from './sessionContext.ts'

// Sesión del frontend: la cookie la gestiona el navegador; aquí solo el usuario y el CSRF en memoria.
export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' })

  const accept = useCallback((session: SessionOut) => {
    setCsrfToken(session.csrf_token)
    setState({ status: 'authenticated', user: session.user })
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
        setState({ status: 'anonymous', error: cause.error })
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
    setState({ status: 'anonymous' })
  }, [])

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
