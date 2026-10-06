// PA-326 y PA-118 (T-56): la suite de la API simulada sale del ejemplo del contrato
// (`components.examples.ConversationQaInReview`, copiado a examples.json por tools/api-types/generate.mjs),
// `coverage_md` y `uncovered` en la revisión, `?simular=sin-cubrir|cobertura-desconocida` y los 4 pasos de QA (PA-327).
// Datos sintéticos (DEMO-3, qa-demo).
import { describe, expect, it } from 'vitest'
import examples from '../api/examples.json'
import type { ConversationOut, ProgressStep, SessionOut, TestSuite } from '../api/types.ts'
import { DEMO_PASSWORD, forcedCoverageFrom } from './db.ts'
import { mockDb } from './node.ts'
import { MOCK_UNCOVERED, mockCoverageMd, mockSuite, mockSuiteConversation, nextSuiteVersion, qaGenerationSteps } from './qaSuite.ts'

const QA_REVIEW_KEY = 'components.examples.ConversationQaInReview'
const QA_EXAMPLE = (examples as Record<string, unknown>)[QA_REVIEW_KEY] as ConversationOut | undefined

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(username = 'qa-demo'): Promise<string> {
  const response = await fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: DEMO_PASSWORD }),
  })
  return ((await response.json()) as SessionOut).csrf_token
}

function post(path: string, csrf: string, body: unknown = {}) {
  return fetch(url(path), { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(body) })
}

async function events(id: string): Promise<Array<{ event: string; data: unknown }>> {
  const text = await (await fetch(url(`/conversations/${id}/events`))).text()
  return text
    .split('\n\n')
    .filter(Boolean)
    .map((block) => ({ event: /^event: (.*)$/m.exec(block)?.[1] ?? '', data: JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? 'null') as unknown }))
}

/** Crea una generación de QA (flujo `tests`) de DEMO-3 y la sigue por SSE hasta el final. */
async function generateQa(csrf: string) {
  const created = (await (await post('/conversations', csrf, { origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, flow: 'tests', excluded_sources: [], feedback: [] })).json()) as ConversationOut
  const stream = await events(created.id)
  const last = stream.at(-1)
  return { created, stream, ready: last?.data as ConversationOut, lastEvent: last?.event }
}

