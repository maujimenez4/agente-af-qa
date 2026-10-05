// Bloque A (T-56): Retomar una conversación terminada en error · Reintentar (POST /retry, PA-276).
// DESIGN-DECISIONS.md §4 bis (Retomar). Datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import examples from '../api/examples.json'
import type { ConversationOut } from '../api/types.ts'
import { App } from '../App.tsx'
import { mockDb, mockServer } from '../mocks/node.ts'
import { openEventStream } from '../test/sse.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const FAILED: ConversationOut = {
  ...EXAMPLE,
  state: 'error',
  review: null,
  error: { code: 'cancelled', message: 'Generación detenida (ficticio).', retry_after: null },
}
const GENERATING: ConversationOut = { ...EXAMPLE, state: 'generating', review: null, error: null }

// Generando sigue en pantalla hasta que la prueba termina: el flujo SSE no se cierra solo.
const heartbeat = openEventStream

async function resume(conversation: ConversationOut) {
  mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(conversation)))
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
}

describe('Retomar en error · Reintentar (bloque A)', () => {
  it('mientras /retry responde, «Reintentar» queda desactivado y un doble clic no lo pide dos veces', async () => {
    /** §4 bis Retomar: *Reintentar* (`POST /retry`, abre Generando), una sola vez. */
    let retries = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => heartbeat()),
      http.post('/api/v1/conversations/:id/retry', async () => {
        retries += 1
        await delay(150)
        return HttpResponse.json(GENERATING, { status: 202 })
      }),
    )
    await resume(FAILED)
    const button = await screen.findByRole('button', { name: 'Reintentar' })
    await userEvent.dblClick(button)
    expect(button).toBeDisabled()
    expect(await screen.findByText('Generando la propuesta…')).toBeInTheDocument()
    expect(retries).toBe(1)
  })

  it('con el teclado: Intro en «Reintentar» abre Generando', async () => {
    let retries = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => heartbeat()),
      http.post('/api/v1/conversations/:id/retry', () => {
        retries += 1
        return HttpResponse.json(GENERATING, { status: 202 })
      }),
    )
    await resume(FAILED)
    ;(await screen.findByRole('button', { name: 'Reintentar' })).focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByText('Generando la propuesta…')).toBeInTheDocument()
    expect(retries).toBe(1)
  })

  it('«Reintentar» es la acción principal y la tarjeta de error no lleva acción propia', async () => {
    /** §4 bis Retomar: el error se muestra «tal cual …, sin acción en la tarjeta, con *Reintentar*». */
    await resume(FAILED)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Generación detenida (ficticio).')
    expect(within(alert).queryByRole('button')).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Empezar una conversación nueva' })).toBeInTheDocument()
  })

  it('si /retry responde handoff_unavailable (QA encadenada), solo queda empezar otra', async () => {
    /** README «Novedades» PA-276: en QA encadenada, 409 handoff_unavailable si la HU volvió a la lista. */
    mockServer.use(
      http.post('/api/v1/conversations/:id/retry', () =>
        HttpResponse.json({ error: { code: 'handoff_unavailable', message: 'La HU volvió a la lista (ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    await resume({ ...FAILED, flow: 'tests', mode: 'qa' })
    await userEvent.click(await screen.findByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByText('La HU volvió a la lista (ficticio).')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Empezar una conversación nueva' })).toBeInTheDocument()
  })
})
