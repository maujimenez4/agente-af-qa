// Cliente de la API (T-55): mismo origen, cookie de sesión HttpOnly y X-CSRF-Token en memoria.
// DESIGN-DECISIONS.md §4. Nunca guarda nada en el almacenamiento del navegador.
import type {
  ApiError,
  ChooseProjectOut,
  ConversationCreateIn,
  ConversationOut,
  ConversationSummary,
  IssueCard,
  IssueSummary,
  OriginIn,
  ProjectsOut,
  ProposeIn,
  SessionOut,
  SettingsOut,
  SourcePreview,
  SourcesIn,
  StartProposal,
  UsageTodayOut,
} from './types.ts'

const BASE = '/api/v1'

/** Mensaje propio del frontend cuando no hay respuesta de la API (no viene de `ErrorBody`). */
export const NETWORK_ERROR_MESSAGE = 'No se pudo conectar con el servidor. Revisa la conexión y vuelve a intentarlo.'
const BAD_RESPONSE_MESSAGE = 'Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo.'

// Token anti-CSRF de la sesión: solo en memoria (se pide de nuevo con GET /auth/me al recargar).
let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

export function hasCsrfToken(): boolean {
  return csrfToken !== null
}

/** La petición se canceló con su AbortSignal (por nombre: el DOMException puede venir de otro realm). */
export function isAbortError(cause: unknown): boolean {
  return typeof cause === 'object' && cause !== null && (cause as { name?: unknown }).name === 'AbortError'
}

/** Error de una petición, con el cuerpo `ErrorBody` de la API (o uno propio si no hubo respuesta). */
export class ApiRequestError extends Error {
  readonly status: number
  readonly error: ApiError

  constructor(status: number, error: ApiError) {
    super(error.message)
    this.name = 'ApiRequestError'
    this.status = status
    this.error = error
  }
}

export function apiUrl(path: string): string {
  return new URL(`${BASE}${path}`, window.location.origin).toString()
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

async function request<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken

  let response: Response
  try {
    response = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal,
    })
  } catch (cause) {
    if (isAbortError(cause)) throw cause
    throw new ApiRequestError(0, { code: 'service_unavailable', message: NETWORK_ERROR_MESSAGE })
  }

  if (response.status === 204) return undefined as T
  const payload: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    const error = (payload as { error?: ApiError } | undefined)?.error
    throw new ApiRequestError(response.status, error ?? { code: 'unexpected', message: BAD_RESPONSE_MESSAGE })
  }
  return payload as T
}

const enc = encodeURIComponent

export const api = {
  login: (username: string, password: string) => request<SessionOut>('POST', '/auth/login', { username, password }),
  logout: () => request<void>('POST', '/auth/logout'),
  me: () => request<SessionOut>('GET', '/auth/me'),

  projects: () => request<ProjectsOut>('GET', '/projects'),
  chooseProject: (project: string) => request<ChooseProjectOut>('POST', '/projects/choose', { project }),
  epics: (project: string) => request<IssueSummary[]>('GET', `/projects/${enc(project)}/epics`),
  search: (project: string, q = '', signal?: AbortSignal) =>
    request<IssueSummary[]>('GET', `/projects/${enc(project)}/search${q ? `?q=${enc(q)}` : ''}`, undefined, signal),
  stories: (epicKey: string) => request<IssueSummary[]>('GET', `/epics/${enc(epicKey)}/stories`),
  issue: (key: string) => request<IssueCard>('GET', `/issues/${enc(key)}`),

  propose: (body: ProposeIn) => request<StartProposal>('POST', '/start/propose', body),
  sources: (origin: OriginIn, excluded: string[] = []) =>
    request<SourcePreview[]>('POST', '/start/sources', { origin, excluded_sources: excluded } satisfies SourcesIn),

  conversations: () => request<ConversationSummary[]>('GET', '/conversations'),
  createConversation: (body: ConversationCreateIn) => request<ConversationOut>('POST', '/conversations', body),
  conversation: (id: string) => request<ConversationOut>('GET', `/conversations/${enc(id)}`),

  settings: () => request<SettingsOut>('GET', '/settings'),
  usage: () => request<UsageTodayOut>('GET', '/settings/usage'),
}
