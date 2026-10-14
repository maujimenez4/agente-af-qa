// Borrador de Editar a mano la suite de QA (PA-158): la suite en campos de texto y de vuelta. Lo que no se edita (la
// clave de la HU y las fuentes) se conserva tal cual. Las listas se editan con una línea por elemento, como en la HU.
import type { TestCase, TestSuite } from '../../api/types.ts'
import { dataColumns } from '../../components/Suite/suiteText.ts'
import { splitLines } from './storyDraft.ts'

export type CaseType = TestCase['type']
export type CasePriority = TestCase['priority']

/** Los tipos de caso del contrato, en el orden del esquema (`TestCaseType`). */
export const CASE_TYPES: readonly CaseType[] = ['positivo', 'negativo', 'alterno', 'excepcion']

export const SUITE_LIST_FIELDS = ['risks', 'dependencies', 'impact_areas'] as const
export type SuiteListField = (typeof SUITE_LIST_FIELDS)[number]

export const SUITE_LIST_LABELS: Record<SuiteListField, string> = {
  risks: 'Riesgos',
  dependencies: 'Dependencias',
  impact_areas: 'Áreas de impacto',
}

export interface StepDraft {
  /** Clave estable para React (no se envía). */
  key: string
  action: string
  data: string
  expected: string
  /** `data` era `null`: vacío vuelve a `null` (así no cuenta como cambio). */
  dataWasNull: boolean
}

export interface CaseDraft {
  key: string
  internal_id: string
  title: string
  type: CaseType
  priority: CasePriority
  /** «CA-01, RN-02»: los CA y RN que verifica, separados por comas o espacios. */
  refs: string
  /** Una línea por precondición. */
  preconditions: string
  steps: StepDraft[]
  gherkin: string
  gherkinWasNull: boolean
}

export interface ColumnDraft {
  key: string
  name: string
}

export interface RowDraft {
  key: string
  /** Valor por clave de columna. */
  values: Record<string, string>
  /** Columnas que la fila ya tenía (aunque vacías): las demás, vacías, no se envían. */
  present: ReadonlySet<string>
}

export interface SuiteDraft {
  cases: CaseDraft[]
  columns: ColumnDraft[]
  rows: RowDraft[]
  lists: Record<SuiteListField, string>
  strategy_md: string
}

let nextKey = 0
const newKey = () => `s${++nextKey}`

const joinLines = (items: readonly string[]) => items.join('\n')

/** Los CA y RN escritos en «Verifica»: separados por comas, espacios o saltos de línea. */
export function splitRefs(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

function stepDraft(step: TestCase['steps'][number]): StepDraft {
  return { key: newKey(), action: step.action, data: step.data ?? '', expected: step.expected, dataWasNull: step.data == null }
}

export function newStep(): StepDraft {
  return { key: newKey(), action: '', data: '', expected: '', dataWasNull: true }
}

function caseDraft(item: TestCase): CaseDraft {
  return {
    key: newKey(),
    internal_id: item.internal_id,
    title: item.title,
    type: item.type,
    priority: item.priority,
    refs: [...item.criterion_ids, ...(item.rule_ids ?? [])].join(', '),
    preconditions: joinLines(item.preconditions),
    steps: item.steps.map(stepDraft),
    gherkin: item.gherkin ?? '',
    gherkinWasNull: item.gherkin == null,
  }
}

/** El siguiente «CP-NN» libre, con el ancho de los que hay (al menos dos cifras). */
export function nextCaseId(ids: readonly string[]): string {
  const numbers = ids.map((id) => /^CP-(\d+)$/.exec(id)).filter((match) => match !== null)
  const max = Math.max(0, ...numbers.map((match) => Number(match[1])))
  const width = Math.max(2, ...numbers.map((match) => match[1]?.length ?? 2))
  return `CP-${String(max + 1).padStart(width, '0')}`
}

/** Un caso nuevo, vacío salvo el id, el tipo (positivo), la prioridad (Should) y un paso por rellenar. */
export function newCase(ids: readonly string[]): CaseDraft {
  return {
    key: newKey(),
    internal_id: nextCaseId(ids),
    title: '',
    type: 'positivo',
    priority: 'Should',
    refs: '',
    preconditions: '',
    steps: [newStep()],
    gherkin: '',
    gherkinWasNull: true,
  }
}

export function newColumn(): ColumnDraft {
  return { key: newKey(), name: '' }
}

export function newRow(): RowDraft {
  return { key: newKey(), values: {}, present: new Set() }
}

export function toSuiteDraft(suite: TestSuite): SuiteDraft {
  const data = suite.synthetic_data ?? []
  const columns = dataColumns(data).map((name) => ({ key: newKey(), name }))
  const rows = data.map((row) => {
    const values: Record<string, string> = {}
    const present = new Set<string>()
    for (const column of columns) {
      if (Object.prototype.hasOwnProperty.call(row, column.name)) {
        values[column.key] = row[column.name] ?? ''
        present.add(column.key)
      }
    }
    return { key: newKey(), values, present }
  })
  return {
    cases: suite.cases.map(caseDraft),
    columns,
    rows,
    lists: Object.fromEntries(SUITE_LIST_FIELDS.map((field) => [field, joinLines(suite[field] ?? [])])) as Record<SuiteListField, string>,
    strategy_md: suite.strategy_md,
  }
}

/** Los CA de «Verifica» (los que empiezan por «CA-») y el resto, que va a las RN (la validación marca lo que no lo sea). */
export function caseRefs(refs: string): { criterion_ids: string[]; rule_ids: string[] } {
  const ids = splitRefs(refs)
  return { criterion_ids: ids.filter((id) => id.startsWith('CA-')), rule_ids: ids.filter((id) => !id.startsWith('CA-')) }
}

/**
 * La suite que se envía: la editada sobre la original (la clave de la HU y las fuentes, tal cual). Una columna de datos
 * sin nombre no se envía (con valores, la validación no deja guardar).
 */
export function fromSuiteDraft(draft: SuiteDraft, original: TestSuite): TestSuite {
  return {
    ...original,
    cases: draft.cases.map((item) => ({
      internal_id: item.internal_id,
      title: item.title,
      ...caseRefs(item.refs),
      type: item.type,
      preconditions: splitLines(item.preconditions),
      steps: item.steps.map((step) => ({
        action: step.action,
        data: step.data.length === 0 && step.dataWasNull ? null : step.data,
        expected: step.expected,
      })),
      gherkin: item.gherkin.length === 0 && item.gherkinWasNull ? null : item.gherkin,
      priority: item.priority,
    })),
    synthetic_data: draft.rows.map((row) =>
      Object.fromEntries(
        draft.columns
          .filter((column) => column.name.trim().length > 0 && (row.present.has(column.key) || (row.values[column.key] ?? '').length > 0))
          .map((column) => [column.name, row.values[column.key] ?? '']),
      ),
    ),
    ...(Object.fromEntries(SUITE_LIST_FIELDS.map((field) => [field, splitLines(draft.lists[field])])) as Record<SuiteListField, string[]>),
    strategy_md: draft.strategy_md,
  }
}
