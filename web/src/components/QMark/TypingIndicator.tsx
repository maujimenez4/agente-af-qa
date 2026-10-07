import styles from './QMark.module.css'
import { QShape } from './QShape.tsx'

// UI.md §4.5: la Q de 18 px en bucle con su texto; Iterar pasa «Generando una nueva versión…» (PA-430).
export function TypingIndicator({ label = 'Escribiendo la respuesta' }: { label?: string }) {
  return (
    <div className={styles.typing} role="status">
      <QShape size={18} offset={163} motion={{ kind: 'loop' }} state="typing" />
      <span>{label}</span>
    </div>
  )
}
