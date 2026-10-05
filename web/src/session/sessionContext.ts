import { createContext, useContext } from 'react'
import type { ApiError, UserOut } from '../api/types.ts'

export type SessionState =
  | { status: 'loading' }
  | { status: 'anonymous'; error?: ApiError }
  | { status: 'authenticated'; user: UserOut }

export interface SessionContextValue {
  state: SessionState
  /** Inicia sesión. Si la API la rechaza, el error queda en `state.error`. */
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

export const SessionContext = createContext<SessionContextValue | null>(null)

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession necesita un SessionProvider.')
  return value
}
