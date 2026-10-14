// Editar a mano la suite de QA en la API simulada (PA-158), como `_edit` de core/graph/nodes.py con un `TestSuite`:
// el esquema (schemas/test_case.py), `story_jira_key` fijo, sin cambios no se guarda y `blocking_errors`
// (core/qa/validation.py): CA y RN que existen en la HU y al menos un caso positivo y uno negativo. Un CA sin caso no
// impide guardar: queda en `uncovered` y el recibo no deja aprobar (PA-426). Se escribe aparte de la validación de la
// web a propósito: así las pruebas comprueban que las dos coinciden. Solo datos ficticios.
import type { ConversationOut, ReviewPayload, TestSuite } from '../api/types.ts'
import { randomFingerprint } from './fingerprint.ts'
import { mockCoverageMd } from './qaSuite.ts'

const CASE_ID = /^CP-\d+$/
const CRITERION_ID = /^CA-\d+$/
const RULE_ID = /^RN-\d+$/
const TYPES = ['positivo', 'negativo', 'alterno', 'excepcion']
const PRIORITIES = ['Must', 'Should', 'Could', "Won't"]

export const SUITE_UNCHANGED = 'La edición no cambia nada respecto a la versión revisada.'

/** Campos que no casan con `TestSuite`, como los lista `_edit`: «cases.0.steps.0.expected». */
export function invalidSuiteFields(value: unknown): string[] {
  if (!value || typeof value !== 'object') return ['contenido']
  const suite = value as Partial<TestSuite>
  const bad: string[] = []
  const text = (v: unknown, min = 0) => typeof v === 'string' && v.length >= min
  const strings = (v: unknown) => Array.isArray(v) && v.every((item) => typeof item === 'string')
  if (!text(suite.story_jira_key, 1)) bad.push('story_jira_key')
  if (!text(suite.strategy_md)) bad.push('strategy_md')
  const cases = Array.isArray(suite.cases) ? suite.cases : undefined
  if (!cases || cases.length === 0) bad.push('cases')
  cases?.forEach((item, index) => {
    const at = `cases.${index}`
    if (!text(item?.internal_id) || !CASE_ID.test(item.internal_id)) bad.push(`${at}.internal_id`)
    if (!text(item?.title, 1)) bad.push(`${at}.title`)
    if (!strings(item?.criterion_ids) || item.criterion_ids.length === 0) bad.push(`${at}.criterion_ids`)
    if (item?.rule_ids !== undefined && !strings(item.rule_ids)) bad.push(`${at}.rule_ids`)
    if (!TYPES.includes(String(item?.type))) bad.push(`${at}.type`)
    if (!PRIORITIES.includes(String(item?.priority))) bad.push(`${at}.priority`)
    if (!strings(item?.preconditions)) bad.push(`${at}.preconditions`)
    const steps = Array.isArray(item?.steps) ? item.steps : undefined
    if (!steps || steps.length === 0) bad.push(`${at}.steps`)
    steps?.forEach((step, position) => {
      if (!text(step?.action, 1)) bad.push(`${at}.steps.${position}.action`)
      if (!text(step?.expected, 1)) bad.push(`${at}.steps.${position}.expected`)
    })
    const refs = [...(strings(item?.criterion_ids) ? item.criterion_ids : []), ...(strings(item?.rule_ids) ? (item.rule_ids ?? []) : [])]
    if (refs.some((id) => !CRITERION_ID.test(id) && !RULE_ID.test(id))) bad.push(at)
  })
  if (suite.synthetic_data !== undefined && !(Array.isArray(suite.synthetic_data) && suite.synthetic_data.every((row) => row && typeof row === 'object' && Object.values(row).every((v) => typeof v === 'string')))) {
    bad.push('synthetic_data')
  }
  return [...new Set(bad)].sort()
}

