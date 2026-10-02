import { ICONS, type IconName, type IconShape } from './icons.ts'

export interface IconProps {
  name: IconName
  /** Lado en px; 18 en las pantallas, 24 en el carril. */
  size?: number
  /** Si se da, el icono se anuncia con este texto; si no, es decorativo. */
  label?: string
  className?: string
}

// Hereda el color del texto (currentColor), como en el lienzo.
export function Icon({ name, size = 18, label, className }: IconProps) {
  const shape: IconShape = ICONS[name]
  const a11y = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true }

  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      style={{ flexShrink: 0 }}
      data-icon={name}
      {...a11y}
    >
      <path d={shape.d} fill={shape.filled ? 'currentColor' : undefined} stroke={shape.filled ? 'none' : undefined} />
    </svg>
  )
}
