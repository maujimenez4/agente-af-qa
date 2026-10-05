// Textos de la lista de pendientes de QA (T-54) en Inicio.
import type { HandoffOut } from '../../api/types.ts'

const WHEN = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

/** «Versión 2 · de af-demo · 2 oct, 12:30» (sin fecha si no se puede leer). */
export function handoffMeta(handoff: HandoffOut): string {
  const date = new Date(handoff.created_at)
  const when = Number.isNaN(date.getTime()) ? '' : ` · ${WHEN.format(date)}`
  return `Versión ${handoff.version} · de ${handoff.from_user}${when}`
}