describe('PA-118 · examples.json trae los ejemplos con nombre del contrato', () => {
  it('test_examples_json_contains_conversation_qa_in_review_with_coverage_fields', () => {
    /** PA-118: generate.mjs copia components.examples.<Nombre> (solo su value) a examples.json. */
    expect(QA_EXAMPLE).toBeDefined()
    expect(QA_EXAMPLE).toMatchObject({ mode: 'qa', flow: 'tests', state: 'in_review' })
    expect(typeof QA_EXAMPLE?.review?.coverage_md).toBe('string')
    expect(QA_EXAMPLE?.review?.coverage_md).toMatch(/^# Matriz de cobertura · DEMO-3\n/)
    expect(QA_EXAMPLE?.review?.uncovered).toEqual({ criteria: [], rules: [] })
    expect(QA_EXAMPLE?.review?.fingerprint).toBe('7c'.repeat(32))
  })

  it('test_examples_json_qa_example_has_four_cases_and_four_steps', () => {
    /** PA-326 y PA-327: 4 casos CP-01..CP-04 sobre CA-01/CA-02 y RN-01/RN-02; 4 pasos sin «memorize». */
    const suite = QA_EXAMPLE?.review?.artifact.content as TestSuite
    expect(suite.cases.map((item) => item.internal_id)).toEqual(['CP-01', 'CP-02', 'CP-03', 'CP-04'])
    const refs = new Set(suite.cases.flatMap((item) => [...item.criterion_ids, ...item.rule_ids]))
    expect([...refs].sort()).toEqual(['CA-01', 'CA-02', 'RN-01', 'RN-02'])
    expect(QA_EXAMPLE?.progress.map((step) => step.node)).toEqual(['load_origin', 'retrieve_context', 'generate', 'publish'])
  })

  it('test_examples_json_named_example_is_not_wrapped_in_value', () => {
    /** PA-118: se copia el `value`, no el objeto de OpenAPI con summary/value. */
    expect(QA_EXAMPLE).not.toHaveProperty('value')
    expect(QA_EXAMPLE).not.toHaveProperty('summary')
  })
})

describe('mockCoverageMd / mockSuite / mockSuiteConversation', () => {
  it('test_mock_coverage_md_matches_contract_example_exactly', () => {
    /** PA-326: mockCoverageMd reproduce TestSuite.coverage_md(); con la suite del ejemplo, idéntica a la del contrato. */
    expect(mockCoverageMd(mockSuite())).toBe(QA_EXAMPLE?.review?.coverage_md)
  })

  it('test_mock_suite_defaults_to_demo_3_and_rewrites_key_and_jira_source', () => {
    /** Trazabilidad: la suite apunta a la HU pedida (story_jira_key y la fuente de Jira). */
    expect(mockSuite().story_jira_key).toBe('DEMO-3')
    const other = mockSuite('DEMO-7')
    expect(other.story_jira_key).toBe('DEMO-7')
    expect(other.sources.filter((source) => source.kind === 'jira').map((source) => source.ref)).toEqual(['DEMO-7'])
    expect(mockCoverageMd(other)).toMatch(/^# Matriz de cobertura · DEMO-7\n/)
  })

  it('test_mock_suite_returns_independent_copies', () => {
    /** Límite: cada llamada es una copia; modificar una no toca el ejemplo. */
    const first = mockSuite()
    first.cases.pop()
    expect(mockSuite().cases).toHaveLength(4)
  })

  it('test_mock_suite_conversation_uncovered_by_forced_value', () => {
    /** PA-326: por defecto el del ejemplo (vacío); gaps → MOCK_UNCOVERED; unknown → null. */
    expect(mockSuiteConversation().review?.uncovered).toEqual({ criteria: [], rules: [] })
    expect(mockSuiteConversation('DEMO-3', 'gaps').review?.uncovered).toEqual(MOCK_UNCOVERED)
    expect(mockSuiteConversation('DEMO-3', 'unknown').review?.uncovered).toBeNull()
    expect(MOCK_UNCOVERED).toEqual({ criteria: ['CA-03'], rules: ['RN-03'] })
  })

  it('test_mock_suite_conversation_gaps_is_a_copy_of_mock_uncovered', () => {
    /** Límite: modificar el `uncovered` de una conversación no cambia MOCK_UNCOVERED. */
    const review = mockSuiteConversation('DEMO-3', 'gaps').review
    review?.uncovered?.criteria.push('CA-99')
    expect(MOCK_UNCOVERED.criteria).toEqual(['CA-03'])
  })

  it('test_mock_suite_conversation_rewrites_story_key_everywhere', () => {
    /** Trazabilidad: clave de la HU en el artefacto, el destino, el plan, la matriz y el título. */
    const conversation = mockSuiteConversation('DEMO-7')
    expect(conversation.title).toBe('Preparar pruebas de DEMO-7')
    expect(conversation.review?.artifact.origin_key).toBe('DEMO-7')
    expect(conversation.review?.target.jira_key).toBe('DEMO-7')
    expect(conversation.review?.plan).toEqual([{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-7', cases: '4' }])
    expect(conversation.review?.coverage_md).toMatch(/^# Matriz de cobertura · DEMO-7\n/)
    expect((conversation.versions[0]?.artifact.content as TestSuite).story_jira_key).toBe('DEMO-7')
  })

  it('test_qa_generation_steps_are_the_four_labels_of_the_example', () => {
    /** PA-327: 4 pasos con las etiquetas del ejemplo; sin «memorize». */
    const steps = qaGenerationSteps()
    expect(steps).toEqual(QA_EXAMPLE?.progress.map(({ node, label }) => ({ node, label })))
    expect(steps.map((step) => step.node)).not.toContain('memorize')
  })

  it('test_next_suite_version_recalculates_coverage_md_with_the_new_case', () => {
    /** PA-326: al iterar, la matriz se recalcula con el caso nuevo (CP-05 sobre CA-02 y RN-02). */
    const next = nextSuiteVersion(mockSuiteConversation(), 'Añade un caso negativo')
    const suite = next.review?.artifact.content as TestSuite
    expect(next.review?.version).toBe(2)
    expect(next.review?.coverage_md).toBe(mockCoverageMd(suite))
    expect(next.review?.coverage_md).toContain('| CA-02 | CP-02, CP-05 | 2 |')
    expect(next.review?.coverage_md).toContain('| RN-02 | CP-02, CP-05 | 2 |')
    expect(next.review?.coverage_md).not.toBe(QA_EXAMPLE?.review?.coverage_md)
  })
})

describe('forcedCoverageFrom (?simular=)', () => {
  it.each([
    ['?simular=sin-cubrir', 'gaps'],
    ['?simular=cobertura-desconocida', 'unknown'],
  ] as const)('test_forced_coverage_from_recognizes_%s', (search, expected) => {
    /** PA-326: los dos valores de revisión en el navegador. */
    expect(forcedCoverageFrom(search)).toBe(expected)
  })

  it.each(['', '?simular=', '?simular=parcial', '?simular=__proto__', '?simular=constructor', '?simular=toString', '?simular=SIN-CUBRIR', '?otro=sin-cubrir'])(
    'test_forced_coverage_from_rejects_%s',
    (search) => {
      /** Solo propiedades propias: ni otro valor, ni las heredadas de Object. */
      expect(forcedCoverageFrom(search)).toBeUndefined()
    },
  )
})

describe('MSW · generación de QA (PA-326 y PA-327)', () => {
  it('test_qa_generation_emits_qa_labels_and_keeps_publish_pending', async () => {
    /** PA-327: el SSE emite load_origin/retrieve_context/generate con las etiquetas del ejemplo; publish queda pendiente. */
    const csrf = await login()
    const { created, stream, ready, lastEvent } = await generateQa(csrf)
    const labels = new Map((QA_EXAMPLE?.progress ?? []).map((step) => [step.node, step.label]))
    expect(created.progress.map((step) => step.node)).toEqual(['load_origin', 'retrieve_context', 'generate', 'publish'])
    expect(created.progress.every((step) => step.state === 'pending')).toBe(true)
    const progress = stream.filter((item) => item.event === 'progress').map((item) => item.data as ProgressStep)
    expect(progress.map((step) => `${step.node}:${step.state}`)).toEqual([
      'load_origin:running',
      'load_origin:done',
      'retrieve_context:running',
      'retrieve_context:done',
      'generate:running',
      'generate:done',
    ])
    for (const step of progress) expect(step.label).toBe(labels.get(step.node))
    expect(lastEvent).toBe('review_ready')
    expect(ready.progress).toHaveLength(4)
    expect(ready.progress.map((step) => step.node)).not.toContain('memorize')
    expect(ready.progress.find((step) => step.node === 'publish')?.state).toBe('pending')
  })

  it('test_qa_generation_ends_in_review_with_coverage_md_and_empty_uncovered', async () => {
    /** PA-326: la revisión trae la matriz (igual a mockCoverageMd) y `uncovered` vacío. */
    const csrf = await login()
    const { ready } = await generateQa(csrf)
    expect(ready).toMatchObject({ state: 'in_review', mode: 'qa', flow: 'tests' })
    expect(ready.review?.coverage_md).toBe(mockCoverageMd(ready.review?.artifact.content as TestSuite))
    expect(ready.review?.coverage_md).toBe(QA_EXAMPLE?.review?.coverage_md)
    expect(ready.review?.uncovered).toEqual({ criteria: [], rules: [] })
  })

  it('test_qa_generation_with_forced_gaps_returns_mock_uncovered', async () => {
    /** PA-326 · ?simular=sin-cubrir. */
    mockDb.forceCoverage = 'gaps'
    const csrf = await login()
    const { ready } = await generateQa(csrf)
    expect(ready.review?.uncovered).toEqual(MOCK_UNCOVERED)
  })

  it('test_qa_generation_with_forced_unknown_returns_null_uncovered', async () => {
    /** PA-326 · ?simular=cobertura-desconocida. */
    mockDb.forceCoverage = 'unknown'
    const csrf = await login()
    const { ready } = await generateQa(csrf)
    expect(ready.review?.uncovered).toBeNull()
    // La matriz sigue llegando: solo se desconoce qué queda sin caso.
    expect(ready.review?.coverage_md).toBe(QA_EXAMPLE?.review?.coverage_md)
  })

  it('test_qa_iteration_recalculates_coverage_md', async () => {
    /** PA-326: una iteración de QA devuelve la matriz recalculada con el caso nuevo. */
    const csrf = await login()
    const { created, ready } = await generateQa(csrf)
    expect((await post(`/conversations/${created.id}/iterate`, csrf, { feedback: 'Añade un caso negativo' })).status).toBe(202)
    const next = (await events(created.id)).at(-1)?.data as ConversationOut
    const suite = next.review?.artifact.content as TestSuite
    expect(next.review?.version).toBe(2)
    expect(suite.cases).toHaveLength(5)
    expect(next.review?.coverage_md).toBe(mockCoverageMd(suite))
    expect(next.review?.coverage_md).not.toBe(ready.review?.coverage_md)
    expect(next.review?.coverage_md).toContain('CP-05')
  })

  it('test_functional_generation_keeps_its_three_steps', async () => {
    /** PA-327: la HU sigue con sus 3 pasos. */
    const csrf = await login('af-demo')
    const created = (await (await post('/conversations', csrf, { origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, flow: 'evolve', excluded_sources: [], feedback: [] })).json()) as ConversationOut
    expect(created.progress.map((step) => step.node)).toEqual(['load_origin', 'retrieve_context', 'generate'])
  })
})
