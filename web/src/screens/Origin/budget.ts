// Presupuesto de tokens del panel «Antes de generar» (UI.md §4.3, PA-102): `budget` de POST /start/sources.
import type { ContextBudget } from '../../api/types.ts'
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

/** Umbral a partir del cual la barra avisa, como el anillo del carril. */
export const BUDGET_WARNING_PERCENT = 90

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many.replace('N', formatNumber(count))
}

/** Lo que pinta el panel; sin un presupuesto válido devuelve `undefined` y no se pinta nada. */
export function budgetView(budget: ContextBudget | undefined): BudgetView | undefined {
  if (!budget) return undefined
  const { used, limit, dropped_sources: dropped, truncated_sources: truncated } = budget
  if (![used, limit, dropped, truncated].every(Number.isFinite) || limit <= 0) return undefined
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
    warning: dropped > 0 || percent >= BUDGET_WARNING_PERCENT,
    notes,
  }
}
