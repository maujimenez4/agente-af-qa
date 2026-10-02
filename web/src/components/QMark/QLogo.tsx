import { Q_PATH, Q_VIEWBOX } from '../../design/qPath.ts'

export interface QLogoProps {
  size?: number
  /** Si se da, el logotipo se anuncia con este texto; si no, es decorativo. */
  label?: string
  className?: string
}

// Logotipo: la Q llena en naranja (carril, inicio y avatar del asistente).
export function QLogo({ size = 34, label, className }: QLogoProps) {
  const a11y = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true }
  return (
    <svg
      viewBox={`0 0 ${Q_VIEWBOX} ${Q_VIEWBOX}`}
      width={size}
      height={size}
      className={className}
      focusable="false"
      style={{ display: 'block', flexShrink: 0 }}
      {...a11y}
    >
      <path d={Q_PATH} fill="var(--color-primary)" />
    </svg>
  )
}
