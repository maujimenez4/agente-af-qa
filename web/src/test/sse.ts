// Flujo SSE de prueba que no termina solo: se cierra cuando la prueba llama a `end()` o al limpiar
// (`closeOpenEventStreams` en `afterEach`). Un flujo que se cierra solo hace que el cliente relea la
// conversación y salga de Generando, y las pruebas que miran Generando dependerían de una carrera.
import { HttpResponse } from 'msw'

const open = new Set<ReadableStreamDefaultController<Uint8Array>>()

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

/** Cierra los flujos que sigan abiertos (el cliente lo ve como fin del flujo). */
export function closeOpenEventStreams(): void {
  for (const controller of open) {
    try {
      controller.close()
    } catch {
      // Ya cerrado o cancelado por el cliente.
    }
  }
  open.clear()
}
