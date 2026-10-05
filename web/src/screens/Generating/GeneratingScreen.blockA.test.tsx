// Bloque A (T-56): Generando · Detener con el teclado y Reintentar rechazado (not_in_error → Actualizar).
// DESIGN-DECISIONS.md §4 bis (Generando: Error y Detener) y §6. Datos sintéticos.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { mockServer } from '../../mocks/node.ts'
import { GeneratingScreen } from './GeneratingScreen.tsx'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const GENERATING: ConversationOut = { ...EXAMPLE, id: 'c-ficticia', state: 'generating', review: null, error: null, cancel_requested: false }
const CANCELLED: ConversationOut = {
  ...GENERATING,
  state: 'error',
  error: { code: 'cancelled', message: 'Generación detenida (ficticio).', retry_after: null },
}

/** Flujo SSE que no termina: la generación sigue en curso. */
const openStream = () =>
  new HttpResponse(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(': latido\n\n'))
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )

const errorStream = (conversation: ConversationOut) =>
  new HttpResponse(`event: error\ndata: ${JSON.stringify(conversation)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })

function renderScreen() {
  const onReady = vi.fn()
  const onRetry = vi.fn()
  render(<GeneratingScreen conversation={GENERATING} onReady={onReady} onRetry={onRetry} />)
  return { onReady, onRetry }
}

describe('Generando · Detener con el teclado (bloque A)', () => {
  it('con Tab se llega a «Detener la generación» e Intro pide /cancel', async () => {
    /** §4 bis: *Detener* (PA-314), accesible con el teclado. */
    let cancels = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => openStream()),
      http.post('/api/v1/conversations/:id/cancel', () => {
        cancels += 1
        return HttpResponse.json({ ...GENERATING, cancel_requested: true }, { status: 202 })
      }),
    )
    renderScreen()
    const button = screen.getByRole('button', { name: 'Detener la generación' })
    for (let presses = 0; presses < 15 && document.activeElement !== button; presses += 1) await userEvent.tab()
    expect(button).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByRole('button', { name: 'Deteniendo la generación…' })).toBeDisabled()
    expect(cancels).toBe(1)
  })

  it('con Espacio también detiene, una sola vez', async () => {
    let cancels = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => openStream()),
      http.post('/api/v1/conversations/:id/cancel', () => {
        cancels += 1
        return HttpResponse.json({ ...GENERATING, cancel_requested: true }, { status: 202 })
      }),
    )
    renderScreen()
    screen.getByRole('button', { name: 'Detener la generación' }).focus()
    await userEvent.keyboard(' ')
    await screen.findByRole('button', { name: 'Deteniendo la generación…' })
    await userEvent.keyboard(' ')
    expect(cancels).toBe(1)
  })
})

describe('Generando · /retry rechazado con not_in_error (bloque A)', () => {
  function rejectRetry(read: ConversationOut) {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => errorStream(CANCELLED), { once: true }),
      http.get('/api/v1/conversations/:id/events', () => openStream()),
      http.post('/api/v1/conversations/:id/retry', () =>
        HttpResponse.json({ error: { code: 'not_in_error', message: 'No hay nada que reintentar (ficticio).', retry_after: null } }, { status: 409 }),
      ),
      http.get('/api/v1/conversations/:id', () => HttpResponse.json(read)),
    )
  }

  async function retryAndRefresh() {
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No hay nada que reintentar' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('No hay nada que reintentar (ficticio).')
    await userEvent.click(within(alert).getByRole('button', { name: 'Actualizar' }))
  }

  it('«Actualizar» con la conversación ya en revisión abre la propuesta', async () => {
    /** §4 bis: «Un /retry rechazado (not_in_error) muestra su tarjeta con *Actualizar*, que lee el estado y sigue desde ahí». */
    rejectRetry({ ...EXAMPLE, id: GENERATING.id })
    const { onReady, onRetry } = renderScreen()
    await retryAndRefresh()
    await waitFor(() => expect(onReady).toHaveBeenCalledWith(expect.objectContaining({ state: 'in_review' })))
    expect(onRetry).not.toHaveBeenCalled()
  })

  it('«Actualizar» con la conversación generando vuelve a seguir la generación', async () => {
    rejectRetry({ ...GENERATING, cancel_requested: false })
    const { onReady, onRetry } = renderScreen()
    await retryAndRefresh()
    expect(await screen.findByText('Generando la propuesta…')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(onReady).not.toHaveBeenCalled()
    expect(onRetry).not.toHaveBeenCalled()
  })

  it('«Actualizar» con la conversación terminada de otra forma vuelve a Origen (onRetry)', async () => {
    rejectRetry({ ...GENERATING, state: 'discarded' })
    const { onReady, onRetry } = renderScreen()
    await retryAndRefresh()
    await waitFor(() => expect(onRetry).toHaveBeenCalledTimes(1))
    expect(onReady).not.toHaveBeenCalled()
  })

  it('la tarjeta de un fallo al detener no lleva acción', async () => {
    /** §4 bis: otro error al detener «sí» se muestra «y la generación sigue»; la tarjeta solo informa. */
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => openStream()),
      http.post('/api/v1/conversations/:id/cancel', () =>
        HttpResponse.json({ error: { code: 'rate_limited', message: 'Límite ficticio.', retry_after: 5 } }, { status: 429 }),
      ),
    )
    renderScreen()
    await userEvent.click(screen.getByRole('button', { name: 'Detener la generación' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Límite ficticio.')
    expect(within(alert).queryByRole('button', { name: 'Reintentar' })).toBeNull()
    expect(screen.getByText('Generando la propuesta…')).toBeInTheDocument()
  })
})
