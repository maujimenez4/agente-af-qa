import { ASSISTANT_NAME } from '../../text/assistant.ts'
import styles from './FaqLogo.module.css'
import { QLogo } from './QLogo.tsx'

/** «FA» en DM Sans 800 a 120 px: la altura de sus mayúsculas es 84 px, la de la Q (docs/diseno/faq/README.md §1). */
const Q_SIZE = 84

// PA-478 · Logotipo del asistente para el inicio de sesión: «FA» y la Q de Qaracter (`Q_PATH`, `--color-primary`),
// alineadas a la línea base, así que coinciden arriba y abajo. Es una sola imagen «FAQ»; sus partes son decorativas.
// Si el nombre cambia (`ASSISTANT_NAME`), este logotipo se rehace a mano: la Q es la última letra.
export function FaqLogo({ className }: { className?: string }) {
  return (
    <span role="img" aria-label={ASSISTANT_NAME} className={[styles.logo, className].filter(Boolean).join(' ')}>
      <span className={styles.letters} aria-hidden="true">
        FA
      </span>
      <QLogo size={Q_SIZE} className={styles.q} />
    </span>
  )
}
