import type { IconName } from '../Icon/index.ts'

export type Role = 'functional' | 'qa' | 'admin'
export type Zone = 'work' | 'history' | 'settings'

export const ROLE_NAMES: Record<Role, string> = {
  functional: 'Analista funcional',
  qa: 'QA',
  admin: 'Administrador',
}

interface RailItem {
  zone: Zone
  label: string
  icon: IconName
  roles: readonly Role[]
}

// Decisión 16: Historial solo para admin (UI.md §3, PA-62), aunque el lienzo lo muestre a todos (PA-302).
const RAIL_ITEMS: readonly RailItem[] = [
  { zone: 'work', label: 'Trabajo', icon: 'work', roles: ['functional', 'qa'] },
  { zone: 'history', label: 'Historial', icon: 'history', roles: ['admin'] },
  { zone: 'settings', label: 'Ajustes', icon: 'settings', roles: ['admin'] },
]

export function railItemsFor(role: Role): readonly RailItem[] {
  return RAIL_ITEMS.filter((item) => item.roles.includes(role))
}

/** Umbral del aviso de consumo de tokens (lienzo: desde el 90 %). */
export const USAGE_WARNING = 90

export const USAGE_RADIUS = 15
const CIRCUMFERENCE = 2 * Math.PI * USAGE_RADIUS

/** `stroke-dasharray` del anillo para un porcentaje (acotado a 0–100). */
export function usageDash(percent: number): string {
  const clamped = Math.min(Math.max(percent, 0), 100)
  return `${((CIRCUMFERENCE * clamped) / 100).toFixed(1)} ${CIRCUMFERENCE.toFixed(1)}`
}
