// Textos de Revisar la calidad (UI.md §4.8 · Mixta 5; T-48). El informe lo escribe el LLM: se pinta campo a
// campo como texto y el Markdown (`report_markdown`) es solo para descargarlo.
import type { ApiError, InvestCheck, IssueSummary, QualityFinding, QualityReport, QualityReviewOut, SourceRef } from '../../api/types.ts'
import { countLabel } from '../../text/plural.ts'
import type { StartRequest } from '../Home/HomeScreen.tsx'

/** Cada cuánto se consulta una revisión en curso los dos primeros minutos: la API no tiene SSE para la calidad. */
export const QUALITY_POLL_MS = 2000
/** PA-406: pasados QUALITY_FAST_FOR_MS, se consulta cada QUALITY_SLOW_POLL_MS. */
export const QUALITY_FAST_FOR_MS = 2 * 60_000
export const QUALITY_SLOW_POLL_MS = 10_000
/** PA-406: tope de la espera. Una revisión que sigue `running` más tiempo es, casi seguro, huérfana (API reiniciada). */
export const QUALITY_MAX_WAIT_MS = 30 * 60_000

/** Espera hasta la siguiente consulta según lo que lleva en curso la revisión (o la ventana de *Volver a consultar*). */
export function qualityPollDelay(elapsedMs: number): number {
  return elapsedMs < QUALITY_FAST_FOR_MS ? QUALITY_POLL_MS : QUALITY_SLOW_POLL_MS
}

/**
 * Desde cuándo cuenta el tope: `created_at` de la revisión; si no se puede leer, desde que se abrió la pantalla.
 * Una fecha posterior a la apertura (reloj del servidor adelantado) cuenta desde la apertura: el tope no se alarga.
 */
export function reviewStartedAt(createdAt: string | undefined, openedAt: number): number {
  const parsed = createdAt ? Date.parse(createdAt) : Number.NaN
  return Number.isFinite(parsed) ? Math.min(parsed, openedAt) : openedAt
}

/** Tarjeta al pasar el tope (PA-406): el título de `provider_timeout`, con este mensaje. */
export const STALE_REVIEW: ApiError = {
  code: 'provider_timeout',
  message: 'La revisión lleva más de 30 minutos en curso; puede que el servidor se haya reiniciado. Nada se ha escrito en Jira.',
}
export const RECHECK = 'Volver a consultar'
export const REVIEW_AGAIN = 'Revisar de nuevo'

export const QUALITY_TITLE = 'Revisar la calidad'
export const READ_ONLY = 'Revisar la calidad · solo lectura'
export const INTRO = 'Reviso la HU con INVEST y contra las fuentes, y te doy un informe. No cambio nada en Jira.'
export const RUNNING_NOTE = 'Son dos llamadas al modelo: con el modelo local puede tardar unos minutos. No se escribe nada en Jira.'
export const NOT_FOUND = 'No encuentro esa HU. Vuelve al inicio y escribe su clave, por ejemplo DEMO-4.'
export const REPORT_TITLE = 'Informe de calidad'
export const FOOTER_NOTE =
  'Este flujo no publica en Jira. Evolucionar abre una conversación nueva con estas mejoras como punto de partida.'
export const NO_FINDINGS = 'No hay hallazgos.'

export const INVEST_NAMES: Record<InvestCheck['letter'], string> = {
  I: 'Independiente',
  N: 'Negociable',
  V: 'Valiosa',
  E: 'Estimable',
  S: 'Pequeña',
  T: 'Testeable',
}
const INVEST_ORDER: readonly InvestCheck['letter'][] = ['I', 'N', 'V', 'E', 'S', 'T']

export const VERDICT_LABELS: Record<InvestCheck['verdict'], string> = { ok: 'Bien', improvable: 'Mejorable' }

