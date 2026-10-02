// Eventos en vivo de una conversación (GET /conversations/{id}/events, text/event-stream).
// Se leen con fetch y un ReadableStream (no EventSource): se cierran con AbortController tras `result`,
// no reconectan solos y se pueden probar con MSW. Si se corta, quien escucha consulta GET /conversations/{id}.
import { apiUrl } from './client.ts'
import type { ApiError, ProgressStep } from './types.ts'

export interface ConversationEvents {
  onProgress?: (step: ProgressStep) => void
  onReviewReady?: (data: { id: string; state: string }) => void
  onResult?: (data: unknown) => void
  onError?: (data: unknown) => void
  /** El flujo terminó o se cortó sin `result`: hay que consultar el estado con GET. */
  onDisconnect?: (reason: 'ended' | 'failed') => void
}

interface ServerEvent {
  event: string
  data: string
}

/** Parte un bloque de texto SSE en eventos completos y devuelve lo que queda a medias. */
export function parseEventStream(buffer: string): { events: ServerEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const blocks = normalized.split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: ServerEvent[] = []
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue // comentario o latido
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (data.length > 0) events.push({ event, data: data.join('\n') })
  }
  return { events, rest }
}

function parseData(data: string): unknown {
  try {
    return JSON.parse(data) as unknown
  } catch {
    return undefined
  }
}

/** Escucha los eventos de una conversación. Devuelve la función para cerrar el flujo. */
export function subscribeEvents(conversationId: string, handlers: ConversationEvents): () => void {
  const controller = new AbortController()
  let closed = false
  const close = () => {
    closed = true
    controller.abort()
  }

  const dispatch = ({ event, data }: ServerEvent) => {
    if (closed) return
    const payload = parseData(data)
    if (payload === undefined) return
    if (event === 'progress') handlers.onProgress?.(payload as ProgressStep)
    else if (event === 'review_ready') handlers.onReviewReady?.(payload as { id: string; state: string })
    else if (event === 'error') handlers.onError?.(payload)
    else if (event === 'result') {
      handlers.onResult?.(payload)
      close() // DESIGN-DECISIONS.md §4: el cliente cierra tras `result`.
    }
  }

  void (async () => {
    try {
      const response = await fetch(apiUrl(`/conversations/${encodeURIComponent(conversationId)}/events`), {
        headers: { Accept: 'text/event-stream' },
        credentials: 'same-origin',
        signal: controller.signal,
      })
      if (!response.ok || !response.body) {
        const body = (await response.json().catch(() => undefined)) as { error?: ApiError } | undefined
        if (body?.error) handlers.onError?.(body.error)
        if (!closed) handlers.onDisconnect?.('failed')
        return
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parsed = parseEventStream(buffer)
        buffer = parsed.rest
        parsed.events.forEach(dispatch)
        if (closed) return
      }
      parseEventStream(`${buffer}\n\n`).events.forEach(dispatch)
      if (!closed) handlers.onDisconnect?.('ended')
    } catch {
      if (!closed) handlers.onDisconnect?.('failed')
    }
  })()

  return close
}
