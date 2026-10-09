// PA-333: tras «Aprobar y publicar», la pantalla se quedó en «Aprobando y publicando…» sin abrir el SSE ni
// consultar el estado, aunque la conversación ya estaba `simulated`. Reproducción determinista: el flujo
// de eventos no llega a abrirse nunca (petición encolada en el navegador) y GET /conversations/{id} ya da
// el estado final; el plazo de 5 s del vigilante vence cuando lo decide la prueba. Datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { until, watchdogClock } from '../../test/watchdog.ts'
import { OPEN_TIMEOUT_MS } from '../Generating/useGeneration.ts'

// `/events` no sale del navegador: ni cabeceras, ni eventos, ni corte.
const stream = vi.hoisted(() => ({ subscriptions: 0 }))
vi.mock('../../api/events.ts', () => ({
  subscribeEvents: () => {
    stream.subscriptions += 1
    return () => undefined
  },
}))

const SIMULATED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as ConversationOut

async function toReceipt() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
  const operations = await screen.findByRole('group', { name: /Qué se hará en Jira/ })
  for (const box of within(operations).getAllByRole('checkbox')) await userEvent.click(box)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Recibo · publicación con el SSE encolado (PA-333)', () => {
  it('sin cabeceras de /events, a los 5 s consulta el estado y abre el resultado simulado', async () => {
    await toReceipt()
    let gets = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id', ({ params }) => {
        gets += 1
        return HttpResponse.json({ ...SIMULATED, id: String(params.id) })
      }),
    )
    const clock = watchdogClock()
    await userEvent.click(screen.getByRole('button', { name: 'Aprobar y publicar' }))
    expect(await screen.findByText('Aprobando y publicando…')).toBeInTheDocument()
    expect(stream.subscriptions).toBeGreaterThan(0)
    expect(clock.armed()).toEqual([OPEN_TIMEOUT_MS])
    expect(gets).toBe(0) // antes de vencer, espera al flujo (lo que pasaba siempre: sin salida)

    clock.fire(OPEN_TIMEOUT_MS)
    expect(await screen.findByText(/Modo de prueba activo: FAQ no escribe en Jira/)).toBeInTheDocument()
    expect(screen.queryByText('Aprobando y publicando…')).toBeNull()
    expect(gets).toBe(1)
    await until(() => expect(clock.armed()).toEqual([]))
  })
})
