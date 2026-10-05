// Suite de pruebas sintética de la API simulada (flujo de QA). El contrato aún no trae un ejemplo de conversación
// de QA en revisión (PA-326): esta sigue el esquema `TestSuite` y la HU de ejemplo (DEMO-3, CA-01/CA-02, RN-01/RN-02).
// Solo datos ficticios.
import type { ConversationOut, TestSuite } from '../api/types.ts'

export function mockSuite(storyKey: string): TestSuite {
  return {
    story_jira_key: storyKey,
    cases: [
      {
        internal_id: 'CP-01',
        title: 'Renovar un préstamo activo sin reservas',
        type: 'positivo',
        priority: 'Must',
        criterion_ids: ['CA-01'],
        rule_ids: ['RN-01'],
        preconditions: ['Persona socia ficticia con un préstamo activo y 0 renovaciones'],
        steps: [
          { action: 'Abrir «Mis préstamos» en la app', expected: 'Se ve el préstamo con el botón «Renovar»' },
          { action: 'Pulsar «Renovar»', data: 'Préstamo PR-0001 (ficticio)', expected: 'El vencimiento se amplía 21 días' },
        ],
        gherkin:
          'Escenario: Renovar un préstamo activo\n  Dado un préstamo activo con menos de 2 renovaciones\n  Y sin reservas pendientes\n  Cuando la persona socia pulsa «Renovar»\n  Entonces el vencimiento se amplía 21 días',
      },
      {
        internal_id: 'CP-02',
        title: 'Rechazar la renovación con reservas pendientes',
        type: 'negativo',
        priority: 'Must',
        criterion_ids: ['CA-02'],
        rule_ids: ['RN-02'],
        preconditions: ['Préstamo activo con una reserva pendiente de otra persona socia ficticia'],
        steps: [{ action: 'Pulsar «Renovar»', data: 'Préstamo PR-0002 (ficticio)', expected: 'Aviso «El ejemplar tiene reservas pendientes» y sin cambios' }],
        gherkin:
          'Escenario: Renovación rechazada por reservas\n  Dado un préstamo activo con reservas pendientes\n  Cuando la persona socia pulsa «Renovar»\n  Entonces se muestra el aviso «El ejemplar tiene reservas pendientes»',
      },
      {
        internal_id: 'CP-03',
        title: 'Rechazar la tercera renovación',
        type: 'alterno',
        priority: 'Should',
        criterion_ids: ['CA-01'],
        rule_ids: ['RN-01'],
        preconditions: ['Préstamo activo con 2 renovaciones ya hechas'],
        steps: [{ action: 'Pulsar «Renovar»', data: 'Préstamo PR-0003 (ficticio)', expected: 'Aviso de máximo de renovaciones y sin cambios' }],
        gherkin: null,
      },
      {
        internal_id: 'CP-04',
        title: 'Renovar sin conexión con el catálogo',
        type: 'excepcion',
        priority: 'Could',
        criterion_ids: ['CA-01'],
        rule_ids: [],
        preconditions: ['El servicio de catálogo no responde (entorno de pruebas)'],
        steps: [{ action: 'Pulsar «Renovar»', expected: 'Mensaje de error recuperable; el préstamo no cambia' }],
        gherkin: null,
      },
    ],
    strategy_md:
      '## Alcance\nRenovación de préstamos en la web y la app.\n\n## Niveles\nFuncional y regresión de reservas (DEMO-2).\n\n## Entornos\nPreproducción con datos ficticios.\n\n## Criterios\nEntrada: HU aprobada. Salida: CA-01 y CA-02 cubiertos y sin defectos críticos.',
    synthetic_data: [
      { socio: 'SOC-0001 (ficticio)', prestamo: 'PR-0001', renovaciones: '0', reservas: '0' },
      { socio: 'SOC-0002 (ficticio)', prestamo: 'PR-0002', renovaciones: '0', reservas: '1' },
      { socio: 'SOC-0003 (ficticio)', prestamo: 'PR-0003', renovaciones: '2', reservas: '0' },
    ],
    risks: ['Las reservas de DEMO-2 cambian el resultado de la renovación'],
    dependencies: ['Servicio de catálogo para comprobar reservas'],
    impact_areas: ['Préstamos', 'Reservas'],
    sources: [
      { kind: 'jira', ref: storyKey },
      { kind: 'rag', ref: 'DOC-01' },
    ],
  }
}

/** Conversación de QA en revisión a partir de la de ejemplo: la suite como artefacto y `publish_suite` en el plan. */
export function mockSuiteConversation(base: ConversationOut, storyKey: string): ConversationOut {
  const next = structuredClone(base)
  const suite = mockSuite(storyKey)
  if (next.review) {
    next.review.artifact = { ...next.review.artifact, type: 'test_suite', origin_key: storyKey, content: suite, impact: null }
    next.review.impact = null
    next.review.plan = [{ op: 'publish_suite', project: 'DEMO', story: storyKey, cases: String(suite.cases.length) }]
    next.review.fingerprint = 'huella-suite-ficticia'
    // Una suite recién generada es la versión 1 (el ejemplo de la HU va por la v2).
    next.review.version = 1
    next.review.artifact.version = 1
  }
  const artifact = next.review?.artifact
  next.versions = next.versions.slice(0, 1).map((item) => ({ ...item, version: 1, artifact: artifact ?? item.artifact }))
  next.flow = 'tests'
  next.mode = 'qa'
  next.jira_baseline = null
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

/** Versión siguiente de la suite simulada: añade un caso con lo pedido (la API real lo genera con el LLM). */
export function nextSuiteVersion(previous: ConversationOut, feedback: string): ConversationOut {
  const next = structuredClone(previous)
  const review = next.review
  if (!review) return next
  const version = review.version + 1
  const suite = review.artifact.content as TestSuite
  const id = `CP-${String(suite.cases.length + 1).padStart(2, '0')}`
  suite.cases.push({
    internal_id: id,
    title: feedback.trim().slice(0, 80) || 'Caso nuevo',
    type: requestedType(feedback),
    priority: 'Should',
    criterion_ids: ['CA-02'],
    rule_ids: ['RN-02'],
    preconditions: ['Datos ficticios de la suite'],
    steps: [{ action: 'Repetir la renovación con los datos del caso', expected: 'El resultado coincide con lo pedido' }],
    gherkin: null,
  })
  review.version = version
  review.fingerprint = `huella-suite-ficticia-${crypto.randomUUID()}`
  review.artifact = { ...review.artifact, version, content: suite }
  review.plan = review.plan.map((item) => (item.op === 'publish_suite' ? { ...item, cases: String(suite.cases.length) } : item))
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
