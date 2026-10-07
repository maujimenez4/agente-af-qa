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

/** Sugerencias de cambio que rellenan el compositor (lienzo MixtoIterar, salvo «Aclara el alcance»: DESIGN-DECISIONS.md §4 bis). */
export const SUGGESTIONS = ['Añade un criterio de error', 'Aclara el alcance', 'Revisa INVEST'] as const

/** Sugerencias de cambio de la suite (QA 3; los mismos textos que Streamlit, `app/qa.py`). */
export const QA_SUGGESTIONS = ['Añade un caso negativo con datos no válidos', 'Cubre también las reglas de negocio', 'Añade un caso de excepción'] as const

const LIST = new Intl.ListFormat('es', { style: 'long', type: 'conjunction' })

/**
 * Sugerencia de QA con algún CA sin caso (bloquea la aprobación): «Añade un caso para CA-02» o «Añade casos para CA-02
 * y CA-03». Sin CA pendientes, ninguna.
 */
export function addCasesSuggestion(criteria: readonly string[]): string | undefined {
  if (criteria.length === 0) return undefined
  return criteria.length === 1 ? `Añade un caso para ${criteria[0]}` : `Añade casos para ${LIST.format(criteria)}`
}

/** Por qué importa en Iterar: *Revisar y aprobar* sigue activo, pero el recibo no dejará aprobar. */
export const MISSING_CASES_ITERATE_REASON = 'Cada CA de la HU necesita al menos un caso para aprobar la suite: pídelo en la conversación.'

/** Editar a mano la suite de QA aún no está (PA-158, PA-340): motivo visible junto al distintivo (PA-346, como PA-431). */
export const QA_EDIT_SOON = 'Editar la suite a mano llegará más adelante; por ahora, pide los cambios en la conversación.'

/** Indicador mientras se genera la versión nueva tras pedir un cambio (PA-430). */
export const ITERATING_LABEL = 'Generando una nueva versión…'
