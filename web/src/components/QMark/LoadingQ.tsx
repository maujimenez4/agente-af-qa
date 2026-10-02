import { useState } from 'react'
import { offsetFor, QUARTER } from './qGeometry.ts'
import { QShape, type QMotion } from './QShape.tsx'

export interface LoadingQProps {
  /** Cuartos llenos (0 a 4), normalmente de `loadingProgress`. */
  done: number
  /** `generate` en curso: se anima dentro del cuarto siguiente. */
  running?: boolean
  size?: number
  /** Si se da, la Q se anuncia con este texto; si no, es decorativa (la lista de procesos ya informa). */
  label?: string
}

// Q de carga por procesos (UI.md §8, n.º 2): cada cuarto se llena al terminar su proceso.
export function LoadingQ({ done, running = false, size = 48, label }: LoadingQProps) {
  const [shown, setShown] = useState({ done, from: done })
  if (shown.done !== done) setShown({ done, from: shown.done })

  const offset = offsetFor(done)
  let motion: QMotion = { kind: 'none' }
  if (running && done < 4) motion = { kind: 'pulse', to: offset - QUARTER }
  else if (shown.from !== done) motion = { kind: 'fill', from: offsetFor(shown.from), duration: 0.42, delay: 0 }

  const shape = (
    <QShape key={`${done}-${motion.kind}`} size={size} offset={offset} motion={motion} state={`loading-${done}`} />
  )
  if (!label) return shape
  return (
    <span role="img" aria-label={label} style={{ display: 'inline-flex' }}>
      {shape}
    </span>
  )
}
