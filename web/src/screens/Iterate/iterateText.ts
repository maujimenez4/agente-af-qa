import type { ArtifactOut, ConversationOut } from '../../api/types.ts'
import type { ImpactAnalysis, UserStory } from '../../components/Proposal/index.ts'

/** Versión de la propuesta tal como la pinta Iterar. */
export interface ProposalVersion {
  version: number
  artifact: ArtifactOut
  story: UserStory
  impact: ImpactAnalysis | null | undefined
}

/** Las versiones de la conversación (VersionOut) más la que está en revisión, sin repetir. */
export function proposalVersions(conversation: ConversationOut): ProposalVersion[] {
  const byVersion = new Map<number, ArtifactOut>()
  for (const item of conversation.versions) byVersion.set(item.version, item.artifact)
  const review = conversation.review
  if (review) byVersion.set(review.version, review.artifact)
  return [...byVersion.entries()]
    .sort(([a], [b]) => a - b)
    .map(([version, artifact]) => ({
      version,
      artifact,
      story: artifact.content as UserStory,
      impact: artifact.impact ?? (review?.version === version ? review.impact : null),
    }))
}

/** «local/qwen3:4b-instruct» → «local · qwen3:4b-instruct» (UI.md §4.5: aviso del modelo usado). */
export function modelLabel(modelUsed: string | null | undefined): string | undefined {
  return modelUsed ? modelUsed.replace('/', ' · ') : undefined
}

/** Sugerencias de cambio del lienzo (MixtoIterar), que rellenan el compositor. */
export const SUGGESTIONS = ['Añade un criterio de error', 'Aclara el alcance', 'Revisa INVEST'] as const
