// Textos de la lista de conversaciones a partir de `ConversationSummary` (docs/api/openapi.yaml).
// Tipo provisional con los campos que se usan: se sustituirá por el generado con openapi-typescript.

export type ConversationStatus = 'started' | 'in_review' | 'approved' | 'published' | 'simulated' | 'discarded'

export interface ConversationSummaryView {
  thread_id: string
  project_key: string
  mode: 'functional' | 'qa'
  origin_kind: 'epic' | 'story' | 'need'
  origin_key: string | null
  title: string
  status: ConversationStatus
  version: number | null
  updated_at: string
}

/** Flujo de la conversación («Evolucionar DEMO-3», «Nueva necesidad», «Pruebas de DEMO-3»). */
export function flowLabel(conversation: ConversationSummaryView): string {
  const key = conversation.origin_key
  if (conversation.mode === 'qa') return key ? `Pruebas de ${key}` : 'Preparar pruebas'
  if (conversation.origin_kind === 'story') return key ? `Evolucionar ${key}` : 'Evolucionar una HU'
  return 'Nueva necesidad'
}

/** Estado legible (UI.md §9, T-52). Los que UI.md no nombra van en DESIGN-DECISIONS.md §4. */
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

/** Agrupa por día de la última actualización (Hoy, Ayer, «30 de septiembre»), de la más reciente a la más antigua. */
export function groupByDay(conversations: readonly ConversationSummaryView[], now: Date): ConversationGroup[] {
  const today = dayKey(now)
  const yesterday = dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))
  const sorted = [...conversations].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))

  const groups: ConversationGroup[] = []
  for (const conversation of sorted) {
    const date = new Date(conversation.updated_at)
    const key = dayKey(date)
    const label = key === today ? 'Hoy' : key === yesterday ? 'Ayer' : DAY_FORMAT.format(date)
    const last = groups.at(-1)
    if (last?.label === label) last.items.push(conversation)
    else groups.push({ label, items: [conversation] })
  }
  return groups
}

function normalize(text: string): string {
  return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** Búsqueda local por título, proyecto, flujo y estado, sin distinguir mayúsculas ni tildes. */
export function matchesSearch(conversation: ConversationSummaryView, query: string): boolean {
  const needle = normalize(query.trim())
  if (!needle) return true
  return normalize(`${conversation.title} ${conversation.project_key} ${subtitle(conversation)}`).includes(needle)
}
