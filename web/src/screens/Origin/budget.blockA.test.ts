// Bloque A (T-56): budgetView con valores límite (DESIGN-DECISIONS.md §4 bis, Origen: presupuesto, PA-102).
import { describe, expect, it } from 'vitest'
import type { ContextBudget } from '../../api/types.ts'
import { BUDGET_DEBOUNCE_MS, BUDGET_WARNING_PERCENT, budgetView } from './budget.ts'

const budget = (used: number, limit = 6000, dropped = 0, truncated = 0): ContextBudget => ({
  used,
  limit,
  dropped_sources: dropped,
  truncated_sources: truncated,
})

describe('budgetView: valores límite (bloque A)', () => {
  it('las constantes son las de §4 bis: aviso desde el 90 % y 300 ms entre clics', () => {
    expect(BUDGET_WARNING_PERCENT).toBe(90)
    expect(BUDGET_DEBOUNCE_MS).toBe(300)
  })

  it('exactamente el 90 % avisa y la barra marca 90', () => {
    /** §4 bis: «Aviso desde el 90 %» (límite inclusivo). */
    expect(budgetView(budget(5400))).toMatchObject({ percent: 90, warning: true, notes: [] })
  })

  it('el 89 % no avisa', () => {
    /** §4 bis (negativo): por debajo del 90 % y sin fuentes descartadas, sin aviso. */
    expect(budgetView(budget(5340))).toMatchObject({ percent: 89, warning: false })
  })

  // Fija un fallo ya corregido al cerrar el bloque A. Antes: budget.ts:45 compara el porcentaje YA REDONDEADO (`percent >= 90`), así que 5.399 de 6.000
  // (89,98 %) avisa como si estuviera al 90 %. El anillo del carril compara los tokens sin redondear
  // (railItems.ts, `tokens >= threshold`). Esperado: sin aviso por debajo del 90 % exacto.
  it('justo por debajo del 90 % (5.399 de 6.000) no avisa', () => {
    /** §4 bis: «Aviso … desde el 90 %». */
    expect(budgetView(budget(5399))?.warning).toBe(false)
  })

  it('el presupuesto lleno (used = limit) marca 100 y avisa', () => {
    expect(budgetView(budget(6000))).toMatchObject({ percent: 100, warning: true, label: 'Contexto · 6.000 de 6.000 tokens' })
  })

  it('con 0 usados la barra está vacía y no avisa', () => {
    expect(budgetView(budget(0))).toEqual({ label: 'Contexto · 0 de 6.000 tokens', percent: 0, warning: false, notes: [] })
  })

  it('solo recortadas no avisa (el aviso es por fuentes que no caben o por el 90 %)', () => {
    /** §4 bis: el aviso sale «desde el 90 % o si hay fuentes que no caben»; las recortadas solo añaden su frase. */
    const view = budgetView(budget(1000, 6000, 0, 3))
    expect(view?.warning).toBe(false)
    expect(view?.notes).toEqual(['3 incidencias se recortan para que quepan.'])
  })

  it('una sola fuente descartada avisa aunque el presupuesto esté casi vacío', () => {
    expect(budgetView(budget(10, 6000, 1, 0))).toMatchObject({ warning: true, notes: ['1 fuente no cabe y no se enviará al modelo.'] })
  })

  it('los recuentos grandes de fuentes llevan separador de miles', () => {
    expect(budgetView(budget(100, 6000, 1200, 0))?.notes).toEqual(['1.200 fuentes no caben y no se enviarán al modelo.'])
  })

  it('límites grandes se formatean con separador de miles', () => {
    expect(budgetView(budget(12345, 128000))?.label).toBe('Contexto · 12.345 de 128.000 tokens')
  })

  it.each([
    ['límite negativo', budget(10, -1)],
    ['límite infinito', budget(10, Number.POSITIVE_INFINITY)],
    ['usados infinitos', budget(Number.POSITIVE_INFINITY)],
    ['descartadas NaN', budget(10, 6000, Number.NaN)],
    ['recortadas NaN', budget(10, 6000, 0, Number.NaN)],
  ])('con un presupuesto no válido (%s) no pinta nada', (_case, value) => {
    /** §4 bis (error): nunca se pinta un presupuesto inventado. */
    expect(budgetView(value)).toBeUndefined()
  })
})
