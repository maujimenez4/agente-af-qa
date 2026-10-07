// Presupuesto de tokens del panel «Antes de generar» (UI.md §4.3, PA-102): `budget` de POST /start/sources.
import type { ContextBudget, SourcePreview } from '../../api/types.ts'
import { formatNumber } from '../../text/numbers.ts'

export interface BudgetView {
  /** «Contexto · 2.350 de 6.000 tokens». */
  label: string
  /** Ancho de la barra, 0–100. */
  percent: number
  /** Aviso: fuentes que no caben (no se envían) o el presupuesto casi lleno (90 % o más). */
  warning: boolean
  /** Frases de las fuentes descartadas o recortadas; vacío si todo cabe entero. */
  notes: string[]
}

/** Espera tras el último clic en una casilla antes de pedir el presupuesto otra vez. */
export const BUDGET_DEBOUNCE_MS = 300

/** Clave de `budgetFor` tras un fallo (ninguna ref de fuente lleva «<»): obliga a volver a pedir el presupuesto. */
export const BUDGET_FAILED = '<fallo>'

/** Umbral a partir del cual la barra avisa, como el anillo del carril. */
export const BUDGET_WARNING_PERCENT = 90

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many.replace('N', formatNumber(count))
}

/**
 * PA-330: estimación al instante del uso de las fuentes marcadas (las obligatorias siempre cuentan), sumando
 * `SourcePreview.tokens`. Sin `tokens` en alguna fuente (API anterior), `undefined`: se espera a la respuesta.
 */
export function estimateUsed(sources: readonly SourcePreview[], excluded: readonly string[]): number | undefined {
  if (sources.length === 0 || !sources.every((source) => typeof source.tokens === 'number' && Number.isFinite(source.tokens))) return undefined
  return sources.filter((source) => source.required || !excluded.includes(source.ref)).reduce((total, source) => total + (source.tokens ?? 0), 0)
}

/** La nota que explica por qué la confirmación no coincide con la estimación (el RAG rellena el hueco). */
export const REFILL_NOTE = 'Al quitar un documento puede entrar otro relacionado en su lugar: manda el número confirmado.'

/**
 * La confirmación cambia la estimación de forma visible: más de un 1 % del límite (redondeos aparte). Solo entonces sale
 * `REFILL_NOTE`, para no confundir con diferencias que nadie ve.
 */
export function differsFromEstimate(budget: ContextBudget | undefined, estimate: number | undefined): boolean {
  if (!budget || estimate === undefined || !Number.isFinite(budget.used) || !(budget.limit > 0)) return false
  return Math.abs(budget.used - estimate) > budget.limit / 100
}

/** PA-330: con `fixed > 0`, lo que ocupa el texto de la necesidad aparte de las fuentes, sobre el total del contexto. */
export function fixedNote(budget: ContextBudget | undefined): string | undefined {
  const fixed = budget?.fixed
  const total = budget?.total
  if (typeof fixed !== 'number' || !Number.isFinite(fixed) || fixed <= 0) return undefined
  const ofTotal = typeof total === 'number' && Number.isFinite(total) && total > 0 ? ` del total de ${formatNumber(total)}` : ''
  return `El texto de la necesidad ocupa ${formatNumber(fixed)} tokens aparte${ofTotal}.`
}

/**
 * Lo que pinta el panel; sin un presupuesto válido devuelve `undefined` y no se pinta nada. Con `estimate` (PA-330,
 * mientras llega la confirmación), el uso es la estimación: «≈ … · estimación», sin las notas del servidor, que son de
 * la consulta anterior.
 */
export function budgetView(budget: ContextBudget | undefined, estimate?: number): BudgetView | undefined {
  if (!budget) return undefined
  const { limit, dropped_sources: dropped, truncated_sources: truncated } = budget
  if (![budget.used, limit, dropped, truncated].every(Number.isFinite) || limit <= 0) return undefined
  if (estimate !== undefined && Number.isFinite(estimate)) {
    return {
      label: `Contexto · ≈ ${formatNumber(Math.max(estimate, 0))} de ${formatNumber(limit)} tokens · estimación`,
      percent: Math.round(Math.min(Math.max((estimate / limit) * 100, 0), 100)),
      warning: estimate >= (limit * BUDGET_WARNING_PERCENT) / 100,
      notes: [],
    }
  }
  const { used } = budget
  const percent = Math.round(Math.min(Math.max((used / limit) * 100, 0), 100))
  const notes: string[] = []
  if (dropped > 0) {
    notes.push(plural(dropped, '1 fuente no cabe y no se enviará al modelo.', 'N fuentes no caben y no se enviarán al modelo.'))
  }
  if (truncated > 0) {
    notes.push(plural(truncated, '1 incidencia se recorta para que quepa.', 'N incidencias se recortan para que quepan.'))
  }
  return {
    label: `Contexto · ${formatNumber(Math.max(used, 0))} de ${formatNumber(limit)} tokens`,
    percent,
    // Sin redondear, como el anillo del carril: 89,98 % no avisa.
    warning: dropped > 0 || used >= (limit * BUDGET_WARNING_PERCENT) / 100,
    notes,
  }
}
