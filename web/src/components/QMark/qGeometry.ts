import { Q_VIEWBOX } from '../../design/qPath.ts'

/** Un cuarto de la Q en unidades del viewBox. */
export const QUARTER = Q_VIEWBOX / 4

/** Desplazamiento del rect para `quarters` cuartos llenos (0 = vacía, 4 = llena). */
export function offsetFor(quarters: number): number {
  const clamped = Math.min(Math.max(quarters, 0), 4)
  return Q_VIEWBOX - clamped * QUARTER
}

export type Phase = 1 | 2 | 3 | 4

// UI.md §2 y decisión 8.
export const PHASE_NAMES: Record<Phase, string> = {
  1: 'Contexto',
  2: 'Generar',
  3: 'Revisión',
  4: 'Publicado',
}

// Escritura simulada (DESIGN-DECISIONS.md §3): 2 caracteres cada 35 ms y nunca más de 1,5 s en total.
export const TICK_MS = 35
export const MAX_DURATION_MS = 1500
const MIN_CHARS_PER_TICK = 2

export function charsPerTick(length: number): number {
  return Math.max(MIN_CHARS_PER_TICK, Math.ceil(length / Math.floor(MAX_DURATION_MS / TICK_MS)))
}
