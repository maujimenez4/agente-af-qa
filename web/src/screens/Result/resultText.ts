// Textos de Mixta 4 · Resultado (UI.md §4.7, lienzo MixtoPublicado) a partir de `ConversationOut.result`.
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import type { PublishOutcomeKind } from '../../components/QMark/index.ts'
import { safeHref } from '../../security/safeHref.ts'

export type { PublishOutcomeKind }

/** Simulada, publicada o publicada en parte (`errors`, RNF-13: no es un error HTTP, llega en `result`). */
export function outcomeOf(result: PublishOutcome): PublishOutcomeKind {
  if (result.simulated) return 'simulated'
  return result.errors.length > 0 || result.failed_ids.length > 0 ? 'partial' : 'published'
}

/** La conversación tiene un resultado que pintar (aprobada, simulada o publicada). */
export function hasResult(conversation: ConversationOut): conversation is ConversationOut & { result: PublishOutcome } {
  return Boolean(conversation.result) && ['approved', 'simulated', 'published'].includes(conversation.state)
}

export interface OutcomeTexts {
  phase: 3 | 4
  phaseName: string
  badge: string
  title: string
  lead: string
  note: string
}

export const OUTCOME_TEXTS: Record<PublishOutcomeKind, OutcomeTexts> = {
  simulated: {
    phase: 3,
    phaseName: 'Aprobada',
    badge: 'Aprobada · simulada',
    title: 'Publicación simulada',
    lead: 'No se ha escrito nada en Jira. Esto es lo que se habría hecho, y queda en la auditoría:',
    note: 'La aprobación sigue vigente: cuando se active la publicación real se podrá publicar sin repetir la revisión. La memoria se genera al publicar de verdad.',
  },
  published: {
    phase: 4,
    phaseName: 'Publicado',
    badge: 'Publicada',
    title: 'Publicado en Jira',
    lead: 'Estas operaciones ya están en Jira:',
    note: 'La memoria de la HU se ha generado e indexado; tendrá prioridad en las próximas propuestas.',
  },
  partial: {
    phase: 4,
    phaseName: 'Publicada en parte',
    badge: 'Publicada en parte',
    title: 'Publicada en parte',
    lead: 'Se aprobaron estas operaciones. Parte ya está en Jira; lo que falló se indica debajo:',
    note: 'Lo publicado se queda en Jira. Reintentar solo lo que falló llegará más adelante (PA-05); mientras, revisa las operaciones en Jira.',
  },
}

const TIME = new Intl.DateTimeFormat('es-ES', { hour: '2-digit', minute: '2-digit' })

/** «Versión 2 aprobada por af-demo a las 15:47» (sin hora si la fecha no se puede leer). */
export function approvedLine(version: number | undefined, result: PublishOutcome): string {
  const date = new Date(result.approved_at)
  const time = Number.isNaN(date.getTime()) ? '' : ` a las ${TIME.format(date)}`
  return `${version ? `Versión ${version}` : 'Propuesta'} aprobada por ${result.approved_by}${time}`
}

const ISSUE_KEY = /^[A-Z][A-Z0-9_]*-\d+$/

/**
 * «Abrir DEMO-3 en Jira» (PA-318): `{jira_browse_url}{clave}`. Solo con un prefijo `https` y una clave de Jira
 * válida; si no, `undefined` y la acción sigue «disponible pronto». El prefijo tiene que acabar en «/», sin query
 * ni fragmento: si no, la clave se pegaría al host (otro sitio). El enlace pasa además por `safeHref`.
 */
export function jiraIssueUrl(browseUrl: string | null | undefined, key: string | undefined): string | undefined {
  if (!browseUrl || !key || !ISSUE_KEY.test(key)) return undefined
  let base: URL
  try {
    base = new URL(browseUrl)
  } catch {
    return undefined
  }
  if (base.protocol !== 'https:' || !base.pathname.endsWith('/') || base.search || base.hash || !browseUrl.endsWith('/')) return undefined
  const url = new URL(key, base)
  return url.origin === base.origin ? safeHref(url.href) : undefined
}
