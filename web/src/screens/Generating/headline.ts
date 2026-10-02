import type { ConversationOut } from '../../api/types.ts'
import { changesLabel } from '../../components/Proposal/index.ts'

/** «Propuesta lista · Versión 1 · 3 cambios frente a Jira» (UI.md §4.4). */
export function readyHeadline(conversation: ConversationOut): string {
  const version = conversation.review?.version ?? conversation.versions.at(-1)?.version ?? 1
  const changes = conversation.review?.artifact.impact?.diffs.length ?? 0
  const parts = ['Propuesta lista', `Versión ${version}`]
  if (conversation.flow === 'evolve') parts.push(changesLabel(changes))
  return parts.join(' · ')
}
