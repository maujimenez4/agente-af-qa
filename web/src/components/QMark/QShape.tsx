import { useId, type CSSProperties } from 'react'
import { Q_PATH, Q_VIEWBOX } from '../../design/qPath.ts'
import styles from './QMark.module.css'
import { QUARTER } from './qGeometry.ts'

export type QMotion =
  | { kind: 'none' }
  | { kind: 'fill'; from: number; duration: number; delay: number }
  | { kind: 'pulse'; to: number }
  | { kind: 'loop' }

interface QShapeProps {
  size: number
  /** Desplazamiento final del rect (estado real, el que queda sin animación). */
  offset: number
  motion: QMotion
  /** Estado para pruebas y depuración: no se usa para pintar. */
  state: string
}

const MOTION_CLASS: Record<QMotion['kind'], string | undefined> = {
  none: undefined,
  fill: styles.fill,
  pulse: styles.pulse,
  loop: styles.loop,
}

// Pieza común de todas las Q: decorativa (aria-hidden); quien la usa pone el nombre accesible.
export function QShape({ size, offset, motion, state }: QShapeProps) {
  const clipId = `q-clip-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`

  const vars: Record<string, string> = { '--q-to': `${offset}px` }
  if (motion.kind === 'fill') {
    vars['--q-from'] = `${motion.from}px`
    vars['--q-duration'] = `${motion.duration}s`
    vars['--q-delay'] = `${motion.delay}s`
  }
  if (motion.kind === 'pulse') {
    vars['--q-from'] = `${offset}px`
    vars['--q-pulse-to'] = `${motion.to}px`
  }
  if (motion.kind === 'loop') {
    vars['--q-to'] = `${2 * QUARTER}px`
  }

  const rectClass = [styles.rect, MOTION_CLASS[motion.kind]].filter(Boolean).join(' ')

  return (
    <svg
      className={styles.svg}
      viewBox={`0 0 ${Q_VIEWBOX} ${Q_VIEWBOX}`}
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      data-q-state={state}
      data-q-offset={motion.kind === 'loop' ? 2 * QUARTER : offset}
    >
      <defs>
        <clipPath id={clipId}>
          <rect
            className={rectClass}
            x="0"
            y="0"
            width={Q_VIEWBOX}
            height={Q_VIEWBOX}
            style={vars as CSSProperties}
            data-q-motion={motion.kind}
          />
        </clipPath>
      </defs>
      <path className={styles.empty} d={Q_PATH} />
      <path className={styles.filled} d={Q_PATH} clipPath={`url(#${clipId})`} />
    </svg>
  )
}
