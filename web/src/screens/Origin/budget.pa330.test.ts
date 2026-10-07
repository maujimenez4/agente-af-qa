// PA-330 (T-56): presupuesto rápido en Origen, funciones puras de budget.ts: estimación con `SourcePreview.tokens`,
// etiqueta de la estimación, cuándo la confirmación difiere y la línea de `fixed`. Datos sintéticos (DEMO, DOC-xx).
import { describe, expect, it } from 'vitest'
import type { ContextBudget, SourcePreview } from '../../api/types.ts'
import { budgetView, differsFromEstimate, estimateUsed, fixedNote, REFILL_NOTE } from './budget.ts'

const source = (ref: string, tokens: number | null | undefined, required = false): SourcePreview => {
  const base: SourcePreview = { ref, kind: required ? 'jira' : 'rag', title: `Fuente ficticia ${ref}`, category: null, required }
  return tokens === undefined ? base : { ...base, tokens }
}

const SOURCES: SourcePreview[] = [source('DEMO-3', 900, true), source('DOC-01', 450), source('DOC-08', 300), source('memoria-DEMO-2', 550)]

const budget = (used: number, limit = 6000, extra: Partial<ContextBudget> = {}): ContextBudget => ({
  used,
  limit,
  dropped_sources: 0,
  truncated_sources: 0,
  ...extra,
})

describe('estimateUsed (PA-330, criterio 1)', () => {
  it('test_estimate_sums_tokens_when_all_sources_are_checked', () => {
    /** Criterio 1: suma `tokens` de todas las fuentes marcadas. */
    expect(estimateUsed(SOURCES, [])).toBe(2200)
  })

  it('test_estimate_skips_excluded_sources_when_unchecked', () => {
    /** Criterio 1: las desmarcadas no cuentan. */
    expect(estimateUsed(SOURCES, ['DOC-01'])).toBe(1750)
    expect(estimateUsed(SOURCES, ['DOC-01', 'memoria-DEMO-2'])).toBe(1200)
  })

  it('test_estimate_counts_required_sources_when_excluded_by_mistake', () => {
    /** Criterio 1: las obligatorias cuentan siempre, aunque lleguen en las exclusiones. */
    expect(estimateUsed(SOURCES, ['DEMO-3'])).toBe(2200)
    expect(estimateUsed(SOURCES, ['DEMO-3', 'DOC-01', 'DOC-08', 'memoria-DEMO-2'])).toBe(900)
  })

  it('test_estimate_ignores_unknown_refs_when_excluded', () => {
    /** Criterio 1 (límite): una ref que no está en la lista no resta nada. */
    expect(estimateUsed(SOURCES, ['DOC-99'])).toBe(2200)
  })

  it('test_estimate_is_zero_when_source_tokens_are_zero', () => {
    /** Criterio 1 (límite): 0 tokens es un dato válido, no «sin dato». */
    expect(estimateUsed([source('DEMO-3', 0, true), source('DOC-01', 0)], [])).toBe(0)
  })

  it.each([
    ['null', null],
    ['ausente', undefined],
    ['NaN', Number.NaN],
    ['infinito', Number.POSITIVE_INFINITY],
  ])('test_estimate_is_undefined_when_a_source_has_tokens_%s', (_label, tokens) => {
    /** Criterio 1 (negativo): basta una fuente sin `tokens` válidos (API anterior) para no estimar. */
    expect(estimateUsed([...SOURCES, source('DOC-20', tokens)], [])).toBeUndefined()
  })

  it('test_estimate_is_undefined_when_the_source_without_tokens_is_excluded', () => {
    /** Criterio 1 (negativo): aunque la fuente sin `tokens` esté desmarcada, tampoco se estima. */
    expect(estimateUsed([...SOURCES, source('DOC-20', null)], ['DOC-20'])).toBeUndefined()
  })

  it('test_estimate_is_undefined_when_a_source_has_negative_tokens', () => {
    /** security-reviewer (BAJO): un `tokens` negativo no da una estimación por debajo de lo real; se espera a la confirmación. */
    expect(estimateUsed([{ ref: 'DOC-01', kind: 'rag', title: 'Fuente ficticia', required: false, tokens: -50 }], [])).toBeUndefined()
  })

  it('test_estimate_is_undefined_when_there_are_no_sources', () => {
    /** Criterio 1 (límite): sin fuentes no hay estimación. */
    expect(estimateUsed([], [])).toBeUndefined()
    expect(estimateUsed([], ['DOC-01'])).toBeUndefined()
  })
})

