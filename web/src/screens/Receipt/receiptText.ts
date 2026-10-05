// Textos del recibo de aprobación (UI.md §4.6, contrato §5): una operación por elemento de `review.plan`.
// El plan lo construye core/graph/nodes.py (`update_story`, `comment`, `create_story`, `link`, `publish_suite`).
// El recibo muestra solo lo que trae el plan: el comentario con los cambios llega como `{"op": "comment"}` (PA-319).
import type { ImpactAnalysis } from '../../components/Proposal/index.ts'
import { fieldLabel } from '../../components/Proposal/index.ts'

export type PlanItem = Record<string, string>

export interface ReceiptOperation {
  /** Clave estable para la casilla. */
  id: string
  label: string
  detail?: string
}

function changedFields(impact: ImpactAnalysis | null | undefined): string | undefined {
  const diffs = impact?.diffs ?? []
  if (diffs.length === 0) return undefined
  const fields = diffs.map((diff) => {
    const name = fieldLabel(diff.field)
    if (diff.before == null) return `${name} (nuevo)`
    if (diff.after === null) return `${name} (se quita)`
    return name
  })
  return `Cambia: ${fields.join(', ')}.`
}

function linkReason(impact: ImpactAnalysis | null | undefined, key: string): string | undefined {
  const reason = (impact?.affected ?? []).find((item) => item.jira_key === key)?.reason
  return reason ? `${reason.trim().replace(/[.]$/, '')}.` : undefined
}

/** «Actualizar DEMO-3 con la versión 3», «Vincular DEMO-3 con DEMO-2»… con su detalle. */
export function receiptOperations(plan: readonly PlanItem[], version: number, title: string, impact: ImpactAnalysis | null | undefined): ReceiptOperation[] {
  return plan.map((item, index) => operationOf(item, index, version, title, impact))
}

function operationOf(item: PlanItem, index: number, version: number, title: string, impact: ImpactAnalysis | null | undefined): ReceiptOperation {
  const id = `${index}-${item.op ?? 'op'}`
  switch (item.op) {
    case 'update_story':
      return { id, label: `Actualizar ${item.key ?? 'la HU'} con la versión ${version}`, detail: changedFields(impact) ?? title }
    case 'comment':
      return { id, label: `Añadir a ${item.key ?? 'la HU'} un comentario con los cambios`, detail: 'Tabla de cambios (campo, antes y después) para quien siga la HU.' }
    case 'create_story':
      return {
        id,
        label: item.epic ? `Crear la HU en la épica ${item.epic}` : item.project ? `Crear la HU en el proyecto ${item.project}` : 'Crear la HU',
        detail: title,
      }
    case 'link':
      return { id, label: `Vincular ${item.from ?? 'la HU'} con ${item.to ?? 'otra incidencia'}`, detail: linkReason(impact, item.to ?? '') ?? `Vínculo «${item.type ?? 'relates to'}».` }
    case 'publish_suite': {
      // `Number('')` es 0: un `cases` vacío no es «0 casos».
      const cases = item.cases?.trim() ? Number(item.cases) : Number.NaN
      const count = Number.isFinite(cases) ? `${cases} ${cases === 1 ? 'caso de prueba' : 'casos de prueba'}` : 'los casos de prueba'
      return { id, label: `Publicar ${count} en ${item.story ?? 'la HU'}`, detail: 'Como subtareas con la etiqueta «caso-prueba».' }
    }
    default: {
      // Operación que el frontend no conoce (versión futura de la API): se muestra tal cual, como texto.
      const detail = Object.entries(item)
        .filter(([key]) => key !== 'op')
        .map(([key, value]) => `${key}: ${value}`)
        .join(' · ')
      return { id, label: `Operación «${item.op ?? 'sin nombre'}»`, detail: detail || undefined }
    }
  }
}

/** «1 de 3 revisadas» → «Todo revisado». */
export function reviewedCounter(checked: number, total: number): string {
  return total > 0 && checked >= total ? 'Todo revisado' : `${checked} de ${total} revisadas`
}

/** «Generado con IA a partir de N fuentes…» (UI.md §4.6). */
export function aiNotice(sources: number): string {
  return `Generado con IA a partir de ${sources} ${sources === 1 ? 'fuente' : 'fuentes'}. Revisa cada operación antes de aprobar.`
}
