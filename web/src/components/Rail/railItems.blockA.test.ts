// Bloque A (T-56): el anillo del carril usa formatNumber (separador de miles con cuatro cifras, §4 bis).
import { describe, expect, it } from 'vitest'
import { usageView } from './railItems.ts'

describe('usageView con formatNumber (bloque A)', () => {
  it('el nombre accesible del anillo agrupa los miles también con cuatro cifras', () => {
    /** §4 bis: «Los números llevan separador de miles también con cuatro cifras, como en el anillo del carril». */
    const view = usageView({ tokens_today: 2350, warning_threshold: 8000 })
    expect(view?.label).toBe('Consumo de tokens de hoy de todas las personas que usan FAQ: 2.350 de 8.000, 29 % del umbral de aviso')
  })

  it('con cinco o más cifras sigue agrupando', () => {
    /** Límite: números grandes del consumo de toda la instalación. */
    expect(usageView({ tokens_today: 123456, warning_threshold: 100000 })?.label).toContain(': 123.456 de 100.000,')
  })
})
