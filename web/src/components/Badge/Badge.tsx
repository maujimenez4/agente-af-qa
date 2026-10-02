import type { ReactNode } from 'react'
import { Icon, type IconName } from '../Icon/index.ts'
import styles from './Badge.module.css'
import { CASE_KIND_TONE, type BadgeTone, type CaseKind } from './badgeTones.ts'

export interface BadgeProps {
  tone?: BadgeTone
  size?: 'sm' | 'md'
  icon?: IconName
  children: ReactNode
}

// Etiqueta no interactiva: «Nueva», «Cambiado en v2», DOC-01, «Todos los CA cubiertos», «Aprobada · simulada»…
export function Badge({ tone = 'neutral', size = 'sm', icon, children }: BadgeProps) {
  return (
    <span className={[styles.badge, styles[size], styles[tone]].join(' ')} data-tone={tone}>
      {icon && <Icon name={icon} size={size === 'md' ? 16 : 14} />}
      {children}
    </span>
  )
}

export function CaseKindBadge({ kind }: { kind: CaseKind }) {
  return <Badge tone={CASE_KIND_TONE[kind]}>{kind}</Badge>
}
