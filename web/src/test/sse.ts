// Flujo SSE de prueba que no termina solo: se cierra cuando la prueba llama a `end()` o al limpiar
// (`closeOpenEventStreams` en `afterEach`). Un flujo que se cierra solo hace que el cliente relea la
// conversación y salga de Generando, y las pruebas que miran Generando dependerían de una carrera.
import { http, HttpResponse } from 'msw'
import { mockServer } from '../mocks/node.ts'

const open = new Set<ReadableStreamDefaultController<Uint8Array>>()
const held = new Set<() => void>()

/** Respuesta para el handler de `/events`: un latido y el flujo abierto. */
export function openEventStream(): HttpResponse<ReadableStream<Uint8Array>> {
  let own: ReadableStreamDefaultController<Uint8Array> | undefined
  return new HttpResponse(
    new ReadableStream<Uint8Array>({
      start(controller) {
        own = controller
        open.add(controller)
        controller.enqueue(new TextEncoder().encode(': latido\n\n'))
      },
      cancel() {
        if (own) open.delete(own)
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}

/**
 * PA-127: el siguiente `/events` espera hasta que la prueba llame a la función devuelta; después lo responde
 * la API simulada como siempre (pasos, parada entre pasos y evento final). Sin reloj: lo que pasa mientras
 * tanto (p. ej. «Deteniendo…» tras *Detener*) se queda fijo hasta que la prueba lo suelta.
 */
export function holdNextEventStream(): () => void {
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  held.add(release)
  let taken = false
  mockServer.use(
    http.get('/api/v1/conversations/:id/events', async () => {
      if (taken) return undefined
      taken = true
      await gate
      // Sin respuesta: la petición sigue al handler de la API simulada.
      return undefined
    }),
  )
  return () => {
    held.delete(release)
    release()
  }
}

/** Cierra los flujos que sigan abiertos (el cliente lo ve como fin del flujo) y suelta los retenidos. */
export function closeOpenEventStreams(): void {
  for (const controller of open) {
    try {
      controller.close()
    } catch {
      // Ya cerrado o cancelado por el cliente.
    }
  }
  open.clear()
  for (const release of held) release()
  held.clear()
}
