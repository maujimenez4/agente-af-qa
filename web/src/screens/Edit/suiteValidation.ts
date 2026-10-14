// Validación de Editar a mano la suite (PA-158) en el navegador, con las mismas reglas que el backend. **El backend
// decide**: solo se bloquea *Guardar* con lo que la API rechazaría seguro (contrato `TestSuite`, schemas/test_case.py,
// `_edit` y `blocking_errors` de core/qa/validation.py); lo demás es un aviso. Un CA sin caso no impide guardar, como al
// generar (PA-426): bloquea la aprobación en el recibo. Los datos personales y las citas los comprueba la API.
import type { TestSuite } from '../../api/types.ts'
import type { SuiteCoverage } from '../../components/Suite/suiteText.ts'
import { UNKNOWN_COVERAGE } from '../../components/Suite/suiteText.ts'
import { missingCasesLabel } from '../Receipt/receiptText.ts'
import type { SuiteDraft } from './suiteDraft.ts'
import { NOTE_MAX, sameContent, type EditCheck, type EditIssue, type IssuePath } from './storyValidation.ts'

/**
 * Los CA y RN de la HU de origen. La API no los manda en QA, pero se deducen sin error de la versión en revisión: el
 * backend solo deja en revisión una suite cuyas referencias existen en la HU, y `uncovered` trae los que no tienen
 * caso. Con `uncovered` a `null` («no se sabe»), tampoco se sabe la HU: `null`.
 */
export type StoryRefs = { criteria: string[]; rules: string[] } | null

const CONTRACT = 'Contrato (TestSuite)'
const SCHEMA = 'schemas/test_case.py'
const COVERAGE = 'core/qa/validation.py · blocking_errors'
const EDIT = 'core/graph/nodes.py · _edit'
const EDIT_IN = 'Contrato (EditIn.feedback)'
const NOTICE = 'Aviso (el contrato lo admite)'

const CASE_ID = /^CP-\d+$/
const CRITERION_ID = /^CA-\d+$/
const RULE_ID = /^RN-\d+$/

const byNumber = (a: string, b: string) => a.localeCompare(b, 'es', { numeric: true })
const unique = (ids: readonly string[]) => [...new Set(ids)]
const list = (ids: readonly string[]) => new Intl.ListFormat('es', { type: 'conjunction' }).format(ids)

export function storyRefs(reviewed: TestSuite, uncovered: { criteria?: unknown; rules?: unknown } | null | undefined): StoryRefs {
  if (!uncovered || !Array.isArray(uncovered.criteria) || !Array.isArray(uncovered.rules)) return null
  const strings = (items: unknown[]) => items.filter((item): item is string => typeof item === 'string' && item.length > 0)
  const criteria = unique([...reviewed.cases.flatMap((item) => item.criterion_ids), ...strings(uncovered.criteria)]).sort(byNumber)
  const rules = unique([...reviewed.cases.flatMap((item) => item.rule_ids ?? []), ...strings(uncovered.rules)]).sort(byNumber)
  return { criteria, rules }
}

/** La cobertura de la suite editada, con las reglas de la pestaña *Cobertura*: lo que de la HU no tiene ningún caso. */
export function liveCoverage(suite: TestSuite, refs: StoryRefs): SuiteCoverage {
  if (!refs) return UNKNOWN_COVERAGE
  const covered = new Set(suite.cases.flatMap((item) => [...item.criterion_ids, ...(item.rule_ids ?? [])]))
  const criteria = refs.criteria.filter((id) => !covered.has(id))
  const rules = refs.rules.filter((id) => !covered.has(id))
  return criteria.length + rules.length === 0 ? { kind: 'complete' } : { kind: 'gaps', criteria, rules }
}

/** Texto de la cobertura en vivo, encima del editor. */
export function liveCoverageText(coverage: SuiteCoverage): { tone: 'success' | 'warning' | 'neutral'; lines: string[] } {
  if (coverage.kind === 'unknown') {
    return { tone: 'neutral', lines: ['No se sabe qué CA y RN tiene la HU: FAQ comprobará las referencias y la cobertura al guardar.'] }
  }
  if (coverage.kind === 'complete') return { tone: 'success', lines: ['Cada CA y cada RN de la HU tiene al menos un caso.'] }
  const lines: string[] = []
  const missing = missingCasesLabel(coverage.criteria)
  if (missing) lines.push(`${missing}. Podrás guardar, pero no aprobar la suite hasta que cada CA tenga un caso.`)
  if (coverage.rules.length > 0) lines.push(`Sin ningún caso: ${list(coverage.rules)}. Una RN sin caso no impide aprobar.`)
  return { tone: coverage.criteria.length > 0 ? 'warning' : 'neutral', lines }
}

/** Valores por defecto del contrato, para comparar como `_edit` (un campo ausente es igual que su valor por defecto). */
function withDefaults(suite: TestSuite): TestSuite {
  return {
    ...suite,
    cases: suite.cases.map((item) => ({
      ...item,
      rule_ids: item.rule_ids ?? [],
      gherkin: item.gherkin ?? null,
      steps: item.steps.map((step) => ({ ...step, data: step.data ?? null })),
    })),
    synthetic_data: suite.synthetic_data ?? [],
    risks: suite.risks ?? [],
    dependencies: suite.dependencies ?? [],
    impact_areas: suite.impact_areas ?? [],
    sources: suite.sources ?? [],
  }
}

/** Igualdad estructural de dos suites (como compara `_edit` el contenido editado con el revisado). */
export function sameSuite(a: TestSuite, b: TestSuite): boolean {
  return sameContent(withDefaults(a), withDefaults(b))
}

function repeated(ids: readonly string[]): Set<string> {
  const seen = new Set<string>()
  const twice = new Set<string>()
  for (const id of ids) (seen.has(id) ? twice : seen).add(id)
  return twice
}

