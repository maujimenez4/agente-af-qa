import { useEffect, type RefObject } from 'react'

/** A cuántos píxeles del final se considera que la persona «está abajo» (sigue la conversación). */
export const NEAR_BOTTOM_PX = 120

/** Un mensaje de la persona (`UserMessage` lo marca): siempre se baja hasta él. */
const OWN_MESSAGE = '[data-author="user"]'

function reducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function containsOwnMessage(nodes: NodeList): boolean {
  for (const node of nodes) {
    if (node instanceof Element && (node.matches(OWN_MESSAGE) || node.querySelector(OWN_MESSAGE))) return true
  }
  return false
}

/**
 * PA-429: al llegar contenido nuevo a la conversación, desplaza `scrollRef` hasta el final (margen incluido) si
 * la persona ya estaba cerca del final; un mensaje suyo baja siempre. Si ha subido a leer, no se la mueve.
 */
export function useStickToBottom(scrollRef: RefObject<HTMLElement | null>, contentRef: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const scroller = scrollRef.current
    const content = contentRef.current
    if (!scroller || !content || typeof MutationObserver === 'undefined') return

    let nearBottom = true
    // Bajando por nuestra cuenta (animación suave): los `scroll` intermedios no son la persona subiendo.
    let following = false
    const onScroll = () => {
      const near = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= NEAR_BOTTOM_PX
      if (near) following = false
      nearBottom = near || following
    }
    const toBottom = () => {
      following = true
      const top = scroller.scrollHeight
      if (typeof scroller.scrollTo === 'function') scroller.scrollTo({ top, behavior: reducedMotion() ? 'auto' : 'smooth' })
      else scroller.scrollTop = top
      nearBottom = true
    }

    const observer = new MutationObserver((mutations) => {
      const own = mutations.some((mutation) => containsOwnMessage(mutation.addedNodes))
      if (own || nearBottom) toBottom()
    })
    // Al abrir una conversación se empieza por el final, sin animación.
    scroller.scrollTop = scroller.scrollHeight
    observer.observe(content, { childList: true, subtree: true, characterData: true })
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      observer.disconnect()
      scroller.removeEventListener('scroll', onScroll)
    }
  }, [scrollRef, contentRef])
}
