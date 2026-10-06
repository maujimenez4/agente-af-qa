// QA encadenada (T-54) en Inicio: «Pendientes de pruebas» solo para QA, *Recoger* abre Generando y
// «otra persona la recogió» (409 handoff_unavailable). Datos sintéticos (DEMO, af-demo, qa-demo).
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../../api/client.ts'
import type { HandoffOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { QA_HANDOFF_ENABLED } from '../../app/features.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { handoffMeta } from './handoffText.ts'
import { QaHandoffs } from './QaHandoffs.tsx'

const HANDOFF: HandoffOut = {
  id: 'c3e5a7b92d4f4a6b8c0d1e2f3a4b5c6d',
  title: 'Renovar un préstamo',
  project: 'DEMO',
  story_key: 'DEMO-3',
  version: 2,
  from_user: 'af-demo',
  created_at: '2026-10-02T10:30:00Z',
}
const SIMULATED_ONLY: HandoffOut = { ...HANDOFF, id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', title: 'Reservar un libro', story_key: null, version: 1 }

function asQa() {
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
  // Montado sin App: el token CSRF lo daría el inicio de sesión.
  setCsrfToken('csrf-ficticio')
}

const pending = () => screen.getByRole('region', { name: 'Pendientes de pruebas' })

describe('handoffMeta', () => {
  it('«Versión 2 · de af-demo · 2 oct, …»', () => {
    expect(handoffMeta(HANDOFF)).toMatch(/^Versión 2 · de af-demo · 2 oct/)
  })

  it('sin fecha legible, sin fecha', () => {
    expect(handoffMeta({ ...HANDOFF, created_at: 'no-es-fecha' })).toBe('Versión 2 · de af-demo')
  })
})

describe('Pendientes de pruebas', () => {
  it('lista cada HU con su clave, título, proyecto, versión y quién la pasó', async () => {
    asQa()
    mockDb.handoffs = [HANDOFF]
    render(<QaHandoffs onTaken={vi.fn()} />)
    const item = await within(pending()).findByRole('listitem')
    expect(item).toHaveTextContent('DEMO-3')
    expect(item).toHaveTextContent('Renovar un préstamo')
    expect(item).toHaveTextContent(/DEMO · Versión 2 · de af-demo/)
    expect(within(item).getByRole('button', { name: 'Recoger DEMO-3' })).toBeEnabled()
  })

  it('una HU aprobada solo en simulación dice que no tiene clave y que no se podrán publicar los casos', async () => {
    asQa()
    mockDb.handoffs = [SIMULATED_ONLY]
    render(<QaHandoffs onTaken={vi.fn()} />)
    const item = await within(pending()).findByRole('listitem')
    expect(item).toHaveTextContent('Sin clave en Jira')
    expect(item).toHaveTextContent('Aprobada en simulación: podrás generar y revisar los casos, pero no publicarlos.')
    expect(within(item).getByRole('button', { name: 'Recoger Reservar un libro' })).toBeInTheDocument()
  })

  it('sin pendientes lo dice', async () => {
    asQa()
    mockDb.handoffs = []
    render(<QaHandoffs onTaken={vi.fn()} />)
    expect(await within(pending()).findByText('No hay HU pendientes de pruebas.')).toBeInTheDocument()
  })

  it('*Recoger* pide /take y entrega la conversación de QA generando', async () => {
    asQa()
    mockDb.handoffs = [HANDOFF]
    const onTaken = vi.fn()
    render(<QaHandoffs onTaken={onTaken} />)
    await userEvent.click(await within(pending()).findByRole('button', { name: 'Recoger DEMO-3' }))
    expect(onTaken).toHaveBeenCalledTimes(1)
    expect(onTaken.mock.calls[0]?.[0]).toMatchObject({ mode: 'qa', flow: 'tests', state: 'generating', title: 'Preparar pruebas de DEMO-3' })
    expect(mockDb.handoffs).toHaveLength(0)
  })

  it('dos clics seguidos en *Recoger* piden /take una sola vez', async () => {
    asQa()
    mockDb.handoffs = [HANDOFF]
    let takes = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (request.url.endsWith('/take')) takes += 1
    })
    const onTaken = vi.fn()
    render(<QaHandoffs onTaken={onTaken} />)
    const button = await within(pending()).findByRole('button', { name: 'Recoger DEMO-3' })
    fireEvent.click(button)
    fireEvent.click(button)
    await vi.waitFor(() => expect(onTaken).toHaveBeenCalledTimes(1))
    expect(takes).toBe(1)
    mockServer.events.removeAllListeners()
  })

  it('si otra persona la recogió (409 handoff_unavailable), lo dice y vuelve a leer la lista', async () => {
    asQa()
    mockDb.handoffs = [HANDOFF, SIMULATED_ONLY]
    mockDb.forceTaken = true
    const onTaken = vi.fn()
    render(<QaHandoffs onTaken={onTaken} />)
    await userEvent.click(await within(pending()).findByRole('button', { name: 'Recoger DEMO-3' }))
    expect(await within(pending()).findByRole('note')).toHaveTextContent('Otra persona ya recogió DEMO-3. La lista está actualizada.')
    await vi.waitFor(() => expect(within(pending()).getAllByRole('listitem')).toHaveLength(1))
    expect(within(pending()).queryByRole('button', { name: 'Recoger DEMO-3' })).toBeNull()
    expect(onTaken).not.toHaveBeenCalled()
  })

  it('un fallo al leer la lista muestra su tarjeta y *Reintentar* la vuelve a pedir', async () => {
    asQa()
    mockDb.handoffs = [HANDOFF]
    mockServer.use(
      http.get(
        '/api/v1/qa/handoffs',
        () => HttpResponse.json({ error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira (ficticio).', retry_after: null } }, { status: 503 }),
        { once: true },
      ),
    )
    render(<QaHandoffs onTaken={vi.fn()} />)
    const alert = await within(pending()).findByRole('alert')
    expect(alert).toHaveTextContent('No se pudo conectar con Jira (ficticio).')
    await userEvent.click(within(alert).getByRole('button'))
    expect(await within(pending()).findByRole('button', { name: 'Recoger DEMO-3' })).toBeInTheDocument()
  })
})

describe('Inicio · pendientes de pruebas por rol', () => {
  it('flujo unido fuera de la entrega (QA_HANDOFF_ENABLED = false): QA no ve la lista en Inicio ni la pide', async () => {
    expect(QA_HANDOFF_ENABLED).toBe(false)
    asQa()
    mockDb.handoffs = [HANDOFF]
    let asked = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/qa/handoffs') asked += 1
    })
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    expect(screen.queryByRole('region', { name: 'Pendientes de pruebas' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Recoger/ })).toBeNull()
    expect(asked).toBe(0)
    mockServer.events.removeAllListeners()
  })

  it('el analista no ve la lista ni la pide', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    let asked = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/qa/handoffs') asked += 1
    })
    render(<App />)
    await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    expect(screen.queryByRole('region', { name: 'Pendientes de pruebas' })).toBeNull()
    expect(asked).toBe(0)
    mockServer.events.removeAllListeners()
  })
})
