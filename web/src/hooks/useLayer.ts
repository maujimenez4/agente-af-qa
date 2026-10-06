import { useEffect, useRef, type KeyboardEvent, type RefObject } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

const focusableIn = (layer: HTMLElement) =>
  [...layer.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((element) => !element.closest('[hidden]'))

/**
 * Capa sobre la pantalla (PA-335: la lista de conversaciones y el panel derecho en ventanas estrechas), con el
 * patrón dialog de WAI-ARIA: al abrirse, el foco entra en la capa; Esc la cierra; Tab no sale de ella; al
 * cerrarse, el foco vuelve al botón que la abre. El clic fuera lo resuelve el velo de quien la pinta.
 */
export function useLayer({
  open,
  layer,
  opener,
  onClose,
}: {
  /** Capa abierta (y en modo capa: fuera de él no hace nada). */
  open: boolean
  layer: RefObject<HTMLElement | null>
  /** El botón que abre y cierra la capa: recibe el foco al cerrarla. */
  opener: () => HTMLElement | null | undefined
  onClose: () => void
}) {
  const wasOpen = useRef(false)
  // El último `opener` sin volver a ejecutar el efecto en cada render (el foco solo se mueve al abrir y al cerrar).
  const openerRef = useRef(opener)
  useEffect(() => {
    openerRef.current = opener
  })

  useEffect(() => {
    if (open) {
      wasOpen.current = true
      const element = layer.current
      ;(element ? (focusableIn(element)[0] ?? element) : null)?.focus()
      return
    }
    // Al cerrarse (no al montar cerrada), el foco vuelve al botón si se había quedado en la capa o en el vacío.
    if (!wasOpen.current) return
    wasOpen.current = false
    const active = document.activeElement
    if (!active || active === document.body || layer.current?.contains(active)) openerRef.current()?.focus()
  }, [open, layer])

  /** Para el `onKeyDown` de la capa: Esc cierra y Tab da la vuelta dentro de ella. */
  return (event: KeyboardEvent<HTMLElement>) => {
    if (!open) return
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !layer.current) return
    const focusable = focusableIn(layer.current)
    const first = focusable[0]
    const last = focusable.at(-1)
    if (!first || !last) {
      event.preventDefault()
      return
    }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === layer.current)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }
}
