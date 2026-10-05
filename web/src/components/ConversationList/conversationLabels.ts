// Textos de la lista de conversaciones a partir de `ConversationSummary` (docs/api/openapi.yaml).
import type { ConversationStatus, ConversationSummary } from '../../api/types.ts'

export type { ConversationStatus }

/** Los campos de `ConversationSummary` que usa la lista. */
export type ConversationSummaryView = Pick<
  ConversationSummary,
  'thread_id' | 'project_key' | 'mode' | 'origin_kind' | 'origin_key' | 'title' | 'status' | 'version' | 'updated_at'
>

// La API titula «Nueva HU en DEMO-1» la HU nueva dentro de una épica (core/conversations.py, PA-317).
const EPIC_TITLE = /^Nueva HU en (\S+)$/

/** Título que se muestra: el de la API, salvo la HU nueva en una épica («HU nueva en la épica DEMO-1»). */
export function conversationTitle(title: string): string {
  const epic = EPIC_TITLE.exec(title)
  return epic ? `HU nueva en la épica ${epic[1]}` : title
}

/** Flujo de la conversación («Evolucionar DEMO-3», «HU nueva en la épica DEMO-1», «Pruebas de DEMO-3»). */
export function flowLabel(conversation: ConversationSummaryView): string {
  const key = conversation.origin_key
  if (conversation.mode === 'qa') return key ? `Pruebas de ${key}` : 'Preparar pruebas'
  if (conversation.origin_kind === 'story') return key ? `Evolucionar ${key}` : 'Evolucionar una HU'
  if (conversation.origin_kind === 'epic') return key ? `HU nueva en la épica ${key}` : 'HU nueva en una épica'
  return 'Nueva necesidad'
}

/** Estado legible (UI.md §9, T-52). Los que UI.md no nombra van en DESIGN-DECISIONS.md §5. */
export function statusLabel(conversation: ConversationSummaryView): string {
  switch (conversation.status) {
    case 'started':
      return 'En curso'
    case 'in_review':
      return conversation.version ? `Versión ${conversation.version}` : 'En revisión'
    case 'approved':
      return 'Aprobada'
    case 'simulated':
      return 'Simulado'
    case 'published':
      return 'Publicado'
    case 'discarded':
      return 'Descartada'
  }
}

export function subtitle(conversation: ConversationSummaryView): string {
  return `${flowLabel(conversation)} · ${statusLabel(conversation)}`
}

export interface ConversationGroup {
  label: string
  items: ConversationSummaryView[]
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
}

const DAY_FORMAT = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'long' })
const DAY_YEAR_FORMAT = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'long', year: 'numeric' })

/** Grupo para fechas que no se pueden leer: no impiden pintar el resto de la lista. */
export const UNDATED_LABEL = 'Sin fecha'

function dayLabel(date: Date, now: Date): string {
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)
  if (dayKey(date) === dayKey(now)) return 'Hoy'
  if (dayKey(date) === dayKey(yesterday)) return 'Ayer'
  return date.getFullYear() === now.getFullYear() ? DAY_FORMAT.format(date) : DAY_YEAR_FORMAT.format(date)
}

/**
 * Agrupa por día de la última actualización («Hoy», «Ayer», «30 de septiembre» o, de otro año,
 * «30 de septiembre de 2025»), de la más reciente a la más antigua. Las fechas no válidas van al final.
 */
export function groupByDay(conversations: readonly ConversationSummaryView[], now: Date): ConversationGroup[] {
  const dated = conversations
    .map((conversation) => ({ conversation, time: Date.parse(conversation.updated_at) }))
    .filter((entry) => Number.isFinite(entry.time))
    .sort((a, b) => b.time - a.time)
  const undated = conversations.filter((conversation) => !Number.isFinite(Date.parse(conversation.updated_at)))

  const groups: Array<ConversationGroup & { key: string }> = []
  for (const { conversation, time } of dated) {
    const date = new Date(time)
    const key = dayKey(date)
    const last = groups.at(-1)
    if (last?.key === key) last.items.push(conversation)
    else groups.push({ key, label: dayLabel(date, now), items: [conversation] })
  }
  if (undated.length > 0) groups.push({ key: 'undated', label: UNDATED_LABEL, items: [...undated] })
  return groups.map(({ label, items }) => ({ label, items }))
}

function normalize(text: string): string {
  return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** Búsqueda local por título, proyecto, flujo y estado, sin distinguir mayúsculas ni tildes. */
export function matchesSearch(conversation: ConversationSummaryView, query: string): boolean {
  const needle = normalize(query.trim())
  if (!needle) return true
  return normalize(`${conversationTitle(conversation.title)} ${conversation.project_key} ${subtitle(conversation)}`).includes(needle)
}
