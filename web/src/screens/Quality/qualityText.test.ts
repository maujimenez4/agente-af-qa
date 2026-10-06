// Resumen de la cabecera del informe de calidad: contado sin IA a partir del veredicto, sin puntuaciones.
import { describe, expect, it } from 'vitest'
import type { InvestCheck, QualityFinding } from '../../api/types.ts'
import { reportSummary } from './qualityText.ts'

const invest = (improvable: readonly InvestCheck['letter'][] = []): InvestCheck[] =>
  (['I', 'N', 'V', 'E', 'S', 'T'] as const).map((letter) => ({
    letter,
    verdict: improvable.includes(letter) ? 'improvable' : 'ok',
    reason: `Motivo ficticio de ${letter}.`,
  }))

const finding = (kind: QualityFinding['kind']): QualityFinding => ({ kind, explanation: 'Ficticio.', proposal: 'Ficticia.' })

describe('reportSummary', () => {
  it('test_counts_invest_ok_and_findings_by_kind', () => {
    /** «INVEST: N de 6 bien» y los hallazgos por tipo, en plural cuando toca. */
    const findings = [finding('ambiguity'), finding('no_source'), finding('ambiguity')]
    expect(reportSummary({ invest: invest(['E', 'T']), findings })).toBe('INVEST: 4 de 6 bien · 2 ambigüedades · 1 sin fuente')
  })

  it('test_singular_and_kind_order_follow_finding_labels', () => {
    /** Orden fijo (Ambigüedad, Hueco, Sin fuente, INVEST, Incoherencia), no el de llegada. */
    const findings = [finding('inconsistency'), finding('invest'), finding('gap'), finding('no_source'), finding('no_source')]
    expect(reportSummary({ invest: invest(['T']), findings })).toBe(
      'INVEST: 5 de 6 bien · 1 hueco · 2 sin fuente · 1 hallazgo INVEST · 1 incoherencia con las fuentes',
    )
  })

  it('test_no_findings_and_all_invest_ok', () => {
    /** Sin hallazgos lo dice; todo «Bien» es 6 de 6. */
    expect(reportSummary({ invest: invest(), findings: [] })).toBe('INVEST: 6 de 6 bien · sin hallazgos')
  })

  it('test_missing_or_repeated_letters_are_not_invented', () => {
    /** Si la API trae menos letras (o repetidas), se cuentan las que hay, una por letra: nada inventado. */
    const partial: InvestCheck[] = [
      { letter: 'I', verdict: 'ok', reason: 'Ficticio.' },
      { letter: 'I', verdict: 'improvable', reason: 'Repetida.' },
      { letter: 'T', verdict: 'improvable', reason: 'Ficticio.' },
    ]
    expect(reportSummary({ invest: partial, findings: [] })).toBe('INVEST: 1 de 2 bien · sin hallazgos')
  })

  it('test_summary_has_no_numeric_score', () => {
    /** Ni porcentajes ni notas: solo recuentos. */
    const text = reportSummary({ invest: invest(['N']), findings: [finding('gap')] })
    expect(text).not.toMatch(/%|\/\s*10|puntuaci|nota/i)
  })
})
