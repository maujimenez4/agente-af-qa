import type { ReactNode } from 'react'
import { Button } from '../components/Button/index.ts'

interface DemoButtonProps {
  /** Si se da, el botón es un conmutador (aria-pressed) y se resalta al estar activo. */
  pressed?: boolean
  onClick: () => void
  children: ReactNode
}

// Botón de los controles de las demos del catálogo, hecho con el Button del sistema.
export function DemoButton({ pressed, onClick, children }: DemoButtonProps) {
  return (
    <Button size="md" variant={pressed ? 'primary' : 'secondary'} aria-pressed={pressed} onClick={onClick}>
      {children}
    </Button>
  )
}