export function checkSuite(edited: TestSuite, original: TestSuite, draft: SuiteDraft, refs: StoryRefs, note: string): EditCheck {
  const errors: EditIssue[] = []
  const warnings: EditIssue[] = []
  const error = (path: IssuePath, message: string, source: string) => errors.push({ path, message, source })
  const warning = (path: IssuePath, message: string, source: string) => warnings.push({ path, message, source })

  if (edited.cases.length === 0) error('cases', 'La suite necesita al menos un caso.', CONTRACT)
  const twice = repeated(edited.cases.map((item) => item.internal_id))
  edited.cases.forEach((item, index) => {
    const label = item.internal_id || `El caso ${index + 1}`
    const at = (field: string) => `cases.${index}.${field}`
    if (!CASE_ID.test(item.internal_id)) error(at('id'), `${label}: el identificador debe ser «CP-» y un número (por ejemplo, CP-05).`, CONTRACT)
    else if (twice.has(item.internal_id)) error(at('id'), `El identificador ${item.internal_id} está repetido.`, SCHEMA)
    if (item.title.length === 0) error(at('title'), `${label} necesita un título.`, CONTRACT)
    else if (item.title.trim().length === 0) warning(at('title'), `El título de ${label} solo tiene espacios.`, NOTICE)

    // «Verifica»: un solo mensaje por campo, con todo lo que falla.
    const problems: string[] = []
    const all = [...item.criterion_ids, ...(item.rule_ids ?? [])]
    const malformed = all.filter((id) => !CRITERION_ID.test(id) && !RULE_ID.test(id))
    if (malformed.length > 0) problems.push(`${list(malformed.map((id) => `«${id}»`))} no ${malformed.length === 1 ? 'es' : 'son'} un CA ni una RN (escribe, por ejemplo, CA-01 o RN-02)`)
    if (!item.criterion_ids.some((id) => CRITERION_ID.test(id))) problems.push(`${label} necesita verificar al menos un CA`)
    if (refs) {
      const known = new Set([...refs.criteria, ...refs.rules])
      const unknown = unique(all.filter((id) => (CRITERION_ID.test(id) || RULE_ID.test(id)) && !known.has(id)))
      if (unknown.length > 0) problems.push(`${list(unknown)} no ${unknown.length === 1 ? 'existe' : 'existen'} en la HU`)
    }
    if (problems.length > 0) error(at('refs'), `${problems.join('. ')}.`, malformed.length > 0 || !item.criterion_ids.some((id) => CRITERION_ID.test(id)) ? SCHEMA : COVERAGE)

    if (item.steps.length === 0) error(at('steps'), `${label} necesita al menos un paso.`, CONTRACT)
    item.steps.forEach((step, position) => {
      if (step.action.length === 0) error(`${at('steps')}.${position}.action`, `${label}, paso ${position + 1}: falta la acción.`, CONTRACT)
      if (step.expected.length === 0) error(`${at('steps')}.${position}.expected`, `${label}, paso ${position + 1}: falta el resultado esperado.`, CONTRACT)
    })
  })

  // Al menos un caso positivo y uno negativo (decisión de T-26, `REQUIRED_TYPES`).
  if (edited.cases.length > 0) {
    const types = new Set(edited.cases.map((item) => item.type))
    const absent = (['positivo', 'negativo'] as const).filter((type) => !types.has(type))
    if (absent.length > 0) {
      const which = absent.length === 2 ? 'un caso positivo y uno negativo' : `un caso ${absent[0]}`
      error('types', `La suite necesita al menos ${which}.`, COVERAGE)
    }
  }

  // Datos sintéticos: cada columna con nombre y sin repetir (cada fila es un objeto «nombre: valor»).
  const names = repeated(draft.columns.map((column) => column.name.trim()).filter(Boolean))
  draft.columns.forEach((column, index) => {
    const path = `data.columns.${index}`
    const used = draft.rows.some((row) => (row.values[column.key] ?? '').length > 0)
    if (column.name.trim().length === 0) {
      if (used) error(path, `La columna ${index + 1} de los datos necesita un nombre.`, CONTRACT)
      else warning(path, `La columna ${index + 1} de los datos no tiene nombre ni valores: no se enviará.`, NOTICE)
    } else if (names.has(column.name.trim())) error(path, `La columna «${column.name.trim()}» está repetida.`, CONTRACT)
  })
  draft.rows.forEach((row, index) => {
    const empty = draft.columns.every((column) => (row.values[column.key] ?? '').length === 0)
    if (empty) warning(`data.rows.${index}`, `La fila ${index + 1} de los datos está vacía.`, NOTICE)
  })

  if (sameSuite(edited, original)) error('unchanged', 'No has cambiado nada respecto a la versión revisada.', EDIT)
  if (note.trim().length > NOTE_MAX) error('note', `La nota no puede pasar de ${NOTE_MAX} caracteres.`, EDIT_IN)

  // Cobertura en vivo: un CA sin caso se guarda, pero bloquea la aprobación; una RN sin caso solo avisa.
  const coverage = liveCoverage(edited, refs)
  if (coverage.kind === 'gaps') {
    const missing = missingCasesLabel(coverage.criteria)
    if (missing) warning('coverage.criteria', `${missing}: podrás guardar, pero no aprobar la suite.`, COVERAGE)
    if (coverage.rules.length > 0) warning('coverage.rules', `Sin ningún caso: ${list(coverage.rules)} (no impide aprobar).`, COVERAGE)
  }
  if (edited.strategy_md.trim().length === 0) warning('strategy', 'La estrategia está vacía: se adjuntaría un documento vacío.', NOTICE)
  return { errors, warnings }
}
