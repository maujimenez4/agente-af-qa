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
  onFocusLeave,
  inertBehind,
}: {
  /** Capa abierta (y en modo capa: fuera de él no hace nada). */
  open: boolean
  layer: RefObject<HTMLElement | null>
  /** El botón que abre y cierra la capa: recibe el foco al cerrarla. */
  opener: () => HTMLElement | null | undefined
  onClose: () => void
  /** Si el foco sale de la capa (por defecto, `onClose`). Plegar sin preguntar: la capa solo se oculta, no se pierde nada. */
  onFocusLeave?: () => void
  /**
   * Lo que queda tapado por el velo mientras la capa está abierta (PA-343): se marca `inert`, así el modo exploración
   * de los lectores de pantalla no lo recorre y no se puede tocar. El velo, el botón que abre la capa y lo que queda
   * fuera del velo (el carril, la franja) no se tocan: un clic ahí sigue cerrando la capa.
   */
  inertBehind?: () => readonly (Element | null | undefined)[]
}) {
  const wasOpen = useRef(false)
  // El último `opener` sin volver a ejecutar el efecto en cada render (el foco solo se mueve al abrir y al cerrar).
  const openerRef = useRef(opener)
  const onFocusLeaveRef = useRef(onFocusLeave ?? onClose)
  const inertBehindRef = useRef(inertBehind)
  useEffect(() => {
    openerRef.current = opener
    onFocusLeaveRef.current = onFocusLeave ?? onClose
    inertBehindRef.current = inertBehind
  })

  // Al cerrar, se quita antes de devolver el foco al botón (la limpieza va antes que el efecto de cierre de abajo).
  useEffect(() => {
    if (!open) return
    const marked = (inertBehindRef.current?.() ?? []).filter(
      (element): element is Element => element instanceof Element && !element.hasAttribute('inert') && !element.contains(layer.current),
    )
    for (const element of marked) element.setAttribute('inert', '')
    return () => {
      for (const element of marked) element.removeAttribute('inert')
    }
  }, [open, layer])

  useEffect(() => {
    if (open) {
      wasOpen.current = true
      const element = layer.current
      ;(element ? (focusableIn(element)[0] ?? element) : null)?.focus()
      // Si el foco sale de la capa (un clic en la franja o en el carril, que quedan fuera del velo), la capa se
      // cierra: así no se puede tabular hacia lo que queda detrás ni quedan dos capas abiertas a la vez.
      const onFocusIn = (event: FocusEvent) => {
        const target = event.target
        if (!(target instanceof Node) || layer.current?.contains(target) || openerRef.current()?.contains(target)) return
        onFocusLeaveRef.current()
      }
      document.addEventListener('focusin', onFocusIn)
      return () => document.removeEventListener('focusin', onFocusIn)
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
