// Tarjeta de error por `error.code` del contrato (docs/api/openapi.yaml, ErrorBody).
// El título, el tono y la acción salen de aquí; el MENSAJE se muestra siempre tal cual (UI.md §7).

/** `ErrorBody` del contrato. Provisional hasta generar los tipos con openapi-typescript. */
export interface ApiError {
  code: string
  message: string
  retry_after?: number | null
}

export type ErrorTone = 'warning' | 'error' | 'neutral'

export type ErrorAction = 'retry' | 'login' | 'restart' | 'refresh'

export interface ErrorPresentation {
  title: string
  tone: ErrorTone
  action?: ErrorAction
}

const PRESENTATIONS: Record<string, ErrorPresentation> = {
  rate_limited: { title: 'Límite de uso alcanzado', tone: 'warning', action: 'retry' },
  too_many_attempts: { title: 'Demasiados intentos', tone: 'warning', action: 'retry' },
  service_unavailable: { title: 'Servicio no disponible', tone: 'error', action: 'retry' },
  unauthenticated: { title: 'Sesión caducada', tone: 'neutral', action: 'login' },
  invalid_credentials: { title: 'No se pudo iniciar sesión', tone: 'error' },
  forbidden: { title: 'Sin permiso', tone: 'neutral' },
  not_found: { title: 'No se encuentra', tone: 'neutral' },
  project_not_found: { title: 'No se encuentra el proyecto', tone: 'neutral' },
  approval_rejected: { title: 'Aprobación rechazada', tone: 'error', action: 'restart' },
  not_in_review: { title: 'La revisión ya no está abierta', tone: 'warning', action: 'refresh' },
  invalid_request: { title: 'Petición no válida', tone: 'error' },
}

const FALLBACK: ErrorPresentation = { title: 'No se pudo completar la acción', tone: 'error' }

export function presentError(error: ApiError): ErrorPresentation {
  // Object.hasOwn: «toString», «constructor» o «__proto__» no son códigos conocidos.
  return Object.hasOwn(PRESENTATIONS, error.code) ? (PRESENTATIONS[error.code] ?? FALLBACK) : FALLBACK
}

export const ACTION_LABELS: Record<ErrorAction, string> = {
  retry: 'Reintentar',
  login: 'Iniciar sesión',
  restart: 'Empezar de nuevo',
  refresh: 'Actualizar',
}

/** Segundos de espera acotados a 0–600 (el servidor ya los acota; esto evita valores absurdos en la UI). */
export function retryDelay(error: ApiError): number {
  const seconds = error.retry_after ?? 0
  if (Number.isNaN(seconds)) return 0
  return Math.min(Math.max(Math.ceil(seconds), 0), 600)
}
