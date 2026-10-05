// Recibo: fallo de la publicación ya en marcha (H-2) y aprobar no se cancela (H-4), de spec-checker en el bloque B.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const PUBLISH_FAILED = { code: 'publish_failed' as const, message: 'Jira rechazó la publicación (mensaje ficticio).', retry_after: null }

async function approveFromReceipt() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
  const operations = await screen.findByRole('group', { name: /Qué se hará en Jira/ })
  for (const box of within(operations).getAllByRole('checkbox')) await userEvent.click(box)
  await userEvent.click(screen.getByRole('button', { name: 'Aprobar y publicar' }))
}

/** Como la API: la publicación falla, la conversación queda en error y el SSE la trae completa. */
function failPublishing() {
  mockServer.use(
    http.get(
      '/api/v1/conversations/:id/events',
      ({ params }) => {
        const run = mockDb.runs.get(String(params.id))
        if (run) {
          run.approving = undefined
          run.conversation = { ...run.conversation, state: 'error', error: PUBLISH_FAILED }
        }
        return new HttpResponse(`event: error\ndata: ${JSON.stringify(run?.conversation)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
      },
      { once: true },
    ),
  )
}

afterEach(() => mockServer.events.removeAllListeners())

describe('Recibo · fallo de la publicación (H-2)', () => {
  it('con la conversación en error sale del recibo a su vista de error, que reintenta con /retry y no vuelve a aprobar', async () => {
    const calls: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') calls.push(new URL(request.url).pathname.split('/').at(-1) ?? '')
    })
    failPublishing()
    await approveFromReceipt()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(PUBLISH_FAILED.message)
    expect(screen.queryByRole('button', { name: 'Aprobar y publicar' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled()
    expect(calls).toEqual(['approve'])
  })

  it('si el fallo no deja la conversación en error, muestra la tarjeta y *Aprobar* queda desactivado', async () => {
    mockServer.use(
      http.get(
        '/api/v1/conversations/:id/events',
        () => new HttpResponse(`event: error\ndata: ${JSON.stringify({ error: PUBLISH_FAILED })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }),
        { once: true },
      ),
    )
    await approveFromReceipt()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No se puede publicar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Aprobar y publicar' })).toBeDisabled()
    expect(within(alert).getByRole('button', { name: 'Volver al recibo' })).toBeInTheDocument()
  })
})

describe('Recibo · aprobar no se cancela (H-4)', () => {
  it('mientras se aprueba y publica no hay *Detener*', async () => {
    mockDb.stepDelayMs = 400
    await approveFromReceipt()
    expect(await screen.findByText('Aprobando y publicando…')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Detener/ })).toBeNull()
    await screen.findByText(/Publicación simulada/, undefined, { timeout: 4000 })
  })

  it('la API simulada responde 409 not_cancellable a /cancel mientras aprueba', async () => {
    mockDb.stepDelayMs = 400
    await approveFromReceipt()
    await screen.findByText('Aprobando y publicando…')
    const id = [...mockDb.runs.keys()].at(-1) ?? ''
    const response = await fetch(new URL(`/api/v1/conversations/${id}/cancel`, window.location.origin), {
      method: 'POST',
      headers: { 'X-CSRF-Token': 'csrf-ficticio' },
    })
    expect(response.status).toBe(409)
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe('not_cancellable')
  })
})
