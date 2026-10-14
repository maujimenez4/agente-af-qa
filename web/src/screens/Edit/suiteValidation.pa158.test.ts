// Editar a mano la suite (PA-158): el borrador y la validación con las reglas del backend (schemas/test_case.py, `_edit`
// y `blocking_errors`), la HU deducida de la revisión y la cobertura en vivo. Datos sintéticos (la suite de DEMO-3 del
// ejemplo del contrato: CP-01…CP-04 sobre CA-01, CA-02, RN-01 y RN-02).
import { describe, expect, it } from 'vitest'
import type { TestSuite } from '../../api/types.ts'
import { mockSuite } from '../../mocks/qaSuite.ts'
import { caseRefs, fromSuiteDraft, nextCaseId, splitRefs, toSuiteDraft, type SuiteDraft } from './suiteDraft.ts'
import { checkSuite, liveCoverage, liveCoverageText, sameSuite, storyRefs, type StoryRefs } from './suiteValidation.ts'

const REFS: StoryRefs = { criteria: ['CA-01', 'CA-02'], rules: ['RN-01', 'RN-02'] }

/** La suite del ejemplo, editada en su borrador, y su comprobación. */
function check(recipe: (draft: SuiteDraft) => void = () => {}, refs: StoryRefs = REFS, note = '') {
  const original = mockSuite()
  const draft = toSuiteDraft(original)
  recipe(draft)
  const content = fromSuiteDraft(draft, original)
  return { original, draft, content, result: checkSuite(content, original, draft, refs, note) }
}
const errorAt = (result: ReturnType<typeof check>['result'], path: string) => result.errors.find((item) => item.path === path)?.message
const caseAt = (draft: SuiteDraft, id: string) => {
  const found = draft.cases.find((item) => item.internal_id === id)
  if (!found) throw new Error(`no está ${id}`)
  return found
}

describe('Borrador de la suite', () => {
  it('ida y vuelta sin tocar nada: la misma suite, y la validación dice que no hay cambios', () => {
    const { original, content, result } = check()
    expect(sameSuite(content, original)).toBe(true)
    expect(result.errors.map((item) => item.path)).toEqual(['unchanged'])
  })

  it('un campo ausente cuenta igual que su valor por defecto (como compara _edit)', () => {
    const original = mockSuite()
    const sparse = structuredClone(original) as TestSuite
    for (const item of sparse.cases) {
      if ((item.rule_ids ?? []).length === 0) delete (item as Partial<typeof item>).rule_ids
    }
    expect(sameSuite(sparse, original)).toBe(true)
  })

  it('«Verifica» separa los CA de las RN y admite comas, espacios y saltos de línea', () => {
    expect(splitRefs('CA-01, RN-02\nCA-03  RN-04;')).toEqual(['CA-01', 'RN-02', 'CA-03', 'RN-04'])
    expect(caseRefs('CA-01, RN-02, CA-03')).toEqual({ criterion_ids: ['CA-01', 'CA-03'], rule_ids: ['RN-02'] })
  })

  it('el siguiente id libre es CP-NN con el ancho de los que hay', () => {
    expect(nextCaseId(['CP-01', 'CP-04'])).toBe('CP-05')
    expect(nextCaseId([])).toBe('CP-01')
    expect(nextCaseId(['CP-099'])).toBe('CP-100')
  })

  it('una columna existente sin nombre y sin valores no se envía', () => {
    const { content, result } = check((draft) => {
      const last = draft.columns[2]
      if (!last) return
      last.name = ''
      for (const row of draft.rows) row.values[last.key] = ''
    })
    expect(content.synthetic_data?.[0]).toEqual({ prestamo: 'PR-0001', renovaciones: '0' })
    expect(result.warnings.find((item) => item.path === 'data.columns.2')?.message).toBe('La columna 3 de los datos no tiene nombre ni valores: no se enviará.')
  })

  it('los datos sintéticos vuelven con las mismas columnas y una columna nueva con valor se añade', () => {
    const { content } = check((draft) => {
      const column = { key: 'nueva', name: 'motivo' }
      draft.columns.push(column)
      const first = draft.rows[0]
      if (first) first.values[column.key] = 'ficticio'
    })
    expect(content.synthetic_data?.[0]).toEqual({ prestamo: 'PR-0001', renovaciones: '0', reservas: '0', motivo: 'ficticio' })
    expect(content.synthetic_data?.[1]).toEqual({ prestamo: 'PR-0002', renovaciones: '0', reservas: '1' })
  })
})

