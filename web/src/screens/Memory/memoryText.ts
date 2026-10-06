// Textos de Memoria (PA-329, sin pantalla en el lienzo ni en UI.md): lista de `GET /memories` y detalle de
// `GET /memories/{key}`. Lo que escribió el LLM (`memory`) se pinta como texto; el `.md` solo se descarga.
import type { MemoryOut } from '../../api/types.ts'

/** Se piden todas de una vez (el máximo del contrato) y la lista se desplaza dentro de su columna. */
export const MEMORY_LIMIT = 200

/** Espera tras la última pulsación en el buscador antes de volver a pedir la lista. */
export const MEMORY_SEARCH_DEBOUNCE_MS = 300

/** Lista vacía sin filtros (docs/api/README.md, «Novedades para el frontend»). */
export const NO_MEMORIES = 'Aún no hay memorias. Se generan al publicar una HU en Jira (modo real).'
/** Lista vacía con un proyecto o una búsqueda. */
export const NO_MATCHES = 'Ninguna memoria coincide con el proyecto o la búsqueda.'

export const LIST_NOTE = 'Cada HU publicada deja su memoria, que tiene prioridad en las próximas propuestas.'

export type MemoryContent = MemoryOut['memory']
type TextField = 'objective' | 'scope'
type ListField = 'business_rules' | 'acceptance_criteria' | 'decisions' | 'dependencies' | 'changes' | 'references'

export type MemorySection = { title: string } & ({ kind: 'text'; field: TextField } | { kind: 'list'; field: ListField })

/** Secciones del detalle, en el orden del `.md` que se descarga (`schemas/memory.py`, ejemplo del contrato). */
export const MEMORY_SECTIONS: readonly MemorySection[] = [
  { title: 'Objetivo', kind: 'text', field: 'objective' },
  { title: 'Alcance', kind: 'text', field: 'scope' },
  { title: 'Reglas de negocio', kind: 'list', field: 'business_rules' },
  { title: 'Decisiones', kind: 'list', field: 'decisions' },
  { title: 'Dependencias', kind: 'list', field: 'dependencies' },
  { title: 'Cambios', kind: 'list', field: 'changes' },
  { title: 'Criterios de aceptación', kind: 'list', field: 'acceptance_criteria' },
  { title: 'Referencias', kind: 'list', field: 'references' },
]

/** El texto de una sección, sin espacios sobrantes; con algo raro (no es texto), vacío. */
export function sectionText(memory: MemoryContent, field: TextField): string {
  const value: unknown = memory[field]
  return typeof value === 'string' ? value.trim() : ''
}

/** Los puntos de una sección: solo textos no vacíos. */
export function sectionItems(memory: MemoryContent, field: ListField): string[] {
  const value: unknown = memory[field]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : []
}

export const INDEXED_TEXT = {
  true: { label: 'Indexada', note: 'Está en la base de conocimiento: se usa como fuente prioritaria en las próximas propuestas.' },
  false: { label: 'No indexada', note: 'Aún no está en la base de conocimiento: todavía no se usa como fuente.' },
} as const

const DATE = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
const SHORT_DATE = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', timeZone: 'UTC' })

/** «2 de octubre de 2026»; si no se puede leer, `undefined`. */
export function memoryDate(value: string): string | undefined {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? undefined : DATE.format(date)
}

/** «2 oct» para la lista; si no se puede leer, `undefined`. */
export function memoryShortDate(value: string): string | undefined {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? undefined : SHORT_DATE.format(date).replace('.', '')
}

/** Nombre del `.md` que se descarga: `memoria-DEMO-3.md`. */
export function memoryFileName(key: string): string {
  return `memoria-${key}.md`
}
