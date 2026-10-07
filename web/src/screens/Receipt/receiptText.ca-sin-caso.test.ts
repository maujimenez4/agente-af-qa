// T-56 · pulido final, bloque 2: un CA sin caso bloquea *Aprobar y publicar* en el recibo de la suite (UI.md §6.4).
// `missingCasesLabel` y `MISSING_CASES_REASON`. Datos sintéticos (CA-0N ficticios).
import { describe, expect, it } from 'vitest'
import { MISSING_CASES_REASON, missingCasesLabel } from './receiptText.ts'

describe('missingCasesLabel (CA sin caso en la suite)', () => {
  it('test_missing_cases_label_is_undefined_without_criteria', () => {
    /** Criterio 6: con 0 CA sin caso no hay aviso. */
    expect(missingCasesLabel([])).toBeUndefined()
  })

  it('test_missing_cases_label_uses_singular_with_one_criterion', () => {
    /** Criterio 6: con 1 CA, «Falta un caso para CA-03». */
    expect(missingCasesLabel(['CA-03'])).toBe('Falta un caso para CA-03')
  })

  it('test_missing_cases_label_joins_two_criteria_with_y', () => {
    /** Criterio 6: con 2 CA, «Faltan casos para CA-02 y CA-03». */
    expect(missingCasesLabel(['CA-02', 'CA-03'])).toBe('Faltan casos para CA-02 y CA-03')
  })

  it('test_missing_cases_label_joins_three_criteria_with_commas_and_y', () => {
    /** Criterio 6: con 3 CA, «Faltan casos para CA-01, CA-02 y CA-03» (Intl.ListFormat es, sin coma de Oxford). */
    expect(missingCasesLabel(['CA-01', 'CA-02', 'CA-03'])).toBe('Faltan casos para CA-01, CA-02 y CA-03')
  })

  it('test_missing_cases_label_keeps_the_order_and_ids_as_they_come', () => {
    /** Criterio 6 (límite): el orden y el texto de los ID son los del backend; no se reordenan ni se interpretan. */
    expect(missingCasesLabel(['CA-10', 'CA-02'])).toBe('Faltan casos para CA-10 y CA-02')
    expect(missingCasesLabel(['<b>CA-9</b>'])).toBe('Falta un caso para <b>CA-9</b>')
  })

  it('test_missing_cases_label_does_not_end_with_a_period', () => {
    /** Criterio 6: el punto lo pone el recibo («Falta un caso para CA-03.»), no la etiqueta. */
    for (const criteria of [['CA-03'], ['CA-02', 'CA-03'], ['CA-01', 'CA-02', 'CA-03']]) {
      expect(missingCasesLabel(criteria)).not.toMatch(/\.$/)
    }
  })

  it('test_missing_cases_reason_explains_what_to_do', () => {
    /** Criterio 1: la razón dice por qué no se puede aprobar y qué hacer. */
    expect(MISSING_CASES_REASON).toBe(
      'Cada CA de la HU necesita al menos un caso para aprobar la suite. Vuelve a la suite y pide un caso que lo verifique.',
    )
  })
})
