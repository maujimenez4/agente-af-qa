import { Q_PATH } from '../../design/qPath.ts'
import { QARACTER_LETTER_PATHS, QARACTER_VIEWBOX } from '../../design/qaracterLogo.ts'

/**
 * Color de las letras del original. Un logotipo de marca no cambia con el tema: va literal, aunque hoy
 * coincide con `--color-text` (#233441).
 */
const LETTERS_FILL = '#233441'

export interface QaracterLogoProps {
  /** Alto en píxeles; el ancho sale de la proporción del original. Mínimo de marca: 24 px. */
  height?: number
  /** Nombre accesible; con `null`, decorativo (si al lado ya está el nombre de la marca). */
  label?: string | null
  className?: string
}

// PA-444 · Logotipo completo de Qaracter (la Q y las letras) para el inicio de sesión. Va dentro del código,
// como `QLogo`: ni archivos externos ni URL. La Q usa `--color-primary` (#FF7932, el del original).
export function QaracterLogo({ height = 40, label = 'Qaracter', className }: QaracterLogoProps) {
  const width = Math.round((height * QARACTER_VIEWBOX.width) / QARACTER_VIEWBOX.height)
  const a11y = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true }
  return (
    <svg
      viewBox={`0 0 ${QARACTER_VIEWBOX.width} ${QARACTER_VIEWBOX.height}`}
      width={width}
      height={height}
      className={className}
      focusable="false"
      style={{ display: 'block', flexShrink: 0 }}
      {...a11y}
    >
      <path d={Q_PATH} fill="var(--color-primary)" />
      {QARACTER_LETTER_PATHS.map((d, index) => (
        <path key={index} d={d} fill={LETTERS_FILL} />
      ))}
    </svg>
  )
}
