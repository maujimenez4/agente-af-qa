// Textos derivados de una propuesta de HU (UserStory, StoryDiff e ImpactAnalysis del contrato).
import type { components } from '../../api/schema'

export type UserStory = components['schemas']['UserStory']
export type StoryDiff = components['schemas']['StoryDiff']
export type ImpactAnalysis = components['schemas']['ImpactAnalysis']
export type ImpactItem = components['schemas']['ImpactItem']
export type SourceRef = components['schemas']['SourceRef']

export type ChangeMark = 'new' | 'changed'

/** «acceptance_criteria.CA-02» → id CA-02. Los diffs de CA y RN van por id (core/impact/diff.py). */
function itemId(field: string): string | undefined {
  const match = /^(?:acceptance_criteria|business_rules)\.([A-Z]+-\d+)$/.exec(field)
  return match?.[1]
}

/** CA y RN nuevos (sin «before») o cambiados en esta versión. */
export function changeMarks(diffs: readonly StoryDiff[]): Map<string, ChangeMark> {
  const marks = new Map<string, ChangeMark>()
  for (const diff of diffs) {
    const id = itemId(diff.field)
    if (id && diff.after !== null) marks.set(id, diff.before == null ? 'new' : 'changed')
  }
  return marks
}

const FIELD_NAMES: Record<string, string> = {
  title: 'Título',
  role: 'Como',
  action: 'Quiero',
  benefit: 'Para',
  description: 'Descripción',
  business_goal: 'Objetivo de negocio',
  scope_includes: 'Alcance incluido',
  scope_excludes: 'Alcance excluido',
  assumptions: 'Supuestos',
  constraints: 'Restricciones',
  dependencies: 'Dependencias',
  alternate_flows: 'Flujos alternativos',
  exceptions: 'Excepciones',
  related_features: 'Funcionalidades relacionadas',
  priority: 'Prioridad',
  sources: 'Fuentes',
  open_questions: 'Preguntas abiertas',
}

/** Nombre legible del campo de un diff: «CA-02», «Descripción», «Fuentes (DOC-01)». */
export function fieldLabel(field: string): string {
  const id = itemId(field)
  if (id) return id
  const [base, detail] = field.split(/[.[]/)
  const name = FIELD_NAMES[base ?? ''] ?? field
  return detail ? `${name} (${detail.replace(/]$/, '')})` : name
}

/** Tipo de un elemento afectado (ImpactItem.kind). */
export const IMPACT_KIND: Record<ImpactItem['kind'], string> = {
  story: 'HU relacionada',
  rule: 'Regla compartida',
  dependency: 'Dependencia',
  regression: 'Regresión',
}

function sentence(text: string): string {
  const trimmed = text.trim()
  return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`
}

/** «1 cambio», «3 cambios» frente a Jira. */
export function changesLabel(count: number): string {
  return `${count} ${count === 1 ? 'cambio' : 'cambios'} frente a Jira`
}

/** Resumen del asistente para una versión, sin LLM: lo que cambió y a qué afecta (UI.md §4.5). */
export function versionSummary(story: UserStory, version: number, impact: ImpactAnalysis | null | undefined): string {
  const parts = [`Versión ${version} lista.`]
  // Cada cambio como frase: el LLM no siempre termina en punto.
  if (story.changes_from_previous.length > 0) parts.push(story.changes_from_previous.map(sentence).join(' '))
  const affected = impact?.affected ?? []
  if (affected.length > 0) {
    parts.push(`Afecta también a ${affected.map((item) => `${item.jira_key} (${item.reason.charAt(0).toLowerCase()}${item.reason.slice(1)})`).join(', ')}.`)
  }
  if (story.open_questions.length > 0) parts.push(`Quedan ${story.open_questions.length} preguntas abiertas.`)
  return parts.join(' ')
}
