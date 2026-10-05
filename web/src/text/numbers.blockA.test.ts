// Bloque A (T-56): formatNumber, separador de miles también con cuatro cifras (DESIGN-DECISIONS.md §4 bis,
// Origen: presupuesto). Valores sintéticos.
import { describe, expect, it } from 'vitest'
import { formatNumber } from './numbers.ts'

describe('formatNumber (bloque A)', () => {
  it.each([
    [0, '0'],
    [999, '999'],
    [1000, '1.000'],
    [2350, '2.350'],
    [6000, '6.000'],
    [1234567, '1.234.567'],
  ])('agrupa los miles con punto también por debajo de 10.000: %d → %s', (value, text) => {
    /** §4 bis: «2.350», no «2350». */
    expect(formatNumber(value)).toBe(text)
  })

  it.each([
    [-5, '-5'],
    [-2350, '-2.350'],
    [-1234567, '-1.234.567'],
  ])('los negativos llevan signo y separador de miles: %d → %s', (value, text) => {
    /** Límite: un número negativo no pierde el separador de miles. */
    expect(formatNumber(value)).toBe(text)
  })

  it.each([
    [0.5, '0,5'],
    [1234.5, '1.234,5'],
    [-1234.25, '-1.234,25'],
    [1234.5678, '1.234,568'],
  ])('los decimales usan coma y se redondean a tres cifras: %d → %s', (value, text) => {
    /** Límite: coma decimal en es-ES, sin mezclar con el punto de los miles. */
    expect(formatNumber(value)).toBe(text)
  })
})
