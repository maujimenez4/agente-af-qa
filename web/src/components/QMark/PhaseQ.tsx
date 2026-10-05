import { useState } from 'react'
import { offsetFor, PHASE_NAMES, type Phase } from './qGeometry.ts'
import styles from './QMark.module.css'
import { QShape } from './QShape.tsx'

export interface PhaseQProps {
  phase: Phase
  /** Otro nombre para la fase (p. ej. «Aprobada» en la publicación simulada). */
  name?: string
  size?: number
}

// Q de fase de la cabecera: sube un cuarto al pasar de fase (0,42 s con 0,25 s de retardo).
export function PhaseQ({ phase, name, size = 26 }: PhaseQProps) {
  // Al subir de fase se anima desde la fase que se veía. La primera vez, o al bajar de fase
  // (otra conversación con la cabecera montada), desde la anterior: nunca parte de una Q más llena.
  const [shown, setShown] = useState({ phase, from: phase - 1 })
  if (shown.phase !== phase) setShown({ phase, from: phase > shown.phase ? shown.phase : phase - 1 })

  const label = name ?? PHASE_NAMES[phase]

  return (
    <div className={styles.phase} role="img" aria-label={`Avance: fase ${phase} de 4, ${label}`}>
      <QShape
        key={phase}
        size={size}
        offset={offsetFor(phase)}
        motion={{ kind: 'fill', from: offsetFor(shown.from), duration: 0.42, delay: 0.25 }}
        state={`phase-${phase}`}
      />
      <span aria-hidden="true">
        <b className={styles.phaseStrong}>Fase {phase} de 4</b>
        <span className={styles.phaseName}> · {label}</span>
      </span>
    </div>
  )
}
