// Textos de la suite de pruebas (UI.md §6.3, lienzo QaIterar) a partir de `TestSuite`. Todo es texto: nada se
// inserta como HTML, tampoco la estrategia, que llega en Markdown.
import type { TestCase, TestSuite } from '../../api/types.ts'
import type { CaseKind } from '../Badge/index.ts'

export const CASE_KIND: Record<TestCase['type'], CaseKind> = {
  positivo: 'Positivo',
  negativo: 'Negativo',
  alterno: 'Alterno',
  excepcion: 'Excepción',
}

/** «Verifica CA-01, RN-02»; sin referencias, nada. */
export function verifiesLabel(item: TestCase): string | undefined {
  const ids = [...item.criterion_ids, ...item.rule_ids]
  return ids.length > 0 ? `Verifica ${ids.join(', ')}` : undefined
}

export function casesLabel(count: number): string {
  return `${count} ${count === 1 ? 'caso' : 'casos'}`
}

/** Casos que no estaban en la versión anterior (por su id). */
export function newCaseIds(suite: TestSuite, previous: TestSuite | undefined): Set<string> {
  if (!previous) return new Set()
  const before = new Set(previous.cases.map((item) => item.internal_id))
  return new Set(suite.cases.filter((item) => !before.has(item.internal_id)).map((item) => item.internal_id))
}

/**
 * Resumen del asistente, sin LLM. v1: «Suite lista: 4 casos y todos los CA cubiertos. Riesgo: …».
 * Después: «Versión 2: añadí el CP-05 (positivo). 5 casos; la cobertura sigue completa.»
 * La cobertura está comprobada: sin ella la suite no llega a revisión (`coverage_failed`).
 */
export function suiteSummary(suite: TestSuite, version: number, previous: TestSuite | undefined): string {
  if (!previous) {
    const risk = suite.risks[0] ? ` Riesgo: ${suite.risks[0].replace(/\.$/, '')}.` : ''
    return `Suite lista: ${casesLabel(suite.cases.length)} y todos los CA cubiertos.${risk}`
  }
  const added = suite.cases.filter((item) => newCaseIds(suite, previous).has(item.internal_id))
  const what =
    added.length === 0
      ? 'revisé los casos'
      : `añadí ${added.map((item) => `el ${item.internal_id} (${CASE_KIND[item.type].toLowerCase()})`).join(', ')}`
  return `Versión ${version}: ${what}. ${casesLabel(suite.cases.length)}; la cobertura sigue completa.`
}

export interface CoverageRow {
  id: string
  covered: ReadonlySet<string>
}

/** Matriz CA/RN × CP (RF-24) con lo que los casos dicen verificar: primero los CA y después las RN, en orden. */
export function coverageMatrix(suite: TestSuite): { cases: string[]; rows: CoverageRow[] } {
  const byId = new Map<string, Set<string>>()
  for (const item of suite.cases) {
    for (const id of [...item.criterion_ids, ...item.rule_ids]) {
      const set = byId.get(id) ?? new Set<string>()
      set.add(item.internal_id)
      byId.set(id, set)
    }
  }
  const order = (id: string) => (id.startsWith('CA-') ? 0 : 1)
  const rows = [...byId.entries()]
    .sort(([a], [b]) => order(a) - order(b) || a.localeCompare(b, 'es', { numeric: true }))
    .map(([id, covered]) => ({ id, covered }))
  return { cases: suite.cases.map((item) => item.internal_id), rows }
}

/** Columnas de los datos sintéticos: la unión de las claves, en el orden en que aparecen. */
export function dataColumns(rows: readonly Record<string, string>[]): string[] {
  const columns: string[] = []
  for (const row of rows) for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key)
  return columns
}

export type StrategyBlock = { kind: 'heading' | 'paragraph' | 'item'; text: string }

/** La estrategia (Markdown del LLM) en bloques de texto: «## » es un título y «- » un punto; el resto, párrafos. */
export function strategyBlocks(markdown: string): StrategyBlock[] {
  const blocks: StrategyBlock[] = []
  for (const raw of markdown.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    const item = /^[-*]\s+(.*)$/.exec(line)
    if (heading?.[1]) blocks.push({ kind: 'heading', text: heading[1] })
    else if (item?.[1]) blocks.push({ kind: 'item', text: item[1] })
    else blocks.push({ kind: 'paragraph', text: line })
  }
  return blocks
}
