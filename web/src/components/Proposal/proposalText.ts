// Textos derivados de una propuesta de HU (UserStory, StoryDiff e ImpactAnalysis del contrato).
import type { components } from '../../api/schema'
import { countLabel } from '../../text/plural.ts'

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

type Item = UserStory['acceptance_criteria'][number] | UserStory['business_rules'][number]

function itemsById(story: UserStory): Map<string, string> {
  const items: Item[] = [...story.acceptance_criteria, ...story.business_rules]
  return new Map(items.map((item) => [item.id, JSON.stringify(item)]))
}

/**
 * CA y RN nuevos o cambiados **en esta versión**. Con versión anterior se compara con ella, porque
 * `impact.diffs` es siempre el diff acumulado frente a Jira (core/impact/analysis.py). Sin ella (v1),
 * con los diffs: sin «before», nuevo; con él, cambiado frente a Jira.
 */
export function changeMarks(story: UserStory, previous: UserStory | undefined, diffs: readonly StoryDiff[]): Map<string, ChangeMark> {
  const marks = new Map<string, ChangeMark>()
  if (previous) {
    const before = itemsById(previous)
    for (const [id, item] of itemsById(story)) {
      const old = before.get(id)
      if (old === undefined) marks.set(id, 'new')
      else if (old !== item) marks.set(id, 'changed')
    }
    return marks
  }
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
  return `${countLabel(count, 'cambio', 'cambios')} frente a Jira`
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
  const questions = story.open_questions.length
  if (questions > 0) parts.push(questions === 1 ? 'Queda 1 pregunta abierta.' : `Quedan ${questions} preguntas abiertas.`)
  return parts.join(' ')
}
