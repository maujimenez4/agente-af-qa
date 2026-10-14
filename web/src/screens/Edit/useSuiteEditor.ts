import { useMemo, useState } from 'react'
import type { TestSuite } from '../../api/types.ts'
import type { SuiteCoverage } from '../../components/Suite/suiteText.ts'
import type { EditorCore } from './editorCore.ts'
import { move } from './storyDraft.ts'
import {
  fromSuiteDraft,
  newCase,
  newColumn,
  newRow,
  newStep,
  toSuiteDraft,
  type CaseDraft,
  type StepDraft,
  type SuiteDraft,
  type SuiteListField,
} from './suiteDraft.ts'
import { checkSuite, liveCoverage, type StoryRefs } from './suiteValidation.ts'

export interface SuiteEditor extends EditorCore<TestSuite> {
  original: TestSuite
  draft: SuiteDraft
  /** Los CA y RN de la HU (`null`: no se sabe). */
  refs: StoryRefs
  /** Cobertura de lo editado, al momento. */
  coverage: SuiteCoverage
  updateCase: (key: string, patch: Partial<Omit<CaseDraft, 'key' | 'steps'>>) => void
  addCase: () => void
  removeCase: (key: string) => void
  moveCase: (key: string, step: -1 | 1) => void
  updateStep: (caseKey: string, stepKey: string, patch: Partial<Omit<StepDraft, 'key'>>) => void
  addStep: (caseKey: string) => void
  removeStep: (caseKey: string, stepKey: string) => void
  moveStep: (caseKey: string, stepKey: string, step: -1 | 1) => void
  renameColumn: (key: string, name: string) => void
  addColumn: () => void
  removeColumn: (key: string) => void
  setCell: (rowKey: string, columnKey: string, value: string) => void
  addRow: () => void
  removeRow: (key: string) => void
  setList: (field: SuiteListField, value: string) => void
  setStrategy: (value: string) => void
}

/** Estado del editor de una suite (PA-158): el borrador, la nota, la comprobación y la cobertura, sin llamar a la API. */
export function useSuiteEditor(original: TestSuite, refs: StoryRefs): SuiteEditor {
  const [draft, setDraft] = useState(() => toSuiteDraft(original))
  const [note, setNote] = useState('')
  const content = useMemo(() => fromSuiteDraft(draft, original), [draft, original])
  const check = useMemo(() => checkSuite(content, original, draft, refs, note), [content, original, draft, refs, note])
  const coverage = useMemo(() => liveCoverage(content, refs), [content, refs])
  const unchanged = check.errors.some((issue) => issue.path === 'unchanged')

  const update = (recipe: (current: SuiteDraft) => SuiteDraft) => setDraft((current) => recipe(current))
  const patchCases = (recipe: (items: CaseDraft[]) => CaseDraft[]) => update((d) => ({ ...d, cases: recipe(d.cases) }))
  const patchSteps = (caseKey: string, recipe: (steps: StepDraft[]) => StepDraft[]) =>
    patchCases((items) => items.map((item) => (item.key === caseKey ? { ...item, steps: recipe(item.steps) } : item)))

  return {
    original,
    draft,
    refs,
    note,
    content,
    check,
    coverage,
    dirty: !unchanged || note.trim().length > 0,
    setNote,
    updateCase: (key, patch) => patchCases((items) => items.map((item) => (item.key === key ? { ...item, ...patch } : item))),
    addCase: () => update((d) => ({ ...d, cases: [...d.cases, newCase(d.cases.map((item) => item.internal_id))] })),
    removeCase: (key) => patchCases((items) => items.filter((item) => item.key !== key)),
    moveCase: (key, step) => patchCases((items) => move(items, items.findIndex((item) => item.key === key), step)),
    updateStep: (caseKey, stepKey, patch) => patchSteps(caseKey, (steps) => steps.map((item) => (item.key === stepKey ? { ...item, ...patch } : item))),
    addStep: (caseKey) => patchSteps(caseKey, (steps) => [...steps, newStep()]),
    removeStep: (caseKey, stepKey) => patchSteps(caseKey, (steps) => steps.filter((item) => item.key !== stepKey)),
    moveStep: (caseKey, stepKey, step) => patchSteps(caseKey, (steps) => move(steps, steps.findIndex((item) => item.key === stepKey), step)),
    renameColumn: (key, name) => update((d) => ({ ...d, columns: d.columns.map((column) => (column.key === key ? { ...column, name } : column)) })),
    addColumn: () => update((d) => ({ ...d, columns: [...d.columns, newColumn()] })),
    removeColumn: (key) =>
      update((d) => ({
        ...d,
        columns: d.columns.filter((column) => column.key !== key),
        rows: d.rows.map((row) => {
          const values = { ...row.values }
          delete values[key]
          const present = new Set(row.present)
          present.delete(key)
          return { ...row, values, present }
        }),
      })),
    setCell: (rowKey, columnKey, value) =>
      update((d) => ({ ...d, rows: d.rows.map((row) => (row.key === rowKey ? { ...row, values: { ...row.values, [columnKey]: value } } : row)) })),
    addRow: () => update((d) => ({ ...d, rows: [...d.rows, newRow()] })),
    removeRow: (key) => update((d) => ({ ...d, rows: d.rows.filter((row) => row.key !== key) })),
    setList: (field, value) => update((d) => ({ ...d, lists: { ...d.lists, [field]: value } })),
    setStrategy: (value) => update((d) => ({ ...d, strategy_md: value })),
  }
}
