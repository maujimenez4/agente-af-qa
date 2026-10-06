import type { ConversationOut, TestSuite } from '../../api/types.ts'
import { changesLabel } from '../../components/Proposal/index.ts'
import { countLabel } from '../../text/plural.ts'

/** «Propuesta lista · Versión 1 · 3 cambios frente a Jira» (UI.md §4.4); en QA, «Suite lista · Versión 1 · 4 casos» (§6.2). */
export function readyHeadline(conversation: ConversationOut): string {
  const version = conversation.review?.version ?? conversation.versions.at(-1)?.version ?? 1
  if (conversation.mode === 'qa') {
    const content = conversation.review?.artifact.content
    const cases = content && 'cases' in content ? (content as TestSuite).cases.length : undefined
    return ['Suite lista', `Versión ${version}`, cases === undefined ? undefined : countLabel(cases, 'caso', 'casos')]
      .filter(Boolean)
      .join(' · ')
  }
  const changes = conversation.review?.artifact.impact?.diffs.length ?? 0
  const parts = ['Propuesta lista', `Versión ${version}`]
  if (conversation.flow === 'evolve') parts.push(changesLabel(changes))
  return parts.join(' · ')
}

/** Cabecera de QA (lienzo QaGenerando): «Pruebas de DEMO-3» en lugar de «Preparar pruebas de DEMO-3», que se corta con el panel abierto. */
export function qaHeaderTitle(title: string): string {
  return title.replace(/^Preparar pruebas de /, 'Pruebas de ')
}
