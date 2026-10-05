// Criterio 2 (T-56, días 2-4): huecos de events.test.ts. Lectura del SSE con fetch a trozos, cierre tras
// `result`, evento `error` y cuándo se avisa de la desconexión (DESIGN-DECISIONS.md §3 y §4).
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { mockServer } from '../mocks/node.ts'
import { parseEventStream, subscribeEvents } from './events.ts'

const EVENTS = '/api/v1/conversations/:id/events'

/** Respuesta SSE que llega en los trozos de bytes indicados, con una pausa entre ellos. */
function chunked(chunks: Uint8Array[]) {
  return () => {
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(chunk)
          await delay(5)
        }
        controller.close()
      },
    })
    return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
  }
}

const encoder = new TextEncoder()
const text = (...parts: string[]) => parts.map((part) => encoder.encode(part))

/** Parte el texto en bytes por las posiciones dadas (pueden caer dentro de un carácter UTF-8). */
function splitBytes(source: string, cuts: number[]): Uint8Array[] {
  const bytes = encoder.encode(source)
  const edges = [0, ...cuts, bytes.length]
  return edges.slice(1).map((end, index) => bytes.slice(edges[index], end))
}

const step = (node: string, state: string, label = 'Paso ficticio') => JSON.stringify({ node, label, state })

describe('parseEventStream: casos de límite', () => {
  it('test_parse_joins_multiline_data_with_newline', () => {
    /** Criterio 2: varias líneas `data:` de un evento se unen con \n. */
    const { events, rest } = parseEventStream('event: progress\ndata: {"a":\ndata: 1}\n\n')
    expect(events).toEqual([{ event: 'progress', data: '{"a":\n1}' }])
    expect(rest).toBe('')
  })

  it('test_parse_accepts_data_without_space_and_defaults_to_message', () => {
    /** Criterio 2: `data:x` sin espacio vale; sin `event:` el tipo es «message». */
    expect(parseEventStream('data:{"x":1}\n\n').events).toEqual([{ event: 'message', data: '{"x":1}' }])
  })

  it('test_parse_ignores_id_retry_and_events_without_data', () => {
    /** Criterio 2: `id:`, `retry:` y un evento sin datos no generan eventos. */
    const { events } = parseEventStream('id: 7\nretry: 1000\n\nevent: progress\n\nevent: result\nid: 8\ndata: {}\n\n')
    expect(events).toEqual([{ event: 'result', data: '{}' }])
  })

  it('test_parse_keeps_incomplete_event_until_blank_line', () => {
    /** Criterio 2 (límite): un evento sin la línea en blanco final queda a medias. */
    const first = parseEventStream('event: progress\ndata: {"a":1}\n')
    expect(first.events).toEqual([])
    const second = parseEventStream(`${first.rest}\n`)
    expect(second.events).toEqual([{ event: 'progress', data: '{"a":1}' }])
  })

  it('test_parse_handles_crlf_split_between_reads', () => {
    /** Criterio 2 (límite): un CRLF partido entre dos lecturas no pierde el evento. */
    const first = parseEventStream('event: progress\r\ndata: {"a":1}\r\n\r')
    const second = parseEventStream(`${first.rest}\n`)
    expect([...first.events, ...second.events]).toEqual([{ event: 'progress', data: '{"a":1}' }])
  })
})

