import { useMemo, useState } from 'react'
import { fromDraft, move, newCriterion, newRule, toDraft, type CriterionDraft, type ListField, type RuleDraft, type StoryDraft, type UserStory } from './storyDraft.ts'
import { checkStory, type EditCheck } from './storyValidation.ts'

export interface StoryEditor {
  original: UserStory
  draft: StoryDraft
  note: string
  /** La HU tal como se enviaría. */
  content: UserStory
  check: EditCheck
  /** Algo cambió respecto a la versión revisada (también la nota). */
  dirty: boolean
  setField: <K extends 'title' | 'role' | 'action' | 'benefit' | 'description' | 'business_goal' | 'priority'>(field: K, value: StoryDraft[K]) => void
  setList: (field: ListField, value: string) => void
  setNote: (value: string) => void
  updateCriterion: (key: string, patch: Partial<Omit<CriterionDraft, 'key' | 'id'>>) => void
  addCriterion: () => void
  removeCriterion: (key: string) => void
  moveCriterion: (key: string, step: -1 | 1) => void
  updateRule: (key: string, description: string) => void
  addRule: () => void
  removeRule: (key: string) => void
  moveRule: (key: string, step: -1 | 1) => void
}

const ids = (draft: StoryDraft) => [...draft.criteria.map((item) => item.id), ...draft.rules.map((item) => item.id)]

/** Estado del editor de una HU: el borrador, la nota y la comprobación (sin llamar a la API). */
export function useStoryEditor(original: UserStory): StoryEditor {
  const [draft, setDraft] = useState(() => toDraft(original))
  const [note, setNote] = useState('')
  const content = useMemo(() => fromDraft(draft, original), [draft, original])
  const check = useMemo(() => checkStory(content, original, note), [content, original, note])
  const unchanged = check.errors.some((issue) => issue.path === 'unchanged')

  const update = (recipe: (current: StoryDraft) => StoryDraft) => setDraft((current) => recipe(current))
  const patchCriteria = (recipe: (items: CriterionDraft[]) => CriterionDraft[]) => update((d) => ({ ...d, criteria: recipe(d.criteria) }))
  const patchRules = (recipe: (items: RuleDraft[]) => RuleDraft[]) => update((d) => ({ ...d, rules: recipe(d.rules) }))

  return {
    original,
    draft,
    note,
    content,
    check,
    dirty: !unchanged || note.trim().length > 0,
    setField: (field, value) => update((d) => ({ ...d, [field]: value })),
    setList: (field, value) => update((d) => ({ ...d, lists: { ...d.lists, [field]: value } })),
    setNote,
    updateCriterion: (key, patch) => patchCriteria((items) => items.map((item) => (item.key === key ? { ...item, ...patch } : item))),
    addCriterion: () => update((d) => ({ ...d, criteria: [...d.criteria, newCriterion(ids(d))] })),
    removeCriterion: (key) => patchCriteria((items) => items.filter((item) => item.key !== key)),
    moveCriterion: (key, step) => patchCriteria((items) => move(items, items.findIndex((item) => item.key === key), step)),
    updateRule: (key, description) => patchRules((items) => items.map((item) => (item.key === key ? { ...item, description } : item))),
    addRule: () => update((d) => ({ ...d, rules: [...d.rules, newRule(ids(d))] })),
    removeRule: (key) => patchRules((items) => items.filter((item) => item.key !== key)),
    moveRule: (key, step) => patchRules((items) => move(items, items.findIndex((item) => item.key === key), step)),
  }
}
