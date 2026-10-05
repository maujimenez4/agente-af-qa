import { useId } from 'react'
import { Button, type ButtonVariant } from './Button.tsx'
import styles from './Button.module.css'

/** Texto para lectores de pantalla de una acción que aún no está (DESIGN-DECISIONS.md §4 bis). */
export const SOON_TEXT = 'Disponible pronto: llega después del punto de control de la demo.'

export interface SoonButtonProps {
  label: string
  variant?: ButtonVariant
  /** Motivo concreto, si lo hay (p. ej. lo que falta en el contrato); si no, `SOON_TEXT`. */
  note?: string
}

// Acción que aún no está en la demo: enfocable, con su descripción y sin efecto (aria-disabled).
export function SoonButton({ label, variant = 'secondary', note = SOON_TEXT }: SoonButtonProps) {
  const noteId = useId()
  return (
    <>
      <Button variant={variant} className={styles.soon} aria-disabled="true" aria-describedby={noteId}>
        {label}
      </Button>
      <span id={noteId} className="visually-hidden">
        {note}
      </span>
    </>
  )
}
