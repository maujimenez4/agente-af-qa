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
