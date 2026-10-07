// Editar a mano (RF-32, `POST /conversations/{id}/edit`): borrador editable de una HU y vuelta a `UserStory`.
// El backend decide (core/graph/nodes.py, `_edit`): aquí solo se bloquea lo que él rechazaría seguro, y el resto se
// avisa. De dónde sale cada regla: web/DESIGN-DECISIONS.md («Editar a mano»).
import type { components } from '../../api/schema'

export type UserStory = components['schemas']['UserStory']
export type Priority = UserStory['priority']

export const PRIORITIES: readonly Priority[] = ['Must', 'Should', 'Could', "Won't"]

/** Listas de texto que se editan con una línea por elemento. */
export const LIST_FIELDS = [
  'scope_includes',
  'scope_excludes',
  'assumptions',
  'constraints',
  'dependencies',
  'alternate_flows',
  'exceptions',
  'related_features',
] as const
export type ListField = (typeof LIST_FIELDS)[number]

export const LIST_LABELS: Record<ListField, string> = {
  scope_includes: 'Alcance incluido',
  scope_excludes: 'Fuera del alcance',
  assumptions: 'Supuestos',
  constraints: 'Restricciones',
  dependencies: 'Dependencias',
  alternate_flows: 'Flujos alternativos',
  exceptions: 'Excepciones',
  related_features: 'Funcionalidades relacionadas',
}

export interface CriterionDraft {
  /** Clave estable para React (no se envía). */
  key: string
  id: string
  title: string
  /** Una línea por paso. */
  given: string
  when: string
  then: string
}

export interface RuleDraft {
  key: string
  id: string
  description: string
}

export interface StoryDraft {
  title: string
  role: string
  action: string
  benefit: string
  description: string
  business_goal: string
  priority: Priority
  criteria: CriterionDraft[]
  rules: RuleDraft[]
  lists: Record<ListField, string>
}

let nextKey = 0
const newKey = () => `k${++nextKey}`

/** Una línea por elemento: así se edita cada lista en un solo cuadro de texto. */
const joinLines = (items: readonly string[]) => items.join('\n')

/** Las líneas con texto; las vacías no se envían (una lista no tiene elementos vacíos). */
export function splitLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.replace(/\r$/, ''))
    .filter((line) => line.trim().length > 0)
}

export function toDraft(story: UserStory): StoryDraft {
  return {
    title: story.title,
    role: story.role,
    action: story.action,
    benefit: story.benefit,
    description: story.description,
    business_goal: story.business_goal,
    priority: story.priority,
    criteria: story.acceptance_criteria.map((item) => ({
      key: newKey(),
      id: item.id,
      title: item.title,
      given: joinLines(item.given),
      when: joinLines(item.when),
      then: joinLines(item.then),
    })),
    rules: story.business_rules.map((item) => ({ key: newKey(), id: item.id, description: item.description })),
    lists: Object.fromEntries(LIST_FIELDS.map((field) => [field, joinLines(story[field])])) as Record<ListField, string>,
  }
}

/**
 * La HU que se envía: lo editado sobre la original. Lo que no se edita aquí (clave de Jira, `internal_id`,
 * fuentes, cambios frente a la anterior, requisitos relacionados y preguntas abiertas) se conserva tal cual.
 */
export function fromDraft(draft: StoryDraft, original: UserStory): UserStory {
  return {
    ...original,
    title: draft.title,
    role: draft.role,
    action: draft.action,
    benefit: draft.benefit,
    description: draft.description,
    business_goal: draft.business_goal,
    priority: draft.priority,
    acceptance_criteria: draft.criteria.map((item) => ({
      id: item.id,
      title: item.title,
      given: splitLines(item.given),
      when: splitLines(item.when),
      then: splitLines(item.then),
    })),
    business_rules: draft.rules.map((item) => ({ id: item.id, description: item.description })),
    ...(Object.fromEntries(LIST_FIELDS.map((field) => [field, splitLines(draft.lists[field])])) as Record<ListField, string[]>),
  }
}

/** El siguiente identificador libre («CA-03» tras «CA-01» y «CA-02»), con el mismo ancho que los que hay. */
export function nextId(prefix: 'CA' | 'RN', ids: readonly string[]): string {
  const numbers = ids.map((id) => new RegExp(`^${prefix}-(\\d+)$`).exec(id)).filter((match) => match !== null)
  const max = Math.max(0, ...numbers.map((match) => Number(match[1])))
  const width = Math.max(2, ...numbers.map((match) => match[1]?.length ?? 2))
  return `${prefix}-${String(max + 1).padStart(width, '0')}`
}

export function newCriterion(ids: readonly string[]): CriterionDraft {
  return { key: newKey(), id: nextId('CA', ids), title: '', given: '', when: '', then: '' }
}

export function newRule(ids: readonly string[]): RuleDraft {
  return { key: newKey(), id: nextId('RN', ids), description: '' }
}

/** Mueve el elemento `index` una posición arriba (-1) o abajo (+1); fuera de rango, la lista igual. */
export function move<T>(items: readonly T[], index: number, step: -1 | 1): T[] {
  const target = index + step
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return [...items]
  const next = [...items]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item as T)
  return next
}