describe('budgetView con estimación (PA-330, criterio 2)', () => {
  it('test_view_shows_estimate_label_when_estimate_is_given', () => {
    /** Criterio 2: «Contexto · ≈ N de L tokens · estimación», con separador de miles. */
    expect(budgetView(budget(2800), 2350)).toEqual({
      label: 'Contexto · ≈ 2.350 de 6.000 tokens · estimación',
      percent: 39,
      warning: false,
      notes: [],
    })
  })

  it('test_view_uses_estimate_not_budget_used_when_estimate_is_given', () => {
    /** Criterio 2: la barra y el aviso salen de la estimación, no del uso confirmado anterior. */
    expect(budgetView(budget(5900), 1200)).toMatchObject({ percent: 20, warning: false })
    expect(budgetView(budget(100), 5400)).toMatchObject({ percent: 90, warning: true })
  })

  it('test_view_clamps_percent_when_estimate_is_out_of_range', () => {
    /** Criterio 2 (límite): la barra queda en 0–100 y la etiqueta no baja de 0. */
    expect(budgetView(budget(2800), 9000)).toMatchObject({
      percent: 100,
      warning: true,
      label: 'Contexto · ≈ 9.000 de 6.000 tokens · estimación',
    })
    expect(budgetView(budget(2800), -50)).toMatchObject({
      percent: 0,
      warning: false,
      label: 'Contexto · ≈ 0 de 6.000 tokens · estimación',
    })
  })

  it('test_view_warns_from_90_percent_when_estimating', () => {
    /** Criterio 2 (límite): 5.400 de 6.000 (90 %) avisa; 5.399 (89,98 %) no, aunque la barra redondee a 90. */
    expect(budgetView(budget(0), 5400)?.warning).toBe(true)
    expect(budgetView(budget(0), 5399)).toMatchObject({ percent: 90, warning: false })
  })

  it('test_view_drops_server_notes_when_estimating', () => {
    /** Criterio 2: las notas de descartadas/recortadas son de la consulta anterior; con estimación no salen ni avisan. */
    const view = budgetView(budget(6000, 6000, { dropped_sources: 2, truncated_sources: 1 }), 3000)
    expect(view).toMatchObject({ notes: [], warning: false })
  })

  it('test_view_is_undefined_when_budget_is_missing_even_with_estimate', () => {
    /** Criterio 2 (negativo) y 9: sin presupuesto válido no se pinta la estimación. */
    expect(budgetView(undefined, 2350)).toBeUndefined()
    expect(budgetView(budget(10, 0), 2350)).toBeUndefined()
    expect(budgetView(budget(Number.NaN), 2350)).toBeUndefined()
  })

  it('test_view_falls_back_to_confirmed_when_estimate_is_not_finite', () => {
    /** Criterio 2 (negativo): una estimación NaN no se pinta; queda el presupuesto confirmado. */
    expect(budgetView(budget(2800), Number.NaN)?.label).toBe('Contexto · 2.800 de 6.000 tokens')
  })
})

describe('differsFromEstimate (PA-330, criterio 3)', () => {
  it('test_differs_is_true_when_gap_exceeds_one_percent_of_limit', () => {
    /** Criterio 3: más de un 1 % del límite (60 de 6.000) en cualquier sentido. */
    expect(differsFromEstimate(budget(2550), 2350)).toBe(true)
    expect(differsFromEstimate(budget(2289), 2350)).toBe(true)
    expect(differsFromEstimate(budget(2411), 2350)).toBe(true)
  })

  it('test_differs_is_false_when_gap_is_exactly_one_percent', () => {
    /** Criterio 3 (límite): 60 de 6.000 exactos no cuentan. */
    expect(differsFromEstimate(budget(2410), 2350)).toBe(false)
    expect(differsFromEstimate(budget(2290), 2350)).toBe(false)
  })

  it('test_differs_is_false_when_values_match_or_gap_is_small', () => {
    /** Criterio 3 (negativo): iguales o con diferencias que nadie ve. */
    expect(differsFromEstimate(budget(2350), 2350)).toBe(false)
    expect(differsFromEstimate(budget(2359), 2350)).toBe(false)
  })

  it.each([
    ['sin presupuesto', undefined, 2350],
    ['sin estimación', budget(2550), undefined],
    ['uso NaN', budget(Number.NaN), 2350],
    ['límite 0', budget(2550, 0), 2350],
    ['límite negativo', budget(2550, -6000), 2350],
    ['límite NaN', budget(2550, Number.NaN), 2350],
  ])('test_differs_is_false_when_data_is_invalid_%s', (_label, value, estimate) => {
    /** Criterio 3 (negativo): con datos no válidos, nunca sale la nota. */
    expect(differsFromEstimate(value, estimate)).toBe(false)
  })

  it('test_refill_note_states_that_the_confirmed_figure_counts', () => {
    /** Criterio 5: el texto de la nota que acompaña a una confirmación distinta. */
    expect(REFILL_NOTE).toBe('Al quitar un documento puede entrar otro relacionado en su lugar: la cifra confirmada es la que cuenta.')
  })
})

describe('fixedNote (PA-330, criterio 4)', () => {
  it('test_fixed_note_includes_total_with_thousands_separator_when_both_given', () => {
    /** Criterio 4: con `fixed > 0` y `total`, ambos con separador de miles. */
    expect(fixedNote(budget(2800, 6000, { fixed: 1300, total: 7300 }))).toBe(
      'El texto de la necesidad ocupa 1.300 tokens aparte del total de 7.300.',
    )
    expect(fixedNote(budget(2800, 6000, { fixed: 300, total: 6300 }))).toBe(
      'El texto de la necesidad ocupa 300 tokens aparte del total de 6.300.',
    )
  })

  it.each([
    ['ausente', {}],
    ['null', { total: null }],
    ['0', { total: 0 }],
    ['NaN', { total: Number.NaN }],
  ])('test_fixed_note_omits_total_when_total_is_%s', (_label, extra) => {
    /** Criterio 4: sin `total` válido, sin la parte «del total de…». */
    expect(fixedNote(budget(2800, 6000, { fixed: 1300, ...extra }))).toBe('El texto de la necesidad ocupa 1.300 tokens aparte.')
  })

  it.each([
    ['0', { fixed: 0, total: 6000 }],
    ['null', { fixed: null, total: 6300 }],
    ['ausente', { total: 6300 }],
    ['negativo', { fixed: -10, total: 6300 }],
    ['NaN', { fixed: Number.NaN, total: 6300 }],
  ])('test_fixed_note_is_undefined_when_fixed_is_%s', (_label, extra) => {
    /** Criterio 4 (negativo): sin `fixed` positivo no hay línea. */
    expect(fixedNote(budget(2800, 6000, extra))).toBeUndefined()
  })

  it('test_fixed_note_is_undefined_when_budget_is_missing', () => {
    /** Criterio 4 (negativo): sin presupuesto, sin línea. */
    expect(fixedNote(undefined)).toBeUndefined()
  })
})