/** `FINDING_LABELS` de T-48 (schemas/quality.py). */
export const FINDING_LABELS: Record<QualityFinding['kind'], string> = {
  ambiguity: 'Ambigüedad',
  gap: 'Hueco',
  no_source: 'Sin fuente',
  invest: 'INVEST',
  inconsistency: 'Incoherencia con las fuentes',
}

export const SOURCE_KINDS: Record<SourceRef['kind'], string> = { jira: 'Jira', rag: 'Documento', memory: 'Memoria' }

/** Las seis letras en orden I, N, V, E, S, T (como `invest_in_order()`); las que falten no se inventan. */
export function investInOrder(checks: readonly InvestCheck[]): InvestCheck[] {
  return INVEST_ORDER.flatMap((letter) => checks.filter((check) => check.letter === letter).slice(0, 1))
}

/** Recuento de cada tipo de hallazgo, en singular y plural («1 ambigüedad», «2 sin fuente»). */
const FINDING_COUNTS: Record<QualityFinding['kind'], readonly [string, string]> = {
  ambiguity: ['ambigüedad', 'ambigüedades'],
  gap: ['hueco', 'huecos'],
  no_source: ['sin fuente', 'sin fuente'],
  invest: ['hallazgo INVEST', 'hallazgos INVEST'],
  inconsistency: ['incoherencia con las fuentes', 'incoherencias con las fuentes'],
}

/**
 * Resumen de la cabecera del informe, contado sin IA a partir del veredicto: «INVEST: 5 de 6 bien» y los
 * hallazgos por tipo, en el orden de FINDING_LABELS («2 ambigüedades · 1 sin fuente»). Sin puntuaciones.
 */
export function reportSummary(report: Pick<QualityReport, 'invest' | 'findings'>): string {
  const invest = investInOrder(report.invest)
  const ok = invest.filter((check) => check.verdict === 'ok').length
  const kinds = (Object.keys(FINDING_COUNTS) as QualityFinding['kind'][]).flatMap((kind) => {
    const count = report.findings.filter((finding) => finding.kind === kind).length
    const [one, many] = FINDING_COUNTS[kind]
    return count > 0 ? [countLabel(count, one, many)] : []
  })
  return [`INVEST: ${ok} de ${invest.length} bien`, ...(kinds.length > 0 ? kinds : ['sin hallazgos'])].join(' · ')
}

export function findingTag(finding: QualityFinding): string {
  return finding.target_id ? `${FINDING_LABELS[finding.kind]} · ${finding.target_id}` : FINDING_LABELS[finding.kind]
}

export function pointsText(count: number): string {
  if (count === 0) return 'No hay puntos a mejorar.'
  return count === 1 ? 'Hay 1 punto a mejorar.' : `Hay ${count} puntos a mejorar.`
}

/** Mensaje del asistente al terminar (UI.md §4.8): la revisión, el resumen del informe y los puntos. */
export function doneMessage(review: QualityReviewOut): string[] {
  const report = review.report
  return [
    `He revisado ${review.issue_key} con INVEST y contra las fuentes.`,
    ...(report?.summary ? [report.summary] : []),
    `${pointsText(report?.findings.length ?? 0)} No he cambiado nada en Jira.`,
  ]
}

export function reportFileName(key: string): string {
  return `calidad-${key}.md`
}

export function qualityHeading(key: string): string {
  return `Calidad de ${key}`
}

/**
 * HU que se pueden revisar con lo escrito en Inicio: la elegida en Jira o, si no, las claves reconocidas y,
 * sin ninguna, las parecidas. Las épicas no se revisan.
 */
export function reviewCandidates(request: StartRequest): IssueSummary[] {
  const stories = (items: readonly IssueSummary[]) => items.filter((item) => item.issue_type !== 'Epic')
  if (request.origin) return stories([request.origin])
  const recognized = stories(request.proposal?.recognized ?? [])
  return recognized.length > 0 ? recognized : stories(request.proposal?.similar ?? [])
}

/** Proyecto de una clave de Jira («DEMO-4» → «DEMO»). */
export function projectOf(key: string): string {
  return key.split('-')[0] ?? key
}
