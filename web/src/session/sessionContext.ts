import { createContext, useContext } from 'react'
import type { ApiError, UserOut } from '../api/types.ts'

/** Dónde estaba la persona cuando caducó la sesión (PA-332): al volver a entrar, se reabre. */
export interface ResumeAt {
  username: string
  conversationId: string
}

export type SessionState =
  | { status: 'loading' }
  | { status: 'anonymous'; error?: ApiError; resume?: ResumeAt }
  | { status: 'authenticated'; user: UserOut; resume?: ResumeAt }

export interface SessionContextValue {
  state: SessionState
  /** Inicia sesión. Si la API la rechaza, el error queda en `state.error`. */
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** La conversación abierta ahora (o ninguna): es la que se reabre si caduca la sesión (PA-332). */
  remember: (conversationId: string | undefined) => void
}

export const SessionContext = createContext<SessionContextValue | null>(null)

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession necesita un SessionProvider.')
  return value
}
