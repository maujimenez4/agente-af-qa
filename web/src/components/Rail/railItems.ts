import { formatNumber } from '../../text/numbers.ts'
import type { Role, UsageTodayOut } from '../../api/types.ts'
import type { IconName } from '../Icon/index.ts'

export type { Role }
export type Zone = 'work' | 'history' | 'settings'

export const ROLE_NAMES: Record<Role, string> = {
  functional: 'Analista funcional',
  qa: 'QA',
  admin: 'Administrador',
}

export interface RailItem {
  zone: Zone
  label: string
  icon: IconName
  roles: readonly Role[]
  /** Aún no está en el contrato: se ve en el carril como «disponible pronto» y no se puede abrir. */
  soon?: boolean
}

// Decisión 16 (PA-302): Historial solo para admin y «disponible pronto» (T-45 es Could y no está en el contrato).
const RAIL_ITEMS: readonly RailItem[] = [
  { zone: 'work', label: 'Trabajo', icon: 'work', roles: ['functional', 'qa'] },
  { zone: 'history', label: 'Historial', icon: 'history', roles: ['admin'], soon: true },
  { zone: 'settings', label: 'Ajustes', icon: 'settings', roles: ['admin'] },
]

export function railItemsFor(role: Role): readonly RailItem[] {
  return RAIL_ITEMS.filter((item) => item.roles.includes(role))
}

/** Zona con la que entra cada rol (la primera que se puede abrir). */
export function homeZone(role: Role): Zone {
  return railItemsFor(role).find((item) => !item.soon)?.zone ?? 'work'
}

export type UsageToday = Pick<UsageTodayOut, 'tokens_today' | 'warning_threshold'>

export interface UsageView {
  /** `tokens_today / warning_threshold`, redondeado y acotado a 0–100. */
  percent: number
  warning: boolean
  label: string
}


/**
 * Lo que pinta el anillo con el consumo de hoy de toda la instalación (decisión 17, PA-305).
 * Sin dato válido devuelve `undefined` y el anillo no se pinta.
 */
export function usageView(usage: UsageToday | undefined): UsageView | undefined {
  if (!usage) return undefined
  const { tokens_today: tokens, warning_threshold: threshold } = usage
  if (!Number.isFinite(tokens) || !Number.isFinite(threshold) || threshold <= 0) return undefined
  const percent = Math.round(Math.min(Math.max((tokens / threshold) * 100, 0), 100))
  return {
    percent,
    warning: tokens >= threshold,
    label: `Consumo de tokens de hoy de toda la instalación: ${formatNumber(Math.max(tokens, 0))} de ${formatNumber(threshold)}, ${percent} % del umbral de aviso`,
  }
}

export const USAGE_RADIUS = 15
const CIRCUMFERENCE = 2 * Math.PI * USAGE_RADIUS

/** `stroke-dasharray` del anillo para un porcentaje (acotado a 0–100). */
export function usageDash(percent: number): string {
  const clamped = Math.min(Math.max(percent, 0), 100)
  return `${((CIRCUMFERENCE * clamped) / 100).toFixed(1)} ${CIRCUMFERENCE.toFixed(1)}`
}
