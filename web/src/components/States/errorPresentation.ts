// Tarjeta de error por `error.code` del contrato (docs/api/openapi.yaml, ErrorBody).
// El título, el tono y la acción salen de aquí; el MENSAJE se muestra siempre tal cual (UI.md §7).

import type { ApiError, ErrorCode } from '../../api/types.ts'
import { ERROR_CITATIONS, ERROR_COVERAGE, ERROR_PROPOSAL_UNFINISHED, ERROR_QUALITY } from '../../text/assistant.ts'

export type { ApiError }

export type ErrorTone = 'warning' | 'error' | 'neutral'

export type ErrorAction = 'retry' | 'login' | 'restart' | 'refresh' | 'regenerate' | 'backToReceipt'

export interface ErrorPresentation {
  title: string
  tone: ErrorTone
  action?: ErrorAction
}

// DESIGN-DECISIONS.md §6: los 28 valores de ErrorBody.code (lista cerrada del contrato, PA-306).
const PRESENTATIONS: Record<ErrorCode, ErrorPresentation> = {
  // Sesión y permisos
  unauthenticated: { title: 'Sesión caducada', tone: 'neutral', action: 'login' },
  invalid_credentials: { title: 'No se pudo iniciar sesión', tone: 'error' },
  too_many_attempts: { title: 'Demasiados intentos', tone: 'warning', action: 'retry' },
  forbidden: { title: 'Sin permiso', tone: 'neutral' },
  // Petición
  invalid_request: { title: 'Petición no válida', tone: 'error' },
  payload_too_large: { title: 'Contenido demasiado grande', tone: 'error' },
  not_found: { title: 'No se encuentra', tone: 'neutral' },
  project_not_found: { title: 'No se encuentra el proyecto', tone: 'neutral' },
  method_not_allowed: { title: 'Acción no permitida', tone: 'error' },
  http_error: { title: 'Petición no válida', tone: 'error' },
  // Conversación
  not_in_review: { title: 'La revisión ya no está abierta', tone: 'warning', action: 'refresh' },
  approval_rejected: { title: 'Aprobación rechazada', tone: 'error', action: 'restart' },
  handoff_unavailable: { title: 'La HU ya no está disponible', tone: 'warning', action: 'refresh' },
  operation_failed: { title: 'No se pudo completar la operación', tone: 'error', action: 'refresh' },
  not_in_error: { title: 'No hay nada que reintentar', tone: 'warning', action: 'refresh' },
  cancelled: { title: 'Generación detenida', tone: 'neutral', action: 'retry' },
  not_cancellable: { title: 'No se puede detener', tone: 'warning', action: 'refresh' },
  restart: { title: 'La conversación no puede continuar', tone: 'error', action: 'restart' },
  too_many_streams: { title: 'Demasiadas pestañas abiertas', tone: 'warning', action: 'retry' },
  // Servicios externos
  rate_limited: { title: 'Límite de uso alcanzado', tone: 'warning', action: 'retry' },
  service_unavailable: { title: 'Servicio no disponible', tone: 'error', action: 'retry' },
  provider_timeout: { title: 'El modelo no respondió a tiempo', tone: 'warning', action: 'regenerate' },
  // Generación (llegan en ConversationOut.error o QualityReviewOut.error)
  invalid_model_output: { title: ERROR_PROPOSAL_UNFINISHED, tone: 'error', action: 'regenerate' },
  citation_failed: { title: ERROR_CITATIONS, tone: 'error', action: 'regenerate' },
  coverage_failed: { title: ERROR_COVERAGE, tone: 'error', action: 'regenerate' },
  quality_failed: { title: ERROR_QUALITY, tone: 'error', action: 'retry' },
  publish_failed: { title: 'No se puede publicar', tone: 'error', action: 'backToReceipt' },
  // Otros
  unexpected: { title: 'Error inesperado', tone: 'error', action: 'retry' },
}

/** Los códigos con título propio: la lista cerrada `ErrorBody.code` del contrato. */
export const KNOWN_ERROR_CODES = Object.keys(PRESENTATIONS)

/** Respaldo para un código que no esté en la lista (versión futura de la API). */
const FALLBACK: ErrorPresentation = { title: 'No se pudo completar la acción', tone: 'error' }

export function presentError(error: ApiError): ErrorPresentation {
  // Object.hasOwn: «toString», «constructor» o «__proto__» no son códigos conocidos.
  return Object.hasOwn(PRESENTATIONS, error.code) ? PRESENTATIONS[error.code as ErrorCode] : FALLBACK
}

export const ACTION_LABELS: Record<ErrorAction, string> = {
  retry: 'Reintentar',
  login: 'Iniciar sesión',
  restart: 'Empezar de nuevo',
  refresh: 'Actualizar',
  regenerate: 'Volver a generar',
  backToReceipt: 'Volver al recibo',
}

/** Segundos de espera acotados a 0–600 (el servidor ya los acota; esto evita valores absurdos en la UI). */
export function retryDelay(error: ApiError): number {
  const seconds = error.retry_after ?? 0
  if (Number.isNaN(seconds)) return 0
  return Math.min(Math.max(Math.ceil(seconds), 0), 600)
}
