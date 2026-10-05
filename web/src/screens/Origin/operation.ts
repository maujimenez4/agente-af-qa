// Operación que se fija en Origen y fuentes (UI.md §4.3): lo único que se podrá aprobar y publicar.
import type { ConversationCreateIn, IssueSummary, OriginIn, SourcePreview, StartOption } from '../../api/types.ts'

export type OperationKind = StartOption['kind']

export interface Operation {
  kind: OperationKind
  flow: ConversationCreateIn['flow']
  origin: OriginIn
  /** «Evolucionar DEMO-3», «Crear una HU nueva en la épica DEMO-1»… */
  label: string
  issue?: IssueSummary
}

const FLOW_OF: Record<OperationKind, ConversationCreateIn['flow']> = {
  evolve: 'evolve',
  tests: 'tests',
  new_story_in_epic: 'need',
  new_need: 'need',
}

/** Operación a partir de una opción de POST /start/propose (traen el `origin` listo). */
export function operationFromOption(option: StartOption, project: string): Operation {
  return {
    kind: option.kind,
    flow: FLOW_OF[option.kind],
    origin: {
      kind: option.origin.kind,
      key: option.origin.key ?? null,
      text: option.origin.text ?? null,
      project: option.origin.project ?? project,
    },
    label: option.label,
    issue: option.issue ?? undefined,
  }
}

/** Operación a partir de un origen elegido en Jira o en los recientes. */
export function operationFromIssue(issue: IssueSummary, project: string, flow: 'need' | 'evolve' | 'review' | 'tests', text: string): Operation {
  if (issue.issue_type === 'Epic') {
    return {
      kind: 'new_story_in_epic',
      flow: 'need',
      origin: { kind: 'epic', key: issue.key, project, text: text || null },
      label: `Crear una HU nueva en la épica ${issue.key}`,
      issue,
    }
  }
  if (flow === 'tests') {
    return { kind: 'tests', flow: 'tests', origin: { kind: 'story', key: issue.key, project }, label: `Preparar pruebas de ${issue.key}`, issue }
  }
  return { kind: 'evolve', flow: 'evolve', origin: { kind: 'story', key: issue.key, project }, label: `Evolucionar ${issue.key}`, issue }
}

/** Título de la tarjeta «Operación fijada». */
export function fixedTitle(operation: Operation): string {
  const key = operation.origin.key
  switch (operation.kind) {
    case 'evolve':
      return `Operación fijada: evolucionar ${key}`
    case 'tests':
      return `Operación fijada: suite de pruebas de ${key}`
    case 'new_story_in_epic':
      return `Operación fijada: HU nueva en la épica ${key}`
    case 'new_need':
      return 'Operación fijada: HU nueva'
  }
}

/**
 * Cuerpo de POST /conversations. Las restricciones (UI.md §4.3): en una necesidad nueva se añaden
 * al texto; al evolucionar o preparar pruebas van como primer `feedback`.
 */
export function createBody(operation: Operation, restrictions: string, excluded: readonly string[]): ConversationCreateIn {
  const extra = restrictions.trim()
  const origin: OriginIn = { ...operation.origin }
  const feedback: string[] = []
  if (extra) {
    if (operation.flow === 'need') origin.text = [origin.text, `Restricciones: ${extra}`].filter(Boolean).join('\n\n')
    else feedback.push(extra)
  }
  return { flow: operation.flow, origin, excluded_sources: [...excluded], feedback }
}

// Categorías del RAG (core/rag/documents.py, T-49).
const CATEGORY_NAMES: Record<string, string> = {
  productos: 'Productos y servicios',
  procesos: 'Procesos de negocio',
  politicas: 'Políticas y reglas operativas',
  documentacion: 'Documentación funcional y técnica',
  glosarios: 'Glosarios y criterios internos',
  historias: 'HU y artefactos previos',
  pruebas: 'Estrategias y casos de prueba',
  memoria: 'Memoria',
}

/** Línea secundaria de una fuente: «DOC-01 · Políticas y reglas operativas». */
export function sourceDetail(source: SourcePreview, included: boolean): string {
  if (!included) return `${source.ref} · No influirá en la propuesta`
  if (source.kind === 'memory') return `${source.ref} · Memoria, prioritaria`
  if (source.kind === 'jira') return `${source.ref} · Jira${source.required ? ', obligatoria' : ''}`
  const category = source.category ? (CATEGORY_NAMES[source.category] ?? source.category) : undefined
  return category ? `${source.ref} · ${category}` : source.ref
}
