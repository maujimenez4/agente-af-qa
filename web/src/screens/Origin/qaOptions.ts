// QA 1 (UI.md §6.1): tipos de caso (RF-22) e «Incluir además». Van como primer `feedback` de POST /conversations,
// con los mismos textos que la vista de Streamlit (app/qa.py, `qa_feedback`).

export type CaseTypeId = 'positive' | 'negative' | 'alternate' | 'exception'
export type ExtraId = 'data' | 'risks' | 'strategy'

export interface QaChoice<T extends string> {
  id: T
  label: string
  hint?: string
}

/** `core/qa/validation` exige al menos un caso positivo y uno negativo: no se pueden quitar. */
export const REQUIRED_TYPES: ReadonlySet<CaseTypeId> = new Set(['positive', 'negative'])

export const CASE_TYPES: readonly QaChoice<CaseTypeId>[] = [
  { id: 'positive', label: 'Positivos' },
  { id: 'negative', label: 'Negativos' },
  { id: 'alternate', label: 'Alternos' },
  { id: 'exception', label: 'De excepción' },
]

export const EXTRAS: readonly QaChoice<ExtraId>[] = [
  { id: 'data', label: 'Datos sintéticos', hint: 'Identificadores ficticios, coherentes con las reglas (RF-25)' },
  { id: 'risks', label: 'Riesgos, dependencias e impacto', hint: 'RF-27' },
  { id: 'strategy', label: 'Estrategia de pruebas', hint: 'Alcance, niveles, entornos y criterios (RF-26)' },
]

const EXTRA_TEXT: Record<ExtraId, string> = {
  data: 'datos sintéticos de prueba (identificadores ficticios)',
  risks: 'riesgos, dependencias y áreas de impacto',
  strategy: 'estrategia de pruebas (alcance, niveles, entornos, criterios de entrada y salida, prioridad)',
}

/** «Incluye casos: positivos, negativos.» y, si hay extras, «Incluye además: …». Los obligatorios, siempre. */
export function qaFeedback(types: ReadonlySet<CaseTypeId>, extras: ReadonlySet<ExtraId>): string[] {
  const chosen = CASE_TYPES.filter((item) => types.has(item.id) || REQUIRED_TYPES.has(item.id)).map((item) => item.label.toLowerCase())
  const parts = [`Incluye casos: ${chosen.join(', ')}.`]
  const wanted = EXTRAS.filter((item) => extras.has(item.id)).map((item) => EXTRA_TEXT[item.id])
  if (wanted.length > 0) parts.push(`Incluye además: ${wanted.join('; ')}.`)
  return parts
}

/** Resumen de «Incluir además» plegado: «3 de 3 incluidos», «1 de 3 incluido», «Ninguno incluido». */
export function extrasSummary(chosen: number, total: number): string {
  if (chosen === 0) return 'Ninguno incluido'
  return `${chosen} de ${total} ${chosen === 1 ? 'incluido' : 'incluidos'}`
}
