// Textos de Editar a mano en Iterar y en el recibo (RF-32, parte B).
import type { ImpactAnalysis } from '../../components/Proposal/proposalText.ts'
import type { UserStory } from './storyDraft.ts'

/**
 * Resumen del asistente para una versión editada a mano: sin `changes_from_previous`, que la edición copia de la versión
 * anterior (lo escribió el modelo para aquella), y con lo que afecta y las preguntas abiertas, como `versionSummary`.
 */
export function editedSummary(story: UserStory, version: number, impact: ImpactAnalysis | null | undefined): string {
  const parts = [`Versión ${version} guardada: editada a mano, sin llamar al modelo.`]
  const affected = impact?.affected ?? []
  if (affected.length > 0) parts.push(`Afecta también a ${affected.map((item) => item.jira_key).join(', ')}.`)
  const questions = story.open_questions.length
  if (questions > 0) parts.push(questions === 1 ? 'Queda 1 pregunta abierta.' : `Quedan ${questions} preguntas abiertas.`)
  return parts.join(' ')
}

/** Versiones editadas a mano (`VersionOut.edited`): la que está en revisión puede no estar aún en `versions`. */
export function editedVersions(versions: readonly { version: number; edited?: boolean }[]): ReadonlySet<number> {
  return new Set(versions.filter((item) => item.edited).map((item) => item.version))
}

/** La nota de una edición en la conversación: etiquetada, para que no parezca un cambio pedido al modelo. */
export function editNoteMessage(note: string): string {
  return `Nota de la edición: ${note.trim()}`
}