describe('Validación como el backend', () => {
  it('ids vacíos, mal formados y repetidos, junto a su campo', () => {
    const { result } = check((draft) => {
      caseAt(draft, 'CP-02').internal_id = 'CP-01'
      caseAt(draft, 'CP-03').internal_id = ''
      caseAt(draft, 'CP-04').internal_id = 'CP4'
    })
    expect(errorAt(result, 'cases.0.id')).toBe('El identificador CP-01 está repetido.')
    expect(errorAt(result, 'cases.1.id')).toBe('El identificador CP-01 está repetido.')
    expect(errorAt(result, 'cases.2.id')).toBe('El caso 3: el identificador debe ser «CP-» y un número (por ejemplo, CP-05).')
    expect(errorAt(result, 'cases.3.id')).toBe('CP4: el identificador debe ser «CP-» y un número (por ejemplo, CP-05).')
  })

  it('al menos un caso positivo y uno negativo', () => {
    const { result } = check((draft) => {
      caseAt(draft, 'CP-02').type = 'alterno'
    })
    expect(errorAt(result, 'types')).toBe('La suite necesita al menos un caso negativo.')
    const both = check((draft) => {
      for (const item of draft.cases) item.type = 'alterno'
    })
    expect(errorAt(both.result, 'types')).toBe('La suite necesita al menos un caso positivo y uno negativo.')
  })

  it('referencias solo a CA y RN que existen en la HU, con formato y al menos un CA', () => {
    const { result } = check((draft) => {
      caseAt(draft, 'CP-01').refs = 'CA-01, CA-09, RN-07'
      caseAt(draft, 'CP-02').refs = 'RN-02'
      caseAt(draft, 'CP-03').refs = 'CA-01, X-1'
    })
    expect(errorAt(result, 'cases.0.refs')).toBe('CA-09 y RN-07 no existen en la HU.')
    expect(errorAt(result, 'cases.1.refs')).toBe('CP-02 necesita verificar al menos un CA.')
    expect(errorAt(result, 'cases.2.refs')).toBe('«X-1» no es un CA ni una RN (escribe, por ejemplo, CA-01 o RN-02).')
  })

  it('sin saber la HU (uncovered null) solo se comprueba el formato, no que existan', () => {
    const { result } = check((draft) => {
      caseAt(draft, 'CP-01').refs = 'CA-09'
    }, null)
    expect(errorAt(result, 'cases.0.refs')).toBeUndefined()
    expect(result.errors).toEqual([])
  })

  it('título, al menos un paso y acción y resultado en cada paso', () => {
    const { result } = check((draft) => {
      const first = caseAt(draft, 'CP-01')
      first.title = ''
      const step = first.steps[0]
      if (step) {
        step.action = ''
        step.expected = ''
      }
      caseAt(draft, 'CP-02').steps = []
    })
    expect(errorAt(result, 'cases.0.title')).toBe('CP-01 necesita un título.')
    expect(errorAt(result, 'cases.0.steps.0.action')).toBe('CP-01, paso 1: falta la acción.')
    expect(errorAt(result, 'cases.0.steps.0.expected')).toBe('CP-01, paso 1: falta el resultado esperado.')
    expect(errorAt(result, 'cases.1.steps')).toBe('CP-02 necesita al menos un paso.')
  })

  it('columnas de datos con valores necesitan nombre y no pueden repetirse', () => {
    const { result } = check((draft) => {
      const [first, second] = draft.columns
      if (first && second) {
        first.name = ''
        second.name = 'reservas'
      }
    })
    expect(errorAt(result, 'data.columns.0')).toBe('La columna 1 de los datos necesita un nombre.')
    expect(errorAt(result, 'data.columns.1')).toBe('La columna «reservas» está repetida.')
    expect(errorAt(result, 'data.columns.2')).toBe('La columna «reservas» está repetida.')
  })

  it('una nota de más de 1.000 caracteres no se puede guardar', () => {
    const { result } = check((draft) => {
      caseAt(draft, 'CP-01').title = 'Renovar con un título ficticio'
    }, REFS, 'x'.repeat(1001))
    expect(errorAt(result, 'note')).toBe('La nota no puede pasar de 1000 caracteres.')
  })
})

describe('Cobertura en vivo', () => {
  it('la HU se deduce de la revisión: lo referenciado más lo que uncovered da sin caso', () => {
    expect(storyRefs(mockSuite(), { criteria: ['CA-03'], rules: ['RN-03'] })).toEqual({ criteria: ['CA-01', 'CA-02', 'CA-03'], rules: ['RN-01', 'RN-02', 'RN-03'] })
    expect(storyRefs(mockSuite(), null)).toBeNull()
  })

  it('quitar el único caso de un CA: falta un caso, se puede guardar y avisa de que bloquea la aprobación', () => {
    const { content, result } = check((draft) => {
      caseAt(draft, 'CP-02').refs = 'CA-01, RN-02'
    })
    expect(liveCoverage(content, REFS)).toEqual({ kind: 'gaps', criteria: ['CA-02'], rules: [] })
    expect(result.errors).toEqual([])
    expect(result.warnings.find((item) => item.path === 'coverage.criteria')?.message).toBe('Falta un caso para CA-02: podrás guardar, pero no aprobar la suite.')
    expect(liveCoverageText(liveCoverage(content, REFS))).toEqual({
      tone: 'warning',
      lines: ['Falta un caso para CA-02. Podrás guardar, pero no aprobar la suite hasta que cada CA tenga un caso.'],
    })
  })

  it('el único caso de una RN: solo avisa, no bloquea', () => {
    const { content, result } = check((draft) => {
      caseAt(draft, 'CP-02').refs = 'CA-02'
    })
    expect(liveCoverage(content, REFS)).toEqual({ kind: 'gaps', criteria: [], rules: ['RN-02'] })
    expect(result.errors).toEqual([])
    expect(liveCoverageText(liveCoverage(content, REFS))).toEqual({ tone: 'neutral', lines: ['Sin ningún caso: RN-02. Una RN sin caso no impide aprobar.'] })
  })

  it('todo cubierto o sin saber la HU', () => {
    expect(liveCoverageText(liveCoverage(mockSuite(), REFS)).lines).toEqual(['Cada CA y cada RN de la HU tiene al menos un caso.'])
    expect(liveCoverage(mockSuite(), null)).toEqual({ kind: 'unknown' })
  })
})
