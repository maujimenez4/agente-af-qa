// API simulada · Editar a mano la suite (PA-158): los rechazos como `_edit` con un `TestSuite` y la versión nueva con la
// cobertura recalculada. Datos sintéticos (la suite de DEMO-3 del ejemplo del contrato).
import { describe, expect, it } from 'vitest'
import type { ReviewPayload, TestSuite } from '../api/types.ts'
import { editedSuiteConversation, invalidSuiteFields, SUITE_UNCHANGED, suiteEditProblem } from './editSuite.ts'
import { mockSuiteConversation } from './qaSuite.ts'

const conversation = (forced?: 'gaps' | 'unknown') => mockSuiteConversation('DEMO-3', forced)
const reviewOf = (forced?: 'gaps' | 'unknown') => conversation(forced).review as ReviewPayload
const edited = (recipe: (suite: TestSuite) => void, review = reviewOf()) => {
  const suite = structuredClone(review.artifact.content) as TestSuite
  recipe(suite)
  return suite
}

describe('editSuite · rechazos como _edit', () => {
  it('sin cambios, o con la clave de la HU cambiada', () => {
    expect(suiteEditProblem(reviewOf(), edited(() => {}))).toBe(SUITE_UNCHANGED)
    expect(suiteEditProblem(reviewOf(), edited((s) => (s.story_jira_key = 'DEMO-4')))).toBe('El campo story_jira_key no se puede cambiar al editar.')
  })

  it('el esquema: id, título, al menos un CA y pasos completos', () => {
    const suite = edited((s) => {
      const first = s.cases[0]
      if (!first) return
      first.internal_id = 'CP4'
      first.title = ''
      first.criterion_ids = []
      first.steps = [{ action: '', data: null, expected: '' }]
    })
    expect(invalidSuiteFields(suite)).toEqual(['cases.0.criterion_ids', 'cases.0.internal_id', 'cases.0.steps.0.action', 'cases.0.steps.0.expected', 'cases.0.title'])
    expect(suiteEditProblem(reviewOf(), suite)).toMatch(/^El contenido editado no es válido; revisa: /)
  })

  it('CA y RN que no existen en la HU, y falta de positivo o negativo', () => {
    const suite = edited((s) => {
      const [first, second] = s.cases
      if (first) first.criterion_ids = ['CA-09']
      if (second) second.type = 'alterno'
    })
    expect(suiteEditProblem(reviewOf(), suite)).toBe(
      'La edición no se puede guardar: CP-01 referencia CA/RN que no existen en la HU: CA-09; faltan casos de tipo: negativo.',
    )
  })

  it('sin saber la HU (uncovered null) no comprueba que existan', () => {
    const review = reviewOf('unknown')
    expect(suiteEditProblem(review, edited((s) => s.cases[0] && (s.cases[0].criterion_ids = ['CA-09']), review))).toBeUndefined()
  })
})

describe('editSuite · versión editada', () => {
  it('versión siguiente, edited, huella nueva y uncovered recalculado (un CA sin caso no impide guardar)', () => {
    const before = conversation()
    const review = before.review as ReviewPayload
    const suite = edited((s) => s.cases[1] && (s.cases[1].criterion_ids = ['CA-01']))
    expect(suiteEditProblem(review, suite)).toBeUndefined()
    const after = editedSuiteConversation(before, suite)
    expect(after.review?.version).toBe(review.version + 1)
    expect(after.review?.fingerprint).not.toBe(review.fingerprint)
    expect(after.review?.uncovered).toEqual({ criteria: ['CA-02'], rules: [] })
    expect(after.review?.coverage_md).toContain('| CA-01 | CP-01, CP-02, CP-03, CP-04 | 4 |')
    expect(after.versions.at(-1)).toMatchObject({ version: review.version + 1, edited: true })
  })

  it('con uncovered null sigue sin saberse', () => {
    const before = conversation('unknown')
    const suite = edited((s) => s.cases[0] && (s.cases[0].title = 'Título ficticio'), before.review as ReviewPayload)
    expect(editedSuiteConversation(before, suite).review?.uncovered).toBeNull()
  })
})