/** Contenido con los valores por defecto del esquema y las claves ordenadas: así compara `_edit` (modelos pydantic). */
function normalized(suite: TestSuite): string {
  const sorted = (value: unknown): unknown =>
    Array.isArray(value)
      ? value.map(sorted)
      : value && typeof value === 'object'
        ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sorted((value as Record<string, unknown>)[key])]))
        : value
  return JSON.stringify(
    sorted({
      ...suite,
      cases: suite.cases.map((item) => ({ ...item, rule_ids: item.rule_ids ?? [], gherkin: item.gherkin ?? null, steps: item.steps.map((step) => ({ ...step, data: step.data ?? null })) })),
      synthetic_data: suite.synthetic_data ?? [],
      risks: suite.risks ?? [],
      dependencies: suite.dependencies ?? [],
      impact_areas: suite.impact_areas ?? [],
      sources: suite.sources ?? [],
    }),
  )
}

/** La HU de la suite según la API simulada: lo que referencia la revisión más lo que `uncovered` da sin caso. */
function storyIds(review: ReviewPayload): { criteria: Set<string>; rules: Set<string> } | null {
  const uncovered = review.uncovered
  if (!uncovered) return null
  const reviewed = review.artifact.content as TestSuite
  return {
    criteria: new Set([...reviewed.cases.flatMap((item) => item.criterion_ids), ...uncovered.criteria]),
    rules: new Set([...reviewed.cases.flatMap((item) => item.rule_ids ?? []), ...uncovered.rules]),
  }
}

/** El motivo del rechazo, como `_edit` («La edición no se puede guardar: …»), o `undefined` si se guarda. */
export function suiteEditProblem(review: ReviewPayload, content: unknown): string | undefined {
  const bad = invalidSuiteFields(content)
  if (bad.length > 0) return `El contenido editado no es válido; revisa: ${bad.slice(0, 8).join(', ')}.`
  const original = review.artifact.content as TestSuite
  const suite = content as TestSuite
  if (suite.story_jira_key !== original.story_jira_key) return 'El campo story_jira_key no se puede cambiar al editar.'
  if (normalized(suite) === normalized(original)) return SUITE_UNCHANGED
  const ids = storyIds(review)
  const problems: string[] = []
  if (ids) {
    for (const item of suite.cases) {
      const unknown = [...item.criterion_ids.filter((id) => !ids.criteria.has(id)), ...(item.rule_ids ?? []).filter((id) => !ids.rules.has(id))]
      if (unknown.length > 0) problems.push(`${item.internal_id} referencia CA/RN que no existen en la HU: ${unknown.join(', ')}`)
    }
  }
  const types = new Set(suite.cases.map((item) => item.type))
  const absent = ['positivo', 'negativo'].filter((type) => !types.has(type as TestSuite['cases'][number]['type']))
  if (absent.length > 0) problems.push(`faltan casos de tipo: ${absent.join(', ')}`)
  return problems.length > 0 ? `La edición no se puede guardar: ${problems.slice(0, 5).join('; ')}.` : undefined
}

/** La conversación con la versión editada: huella nueva, `edited: true` y la cobertura recalculada sin LLM. */
export function editedSuiteConversation(reviewing: ConversationOut, content: TestSuite): ConversationOut {
  const review = reviewing.review as ReviewPayload
  const version = review.version + 1
  const ids = storyIds(review)
  const covered = new Set(content.cases.flatMap((item) => [...item.criterion_ids, ...(item.rule_ids ?? [])]))
  const order = (a: string, b: string) => a.localeCompare(b, 'es', { numeric: true })
  const uncovered = ids
    ? { criteria: [...ids.criteria].filter((id) => !covered.has(id)).sort(order), rules: [...ids.rules].filter((id) => !covered.has(id)).sort(order) }
    : null
  const artifact = { ...review.artifact, version, content }
  const now = new Date().toISOString()
  return {
    ...reviewing,
    review: { ...review, version, artifact, fingerprint: randomFingerprint(), error: null, uncovered, coverage_md: mockCoverageMd(content) },
    versions: [...reviewing.versions, { artifact, created_at: now, edited: true, version }],
    updated_at: now,
  }
}
