// Suite de pruebas de la API simulada (flujo de QA): la conversación de QA en revisión del contrato
// (`components.examples.ConversationQaInReview`, PA-326, copiada a examples.json por PA-118), con 4 casos sobre
// CA-01/CA-02 y RN-01/RN-02 de DEMO-3. Lo que el contrato no trae (iterar, publicar) se simula aquí. Solo datos ficticios.
import type { ConversationOut, ProgressStep, ReviewPayload, TestSuite } from '../api/types.ts'
import { coverageMatrix } from '../components/Suite/suiteText.ts'
import { example } from './examples.ts'
import { randomFingerprint } from './fingerprint.ts'

const QA_REVIEW = 'components.examples.ConversationQaInReview'
const EXAMPLE_KEY = 'DEMO-3'

/** `?simular=sin-cubrir` y `?simular=cobertura-desconocida`: cómo llega `ReviewPayload.uncovered` (PA-326). */
export type ForcedCoverage = 'gaps' | 'unknown'

/** CA y RN ficticios sin caso para `?simular=sin-cubrir`. */
export const MOCK_UNCOVERED = { criteria: ['CA-03'], rules: ['RN-03'] }

/** Pasos de una generación de QA (PA-327), con las etiquetas del ejemplo: 4, sin «Guardar la memoria». */
export function qaGenerationSteps(): Pick<ProgressStep, 'node' | 'label'>[] {
  return example<ConversationOut>(QA_REVIEW).progress.map(({ node, label }) => ({ node, label }))
}

/** La suite del ejemplo del contrato, con la clave de la HU pedida. */
export function mockSuite(storyKey: string = EXAMPLE_KEY): TestSuite {
  const suite = structuredClone(example<ConversationOut>(QA_REVIEW).review?.artifact.content) as TestSuite
  suite.story_jira_key = storyKey
  suite.sources = suite.sources.map((source) => (source.kind === 'jira' && source.ref === EXAMPLE_KEY ? { ...source, ref: storyKey } : source))
  return suite
}

/** La matriz en Markdown, como `TestSuite.coverage_md()` de schemas/test_case.py: una fila por CA o RN con casos. */
export function mockCoverageMd(suite: TestSuite): string {
  const rows = coverageMatrix(suite).rows.map((row) => {
    const cases = [...row.covered].sort((a, b) => a.localeCompare(b, 'es', { numeric: true }))
    return `| ${row.id} | ${cases.join(', ')} | ${cases.length} |`
  })
  return [`# Matriz de cobertura · ${suite.story_jira_key}`, '', '| CA/RN | Casos de prueba | Nº |', '|---|---|---|', ...rows].join('\n') + '\n'
}

/** `uncovered` según `?simular=`: por defecto, el del ejemplo (todo cubierto). */
function mockUncovered(forced: ForcedCoverage | undefined, fallback: ReviewPayload['uncovered']): ReviewPayload['uncovered'] {
  if (forced === 'gaps') return structuredClone(MOCK_UNCOVERED)
  if (forced === 'unknown') return null
  return fallback ?? { criteria: [], rules: [] }
}

/** Conversación de QA en revisión: el ejemplo del contrato con la clave de la HU pedida y el `uncovered` forzado. */
export function mockSuiteConversation(storyKey: string = EXAMPLE_KEY, forced?: ForcedCoverage): ConversationOut {
  const next = example<ConversationOut>(QA_REVIEW)
  const review = next.review
  if (!review) return next
  const suite = mockSuite(storyKey)
  review.artifact = { ...review.artifact, origin_key: storyKey, content: suite }
  review.target = { ...review.target, jira_key: storyKey }
  review.plan = review.plan.map((item) => (item.op === 'publish_suite' ? { ...item, story: storyKey } : item))
  review.coverage_md = mockCoverageMd(suite)
  review.uncovered = mockUncovered(forced, review.uncovered)
  next.title = `Preparar pruebas de ${storyKey}`
  next.versions = next.versions.map((item) => ({ ...item, artifact: review.artifact }))
  return next
}

/** Tipo del caso que pide el cambio («negativo», «excepción», «alterno»); si no dice ninguno, positivo. */
function requestedType(feedback: string): TestSuite['cases'][number]['type'] {
  const text = feedback.toLowerCase()
  if (text.includes('negativ')) return 'negativo'
  if (text.includes('excepci')) return 'excepcion'
  if (text.includes('altern')) return 'alterno'
  return 'positivo'
}

/**
 * Versión siguiente de la suite simulada: añade un caso con lo pedido (la API real lo genera con el LLM). Si la anterior
 * tenía CA sin caso (`?simular=sin-cubrir`), el caso nuevo los verifica y `uncovered.criteria` queda vacío, como lo
 * recalcularía la API: así se ve el recorrido completo (aviso, pedir el caso, aviso resuelto y aprobar). Las RN sin
 * caso se mantienen (avisan sin bloquear).
 */
export function nextSuiteVersion(previous: ConversationOut, feedback: string): ConversationOut {
  const next = structuredClone(previous)
  const review = next.review
  if (!review) return next
  const version = review.version + 1
  const suite = review.artifact.content as TestSuite
  const id = `CP-${String(suite.cases.length + 1).padStart(2, '0')}`
  const missing = review.uncovered?.criteria ?? []
  suite.cases.push({
    internal_id: id,
    title: feedback.trim().slice(0, 80) || 'Caso nuevo',
    type: requestedType(feedback),
    priority: 'Should',
    criterion_ids: missing.length > 0 ? [...missing] : ['CA-02'],
    rule_ids: ['RN-02'],
    preconditions: ['Datos ficticios de la suite'],
    steps: [{ action: 'Repetir la renovación con los datos del caso', expected: 'El resultado coincide con lo pedido' }],
    gherkin: null,
  })
  review.version = version
  review.fingerprint = randomFingerprint()
  review.artifact = { ...review.artifact, version, content: suite }
  review.plan = review.plan.map((item) => (item.op === 'publish_suite' ? { ...item, cases: String(suite.cases.length) } : item))
  review.coverage_md = mockCoverageMd(suite)
  if (review.uncovered) review.uncovered = { criteria: [], rules: review.uncovered.rules }
  review.error = null
  next.versions = [...previous.versions, { artifact: review.artifact, created_at: new Date().toISOString(), edited: false, version }]
  return next
}

/** Error ficticio de una suite publicada en parte (`?simular=parcial`): el último caso no se creó. */
export function suitePartialError(caseId: string): string {
  return `No se pudo crear ${caseId}: Jira no respondió (mensaje ficticio).`
}

/**
 * Resultado de publicar la suite simulada en modo real: una subtarea ficticia por caso (DEMO-21, DEMO-22…).
 * En parte (PA-324), el último caso no se crea y la conversación queda en `approved` con `result.errors` y
 * `failed_ids`; si se publica entera, en `published`.
 */
export function suitePublishOutcome(suite: TestSuite, partial: boolean) {
  const ids = suite.cases.map((item) => item.internal_id)
  const failed = partial ? ids.slice(-1) : []
  const created = ids.filter((id) => !failed.includes(id))
  return {
    state: partial ? ('approved' as const) : ('published' as const),
    published_keys: created.map((_, index) => `DEMO-${21 + index}`),
    errors: failed.map(suitePartialError),
    failed_ids: failed,
  }
}