describe('subscribeEvents: trozos de red', () => {
  it('test_events_split_mid_event_are_delivered_once_in_order', async () => {
    /** Criterio 2: un evento partido en varios trozos (incluso dentro de «event:» y del separador) llega entero. */
    const body = `event: progress\ndata: ${step('load_origin', 'running')}\n\nevent: progress\ndata: ${step('load_origin', 'done')}\n\n`
    const cut = body.indexOf('\n\n') + 1 // entre los dos \n del separador
    mockServer.use(
      http.get(EVENTS, chunked(text(body.slice(0, 4), body.slice(4, 30), body.slice(30, cut), body.slice(cut, cut + 9), body.slice(cut + 9)))),
    )
    const states: string[] = []
    const onDisconnect = vi.fn()
    subscribeEvents('c-1', { onProgress: (item) => states.push(`${item.node}:${item.state}`), onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('ended'))
    expect(states).toEqual(['load_origin:running', 'load_origin:done'])
  })

  it('test_multibyte_utf8_split_between_chunks_keeps_label', async () => {
    /** Criterio 2: una tilde partida entre dos trozos de bytes no corrompe el label. */
    const label = 'Generar la propuesta, validar las citas y analizar el impacto · préstamo'
    const body = `event: progress\ndata: ${step('generate', 'running', label)}\n\n`
    const accent = encoder.encode(body.slice(0, body.indexOf('é'))).length + 1 // dentro de «é» (2 bytes)
    mockServer.use(http.get(EVENTS, chunked(splitBytes(body, [accent]))))
    const labels: string[] = []
    const onDisconnect = vi.fn()
    subscribeEvents('c-1', { onProgress: (item) => labels.push(item.label), onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalled())
    expect(labels).toEqual([label])
  })

  it('test_multiline_data_over_network_is_parsed_as_json', async () => {
    /** Criterio 2: un JSON repartido en varias líneas `data:` se entrega como un objeto. */
    mockServer.use(http.get(EVENTS, chunked(text('event: review_ready\ndata: {"id":"c-1",\n', 'data: "state":"in_review"}\n\n'))))
    const onReviewReady = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('c-1', { onReviewReady, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalled())
    expect(onReviewReady).toHaveBeenCalledWith({ id: 'c-1', state: 'in_review' })
  })

  it('test_last_event_without_blank_line_is_delivered_at_end', async () => {
    /** Criterio 2 (límite): el último evento sin línea en blanco se entrega al cerrar el flujo. */
    mockServer.use(http.get(EVENTS, chunked(text('event: review_ready\ndata: {"id":"c-1","state":"in_review"}'))))
    const onReviewReady = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('c-1', { onReviewReady, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('ended'))
    expect(onReviewReady).toHaveBeenCalledTimes(1)
  })

  it('test_unknown_events_and_heartbeats_are_ignored', async () => {
    /** Criterio 2: latidos y eventos que no conoce no llegan a ningún manejador. */
    mockServer.use(
      http.get(EVENTS, chunked(text(': ping\n\n', 'event: futuro\ndata: {"x":1}\n\n', `event: progress\ndata: ${step('load_origin', 'done')}\n\n`))),
    )
    const handlers = { onProgress: vi.fn(), onReviewReady: vi.fn(), onResult: vi.fn(), onError: vi.fn(), onDisconnect: vi.fn() }
    subscribeEvents('c-1', handlers)
    await vi.waitFor(() => expect(handlers.onDisconnect).toHaveBeenCalled())
    expect(handlers.onProgress).toHaveBeenCalledTimes(1)
    expect(handlers.onReviewReady).not.toHaveBeenCalled()
    expect(handlers.onResult).not.toHaveBeenCalled()
    expect(handlers.onError).not.toHaveBeenCalled()
  })
})

describe('subscribeEvents: cierre tras result', () => {
  it('test_nothing_dispatched_after_result_in_later_chunks', async () => {
    /** Criterio 2: tras `result` no se entrega nada de los trozos siguientes ni se avisa de desconexión. */
    mockServer.use(
      http.get(
        EVENTS,
        chunked(
          text(
            'event: result\ndata: {"mode":"simulation"}\n\n',
            `event: progress\ndata: ${step('memorize', 'done')}\n\n`,
            'event: error\ndata: {"code":"unexpected","message":"x"}\n\n',
          ),
        ),
      ),
    )
    const handlers = { onResult: vi.fn(), onProgress: vi.fn(), onError: vi.fn(), onDisconnect: vi.fn() }
    subscribeEvents('c-1', handlers)
    await vi.waitFor(() => expect(handlers.onResult).toHaveBeenCalledTimes(1))
    await new Promise((resolve) => setTimeout(resolve, 40))
    expect(handlers.onProgress).not.toHaveBeenCalled()
    expect(handlers.onError).not.toHaveBeenCalled()
    expect(handlers.onDisconnect).not.toHaveBeenCalled()
  })

  it('test_close_inside_handler_stops_rest_of_same_chunk', async () => {
    /** Criterio 2: cerrar desde un manejador corta los eventos que venían en el mismo trozo. */
    mockServer.use(
      http.get(
        EVENTS,
        chunked(text(`event: progress\ndata: ${step('load_origin', 'running')}\n\nevent: progress\ndata: ${step('load_origin', 'done')}\n\n`)),
      ),
    )
    const onProgress = vi.fn()
    const onDisconnect = vi.fn()
    const close = subscribeEvents('c-1', {
      onProgress: (item) => {
        onProgress(item)
        close()
      },
      onDisconnect,
    })
    await vi.waitFor(() => expect(onProgress).toHaveBeenCalledTimes(1))
    await new Promise((resolve) => setTimeout(resolve, 40))
    expect(onProgress).toHaveBeenCalledTimes(1)
    expect(onDisconnect).not.toHaveBeenCalled()
  })

  it('test_close_is_idempotent', async () => {
    /** Criterio 2 (límite): cerrar dos veces no falla ni avisa. */
    mockServer.use(http.get(EVENTS, chunked(text(`event: progress\ndata: ${step('load_origin', 'done')}\n\n`))))
    const onDisconnect = vi.fn()
    const close = subscribeEvents('c-1', { onDisconnect })
    close()
    expect(() => close()).not.toThrow()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(onDisconnect).not.toHaveBeenCalled()
  })
})

describe('subscribeEvents: evento error y desconexión', () => {
  it('test_error_event_reaches_on_error_and_stream_ends', async () => {
    /** Criterio 2: el evento `error` con {"error": ErrorBody} (api/app.py) llega como ApiError; sin result, avisa «ended». */
    const failure = { code: 'citation_failed', message: 'La propuesta cita fuentes que no están en el contexto recibido.', retry_after: null }
    mockServer.use(
      http.get(
        EVENTS,
        chunked(text(`event: progress\ndata: ${step('generate', 'running')}\n\n`, `event: error\ndata: ${JSON.stringify({ error: failure })}\n\n`)),
      ),
    )
    const onError = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('c-1', { onError, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('ended'))
    expect(onError).toHaveBeenCalledWith(failure, undefined)
  })

  it('test_error_event_with_conversation_passes_error_and_conversation', async () => {
    /** Criterio 2: el evento `error` con la conversación en estado error trae su ErrorBody en `error`. */
    const failure = { code: 'provider_timeout', message: 'El modelo no respondió a tiempo.', retry_after: null }
    const conversation = { id: 'c-1', state: 'error', error: failure }
    mockServer.use(http.get(EVENTS, chunked(text(`event: error\ndata: ${JSON.stringify(conversation)}\n\n`))))
    const onError = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('c-1', { onError, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('ended'))
    expect(onError).toHaveBeenCalledWith(failure, conversation)
  })

  // Un corte a MITAD del flujo no se puede simular con MSW 3: si el ReadableStream del handler falla, MSW
  // cierra el cuerpo con normalidad (o falla el fetch entero). Queda cubierto el corte al abrir (events.test.ts).

  it('test_http_error_without_error_body_reports_failed_only', async () => {
    /** Criterio 2 (negativo): un error HTTP sin ErrorBody no llama a onError, solo avisa «failed». */
    mockServer.use(http.get(EVENTS, () => new HttpResponse('<html>', { status: 502 })))
    const onError = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('c-1', { onError, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('failed'))
    expect(onError).not.toHaveBeenCalled()
  })

  it('test_not_found_stream_reports_error_body_and_failed', async () => {
    /** Criterio 2: abrir el flujo de una conversación ajena da 404 not_found por onError y «failed». */
    const onError = vi.fn()
    const onDisconnect = vi.fn()
    mockServer.use(
      http.get(EVENTS, () =>
        HttpResponse.json({ error: { code: 'not_found', message: 'No existe esa conversación o no es tuya.', retry_after: null } }, { status: 404 }),
      ),
    )
    subscribeEvents('ajena', { onError, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('failed'))
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'not_found' }))
  })

  it('test_close_before_response_never_reports', async () => {
    /** Criterio 2: cerrar mientras se espera la respuesta no avisa de nada. */
    mockServer.use(
      http.get(EVENTS, async () => {
        await delay(30)
        return HttpResponse.json({ error: { code: 'unexpected', message: 'x' } }, { status: 500 })
      }),
    )
    const onError = vi.fn()
    const onDisconnect = vi.fn()
    const close = subscribeEvents('c-1', { onError, onDisconnect })
    close()
    await new Promise((resolve) => setTimeout(resolve, 80))
    expect(onDisconnect).not.toHaveBeenCalled()
  })

  it('test_request_asks_for_event_stream_and_encodes_id', async () => {
    /** Criterio 2: pide text/event-stream y codifica el id de la conversación en la ruta. */
    let seen: Request | undefined
    mockServer.use(
      http.get(EVENTS, ({ request }) => {
        seen = request
        return new HttpResponse('', { headers: { 'Content-Type': 'text/event-stream' } })
      }),
    )
    const onDisconnect = vi.fn()
    subscribeEvents('a/b c', { onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('ended'))
    expect(seen?.headers.get('Accept')).toBe('text/event-stream')
    expect(new URL(seen?.url ?? '').pathname).toBe('/api/v1/conversations/a%2Fb%20c/events')
  })
})
