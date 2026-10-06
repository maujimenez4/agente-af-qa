// Cantidades con su sustantivo en singular o en plural («1 fuente», «2 fuentes», «1.234 casos»), con el número
// en español (formatNumber). Para que no vuelva a salir «1 fuentes» o «1 criterios»: todo recuento visible pasa por aquí.
import { formatNumber } from './numbers.ts'

/** El sustantivo que toca para `count`: `one` solo con 1 (también para 0 va el plural: «0 casos»). */
export function pluralWord(count: number, one: string, many: string): string {
  return count === 1 ? one : many
}

/** «1 fuente», «2 fuentes», «0 casos». */
export function countLabel(count: number, one: string, many: string): string {
  return `${formatNumber(count)} ${pluralWord(count, one, many)}`
}
