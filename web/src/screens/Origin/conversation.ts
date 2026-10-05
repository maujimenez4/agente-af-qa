// Conversación de Origen y fuentes (UI.md §4.3): propuestas del arranque guiado y detalles.
import type { StartProposal } from '../../api/types.ts'

/**
 * Un turno del chat, en orden.
 * - `ask`: un mensaje antes de fijar la operación y su propuesta (sin ella mientras se espera o si falló).
 * - `detail`: un mensaje con la operación ya fijada; va con las restricciones al generar.
 */
export type Turn = { kind: 'ask'; text: string; proposal?: StartProposal } | { kind: 'detail'; text: string }

export const NOTED = 'Anotado: lo tendré en cuenta al generar.'
export const PLACEHOLDER_NEED = 'Escribe otra necesidad o una clave de Jira'
export const PLACEHOLDER_DETAILS = 'Añade detalles a la necesidad (opcional)'

const CAPABILITIES = {
  functional: 'Puedo crear una HU nueva, evolucionar una existente o preparar sus pruebas. No gestiono proyectos de Jira.',
  qa: 'Puedo preparar las pruebas de una HU existente. No gestiono proyectos de Jira.',
} as const

/** Línea fija tras una búsqueda por texto: qué puede hacer el agente (y qué no). */
export function capabilitiesLine(mode: 'functional' | 'qa'): string {
  return CAPABILITIES[mode]
}

/** Placeholder del composer: lo que hará el siguiente mensaje. */
export function composerPlaceholder(operationChosen: boolean): string {
  return operationChosen ? PLACEHOLDER_DETAILS : PLACEHOLDER_NEED
}

/** La última propuesta recibida: la única con opciones activas. */
export function latestProposal(turns: readonly Turn[]): StartProposal | undefined {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn?.kind === 'ask' && turn.proposal) return turn.proposal
  }
  return undefined
}

/** Los detalles escritos tras fijar la operación (van con las restricciones). */
export function detailsOf(turns: readonly Turn[]): string[] {
  return turns.filter((turn) => turn.kind === 'detail').map((turn) => turn.text)
}
