// Cliente de la API (T-55): mismo origen, cookie de sesión HttpOnly y X-CSRF-Token en memoria.
// DESIGN-DECISIONS.md §4. Nunca guarda nada en el almacenamiento del navegador.
import type {
  AdminModelsOut,
  ApiError,
  ChooseProjectOut,
  ConnectionsTestOut,
  ConversationCreateIn,
  ConversationOut,
  ConversationSummary,
  HandoffOut,
  IssueCard,
  IssueSummary,
  IterateIn,
  MemoryOut,
  MemorySummary,
  ApproveIn,
  EditIn,
  OriginIn,
  ProjectsOut,
  ProposeIn,
  QualityReviewIn,
  QualityReviewOut,
  QualityReviewSummary,
  SessionOut,
  SettingsOut,
  SourcesIn,
  SourcesOut,
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

/** Mensaje para un fallo que no es de la API (red caída, respuesta ilegible…), como `unexpected`. */
export const UNEXPECTED_ERROR: ApiError = {
  code: 'unexpected',
  message: 'Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo.',
}

/** El `ApiError` de un fallo: el de la API o, si no lo es, `UNEXPECTED_ERROR` (nunca se relanza sin capturar). */
export function toApiError(cause: unknown): ApiError {
  return cause instanceof ApiRequestError ? cause.error : UNEXPECTED_ERROR
}

export function apiUrl(path: string): string {
  return new URL(`${BASE}${path}`, window.location.origin).toString()
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

/**
 * `repeatable`: la acción se puede repetir sin efectos (PA-461): tras un 403 por un token CSRF antiguo, se reintenta
 * una vez con el nuevo. `recovered` (interno): ya es ese reintento; no se vuelve a recuperar (sin bucles).
 */
async function request<T>(
  method: Method,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
  repeatable = false,
  recovered = false,
): Promise<T> {
  const startedIn = sessionNumber
  const sentToken = csrfToken
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
    const error = (payload as { error?: ApiError } | undefined)?.error ?? { code: 'unexpected', message: BAD_RESPONSE_MESSAGE }
    // Un 401 de una petición lanzada en una sesión anterior (antes de volver a entrar) no echa a nadie.
    if (response.status === 401 && !SESSION_PATHS.has(path) && startedIn === sessionNumber) unauthenticatedHandler?.(error)
    // PA-461: la API da el mismo 403 si falta el permiso que si el token CSRF es antiguo (se inició sesión en otra
    // pestaña). Se comprueba la sesión una vez: si el token cambió, era eso.
    // Solo con un token enviado: sin token (sesión cerrada) el 403 es lo esperado.
    if (response.status === 403 && method !== 'GET' && sentToken !== null && !SESSION_PATHS.has(path) && !recovered && startedIn === sessionNumber) {
      const outcome = await checkSessionAfterForbidden(sentToken)
      // Mientras se comprobaba, en esta pestaña pudo cambiar la sesión (cerrar y entrar otra persona): sin reintento.
      if (outcome === 'renewed' && startedIn === sessionNumber) {
        if (repeatable) return request<T>(method, path, body, signal, repeatable, true)
        throw new ApiRequestError(403, { code: 'operation_failed', message: SESSION_RENEWED_MESSAGE })
      }
    }
    throw new ApiRequestError(response.status, error)
  }
  return payload as T
}

const enc = encodeURIComponent

// PA-332: un 401 en cualquier pantalla avisa a la sesión (SessionProvider pasa a anónimo). No avisan las
// rutas de la propia sesión: un 401 en /auth/me al arrancar o en /auth/login es lo esperado.
const SESSION_PATHS = new Set(['/auth/me', '/auth/login', '/auth/logout'])
let unauthenticatedHandler: ((error: ApiError) => void) | undefined
let sessionNumber = 0

/** PA-461: una acción que no se repite sola tras renovar el token: la persona la vuelve a pedir. */
export const SESSION_RENEWED_MESSAGE = 'Tu sesión se renovó en otra pestaña. Vuelve a intentarlo.'

/**
 * Lo que dice `GET /auth/me` tras un 403 (PA-461):
 * - `renewed`: la misma persona con otro token (se guarda el nuevo);
 * - `unchanged`: el mismo token, así que el 403 es de permisos de verdad;
 * - `switched`: otra persona inició sesión en otra pestaña (la sesión vuelve al inicio de sesión);
 * - `failed`: no se pudo comprobar (un 401 lo trata la sesión, PA-332).
 */
type ForbiddenCheck = 'renewed' | 'unchanged' | 'switched' | 'failed'
let sessionCheck: Promise<ForbiddenCheck> | undefined
let sessionChangedHandler: ((session: SessionOut) => boolean) | undefined

/**
 * Registra quién decide si una sesión leída de `/auth/me` es de la misma persona (la sesión). Devuelve `true` si
 * lo es; si no, la sesión ya ha vuelto al inicio de sesión. Devuelve la función para dejar de escucharlo.
 */
export function onSessionChecked(handler: (session: SessionOut) => boolean): () => void {
  sessionChangedHandler = handler
  return () => {
    if (sessionChangedHandler === handler) sessionChangedHandler = undefined
  }
}

/** Comprueba la sesión una sola vez aunque lleguen varios 403 a la vez (comparten la consulta). */
async function checkSessionAfterForbidden(sentToken: string | null): Promise<ForbiddenCheck> {
  // Otra petición ya renovó el token después de enviarse esta: no hace falta preguntar.
  if (csrfToken !== null && csrfToken !== sentToken) return 'renewed'
  sessionCheck ??= (async (): Promise<ForbiddenCheck> => {
    try {
      const session = await request<SessionOut>('GET', '/auth/me')
      // Sin nadie que confirme que es la misma persona, no se acepta el token (falla de forma segura).
      if (!sessionChangedHandler) return 'failed'
      if (!sessionChangedHandler(session)) return 'switched'
      if (session.csrf_token === sentToken) return 'unchanged'
      csrfToken = session.csrf_token
      return 'renewed'
    } catch (cause) {
      if (cause instanceof ApiRequestError && cause.status === 401) unauthenticatedHandler?.(cause.error)
      return 'failed'
    } finally {
      sessionCheck = undefined
    }
  })()
  return sessionCheck
}

/** Empieza una sesión nueva (cada inicio de sesión aceptado): los 401 de peticiones anteriores se ignoran. */
export function startSession(): void {
  sessionNumber += 1
}

/** Registra quién se entera de un 401 (la sesión). Devuelve la función para dejar de escucharlo. */
export function onUnauthenticated(handler: (error: ApiError) => void): () => void {
  unauthenticatedHandler = handler
  return () => {
    if (unauthenticatedHandler === handler) unauthenticatedHandler = undefined
  }
}

/** Filtros de `GET /memories`: proyecto, texto que buscar (clave y contenido) y cuántas como mucho (1 a 200). */
export interface MemoryFilters {
  project?: string | null
  q?: string
  limit?: number
}

/** «?project=DEMO&q=renovar&limit=200», sin los filtros vacíos. */
export function memoryQuery({ project, q, limit }: MemoryFilters): string {
  const params = new URLSearchParams()
  if (project) params.set('project', project)
  if (q?.trim()) params.set('q', q.trim())
  if (limit !== undefined) params.set('limit', String(limit))
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const api = {
  login: (username: string, password: string) => request<SessionOut>('POST', '/auth/login', { username, password }),
  logout: () => request<void>('POST', '/auth/logout'),
  me: () => request<SessionOut>('GET', '/auth/me'),

  projects: () => request<ProjectsOut>('GET', '/projects'),
  chooseProject: (project: string) => request<ChooseProjectOut>('POST', '/projects/choose', { project }, undefined, true),
  epics: (project: string) => request<IssueSummary[]>('GET', `/projects/${enc(project)}/epics`),
  search: (project: string, q = '', signal?: AbortSignal) =>
    request<IssueSummary[]>('GET', `/projects/${enc(project)}/search${q ? `?q=${enc(q)}` : ''}`, undefined, signal),
  stories: (epicKey: string) => request<IssueSummary[]>('GET', `/epics/${enc(epicKey)}/stories`),
  issue: (key: string) => request<IssueCard>('GET', `/issues/${enc(key)}`),

  propose: (body: ProposeIn) => request<StartProposal>('POST', '/start/propose', body, undefined, true),
  sources: (origin: OriginIn, excluded: string[] = [], signal?: AbortSignal) =>
    request<SourcesOut>('POST', '/start/sources', { origin, excluded_sources: excluded } satisfies SourcesIn, signal, true),

  conversations: () => request<ConversationSummary[]>('GET', '/conversations'),
  createConversation: (body: ConversationCreateIn) => request<ConversationOut>('POST', '/conversations', body),
  conversation: (id: string) => request<ConversationOut>('GET', `/conversations/${enc(id)}`),
  iterate: (id: string, feedback: string) =>
    request<ConversationOut>('POST', `/conversations/${enc(id)}/iterate`, { feedback } satisfies IterateIn),
  discard: (id: string) => request<ConversationOut>('POST', `/conversations/${enc(id)}/discard`),
  approve: (id: string, fingerprint: string) =>
    request<ConversationOut>('POST', `/conversations/${enc(id)}/approve`, { fingerprint } satisfies ApproveIn),
  cancel: (id: string) => request<ConversationOut>('POST', `/conversations/${enc(id)}/cancel`, undefined, undefined, true),
  retry: (id: string) => request<ConversationOut>('POST', `/conversations/${enc(id)}/retry`),

  // QA encadenada (T-54): el analista pasa la HU a QA; QA ve las pendientes y recoge una.
  handoff: (id: string) => request<HandoffOut>('POST', `/conversations/${enc(id)}/handoff`),
  qaHandoffs: () => request<HandoffOut[]>('GET', '/qa/handoffs'),
  takeHandoff: (id: string) => request<ConversationOut>('POST', `/qa/handoffs/${enc(id)}/take`),

  // Memoria (T-33): las memorias de las HU publicadas que ve la conexión, y una con su contenido y su .md.
  memories: (filters: MemoryFilters = {}, signal?: AbortSignal) => request<MemorySummary[]>('GET', `/memories${memoryQuery(filters)}`, undefined, signal),
  // «.» y «..» se normalizarían como segmentos de ruta (saldrían de /memories): no son una clave válida.
  memory: (key: string, signal?: AbortSignal) =>
    key === '.' || key === '..'
      ? Promise.reject(new ApiRequestError(400, { code: 'invalid_request', message: 'La clave de la memoria no es válida.' }))
      : request<MemoryOut>('GET', `/memories/${enc(key)}`, undefined, signal),

  settings: () => request<SettingsOut>('GET', '/settings'),
  usage: () => request<UsageTodayOut>('GET', '/settings/usage'),

  // Administración mínima (T-29): solo admin. Probar conexiones lleva CSRF y admite una prueba cada 10 s.
  adminConnectionsTest: () => request<ConnectionsTestOut>('POST', '/admin/connections/test', undefined, undefined, true),
  adminModels: (signal?: AbortSignal) => request<AdminModelsOut>('GET', '/admin/models', undefined, signal),

  // Revisar la calidad (T-48, Mixta 5): solo lectura, no publica. Responde 202 en `running`; el avance, consultando la revisión.
  startQualityReview: (body: QualityReviewIn) => request<QualityReviewOut>('POST', '/quality-reviews', body),
  qualityReviews: () => request<QualityReviewSummary[]>('GET', '/quality-reviews'),
  qualityReview: (id: string, signal?: AbortSignal) =>
    request<QualityReviewOut>('GET', `/quality-reviews/${enc(id)}`, undefined, signal),

  // Editar a mano (RF-32): versión nueva sin llamar al modelo, con la huella del payload mostrado; 200 síncrono. Una edición
  // que la API rechaza no es un error HTTP: llega en `review.error` con la misma revisión. La nota solo va si no está vacía.
  edit: (id: string, fingerprint: string, content: EditIn['content'], feedback?: string | null) =>
    request<ConversationOut>('POST', `/conversations/${enc(id)}/edit`, {
      fingerprint,
      content,
      ...(feedback?.trim() ? { feedback } : {}),
    } satisfies EditIn),
}
