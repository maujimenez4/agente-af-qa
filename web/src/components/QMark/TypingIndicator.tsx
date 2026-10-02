import styles from './QMark.module.css'
import { QShape } from './QShape.tsx'

// UI.md §4.5: «Escribiendo la respuesta» con la Q de 18 px en bucle mientras se escribe.
export function TypingIndicator() {
  return (
    <div className={styles.typing} role="status">
      <QShape size={18} offset={163} motion={{ kind: 'loop' }} state="typing" />
      <span>Escribiendo la respuesta</span>
    </div>
  )
}
