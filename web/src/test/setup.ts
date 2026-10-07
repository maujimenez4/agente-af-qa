import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { setCsrfToken } from '../api/client.ts'
import { mockServer, resetMockApi } from '../mocks/node.ts'
import { closeOpenEventStreams } from './sse.ts'

// Con toda la suite en paralelo, 1 s de espera por defecto se queda corto en equipos lentos.
configure({ asyncUtilTimeout: 3000 })

// PA-127: peticiones aún en curso al acabar el archivo (p. ej. la recarga de la lista que lanza la última
// pantalla al desmontarse). Si MSW se cierra antes de que terminen, salen a la red real.
let inFlight = 0
let interceptedFetch: typeof fetch | undefined
/** Tope para esperarlas al cerrar: no alarga ninguna prueba, solo el cierre del archivo. */
const DRAIN_LIMIT_MS = 1000

// API simulada para todas las pruebas: una petición sin handler es un error, no una llamada real.
beforeAll(() => {
  mockServer.listen({ onUnhandledFrame: 'error' })
  const intercepted = globalThis.fetch
  interceptedFetch = intercepted
  globalThis.fetch = ((...args: Parameters<typeof fetch>) => {
    inFlight += 1
    return intercepted(...args).finally(() => {
      inFlight -= 1
    })
  }) as typeof fetch
})

beforeEach(() => {
  resetMockApi()
  setCsrfToken(null)
})

afterEach(() => {
  cleanup()
  closeOpenEventStreams()
})

afterAll(async () => {
  const limit = Date.now() + DRAIN_LIMIT_MS
  while (inFlight > 0 && Date.now() < limit) await new Promise((resolve) => setTimeout(resolve, 10))
  if (interceptedFetch) globalThis.fetch = interceptedFetch
  mockServer.close()
})
