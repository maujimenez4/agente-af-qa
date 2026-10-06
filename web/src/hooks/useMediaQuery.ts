import { useCallback, useSyncExternalStore } from 'react'

function listFor(query: string): MediaQueryList | null {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query) : null
}

/** true mientras se cumple la media query (sin `matchMedia`, como en jsdom, siempre false). */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const media = listFor(query)
      media?.addEventListener('change', onChange)
      return () => media?.removeEventListener('change', onChange)
    },
    [query],
  )
  return useSyncExternalStore(
    subscribe,
    () => listFor(query)?.matches ?? false,
    () => false,
  )
}
