import { createContext, useContext } from 'react'
import type { ApiError, UserOut } from '../api/types.ts'

/** Qué tenía abierto la persona: una conversación o una revisión de calidad (ids distintos en la API). */
export type OpenKind = 'conversation' | 'quality'

/** Dónde estaba la persona cuando caducó la sesión (PA-332): al volver a entrar, se reabre. */
export interface ResumeAt {
  username: string
  id: string
  kind: OpenKind
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
  /** Lo abierto ahora (o nada): es lo que se reabre si caduca la sesión (PA-332). */
  remember: (id: string | undefined, kind?: OpenKind) => void
}

export const SessionContext = createContext<SessionContextValue | null>(null)

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession necesita un SessionProvider.')
  return value
}
