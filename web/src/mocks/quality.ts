// Revisiones de calidad simuladas (T-48, Mixta 5): parten de los ejemplos del contrato. Solo datos sintéticos.
import type { QualityReviewOut, QualityReviewSummary } from '../api/types.ts'
import { example } from './examples.ts'

export interface MockQualityReview {
  review: QualityReviewOut
  owner: string
  project: string
  title: string
  /** Hora (ms) a partir de la cual la revisión deja `running` al consultarla. */
  readyAt: number
}

/** `?simular=calidad-error`: la revisión acaba en `error` con `quality_failed`. */
export function qualityErrorFrom(search: string): boolean {
  return new URLSearchParams(search).get('simular') === 'calidad-error'
}

/** La revisión guardada del ejemplo del contrato (DEMO-3, «Informe listo»), de af-demo. */
export function seedQualityReviews(): MockQualityReview[] {
  const summary = example<QualityReviewSummary[]>('GET /api/v1/quality-reviews 200')[0]
  const review = example<QualityReviewOut>('GET /api/v1/quality-reviews/{review_id} 200')
  if (!summary) return []
  return [{ review, owner: 'af-demo', project: summary.project, title: summary.title, readyAt: 0 }]
}

export function qualitySummary(item: MockQualityReview): QualityReviewSummary {
  const { id, issue_key, state, created_at, updated_at } = item.review
  return { id, issue_key, project: item.project, title: item.title, state, created_at, updated_at }
}

/** POST /quality-reviews: 202 en `running`, como la API; el informe llega al consultarla tras `delayMs`. */
export function newQualityReview(issueKey: string, owner: string, now: number, delayMs: number): MockQualityReview {
  const key = issueKey.trim().toUpperCase()
  const at = new Date(now).toISOString()
  const review: QualityReviewOut = {
    ...example<QualityReviewOut>('POST /api/v1/quality-reviews 202'),
    id: crypto.randomUUID(),
    issue_key: key,
    state: 'running',
    report: null,
    report_markdown: null,
    evolve_feedback: [],
    error: null,
    created_at: at,
    updated_at: at,
  }
  const project = key.split('-')[0] ?? key
  return { review, owner, project, title: `Revisar la calidad de ${key}`, readyAt: now + delayMs }
}

/**
 * Avanza una revisión en curso cuando le toca: el informe del ejemplo con la clave pedida o, si la HU no
 * existe (o con `?simular=calidad-error`), `error`. Nada se escribe en ningún Jira.
 */
export function settleQualityReview(item: MockQualityReview, now: number, forceError: boolean, exists: (key: string) => boolean): void {
  if (item.review.state !== 'running' || now < item.readyAt) return
  const key = item.review.issue_key
  const updated_at = new Date(now).toISOString()
  if (!exists(key)) {
    item.review = { ...item.review, state: 'error', updated_at, error: { code: 'not_found', message: `No existe la incidencia ${key} o no la puedes ver.` } }
    return
  }
  if (forceError) {
    item.review = {
      ...item.review,
      state: 'error',
      updated_at,
      error: { code: 'quality_failed', message: 'No se pudo revisar la calidad: el modelo no devolvió un informe válido (ficticio).' },
    }
    return
  }
  const done = example<QualityReviewOut>('POST /api/v1/quality-reviews 202')
  item.review = {
    ...item.review,
    state: 'done',
    updated_at,
    report: done.report,
    evolve_feedback: done.evolve_feedback,
    report_markdown: (done.report_markdown ?? '').replaceAll('DEMO-3', key),
  }
}
