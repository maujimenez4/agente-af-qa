// Correcciones de la revisión de spec-checker sobre Iterar (H-1, H-4, H-5, H-9 y H-11).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut

async function openFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

const panel = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const log = () => screen.getByRole('log', { name: 'Conversación' })
const composer = () => screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' })

async function askFor(change: string, version: number) {
  await userEvent.type(composer(), change)
  await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  await within(panel()).findByRole('button', { name: `Versión ${version}` })
}

afterEach(() => mockServer.events.removeAllListeners())

describe('Iterar · historial de la conversación (H-1)', () => {
  it('los cambios pedidos antes de retomar siguen en el chat tras pedir otro, sin duplicarse', async () => {
    await openFromList()
    const earlier = EXAMPLE.feedback[0] as string
    expect(within(log()).getByText(earlier)).toBeInTheDocument()
    await askFor('Cambio ficticio uno', 3)
    await askFor('Cambio ficticio dos', 4)
    expect(within(log()).getAllByText(earlier)).toHaveLength(1)
    expect(within(log()).getAllByText('Cambio ficticio uno')).toHaveLength(1)
    expect(within(log()).getAllByText('Cambio ficticio dos')).toHaveLength(1)
  })
})

describe('Iterar · marcas por versión con diffs acumulados frente a Jira (H-4)', () => {
  it('la API simulada acumula los diffs: el CA cambiado en Jira sigue en Cambios en la versión siguiente', async () => {
    await openFromList()
    const before = EXAMPLE.review?.impact?.diffs.length ?? 0
    await askFor('Cambio ficticio', 3)
    expect(within(panel()).getByRole('tab', { name: `Cambios (${before + 1})` })).toBeInTheDocument()
    const run = [...mockDb.runs.values()].at(-1)
    const fields = run?.conversation.review?.impact?.diffs.map((diff) => diff.field) ?? []
    expect(new Set(fields).size).toBe(fields.length)
  })

  it('en v3 solo se marca «Cambiado en v3» lo que cambió frente a v2, no lo que ya difería de Jira', async () => {
    await openFromList()
    await askFor('Cambio ficticio', 3)
    const changed = within(panel()).getByText('Renovación permitida (revisado en v3)').closest('li') as HTMLElement
    expect(within(changed).getByText('Cambiado en v3')).toBeInTheDocument()
    // CA-02 difería de Jira desde la v2 y no cambia en la v3.
    const criteria = within(panel()).getByRole('list', { name: 'Criterios de aceptación' })
    const ca02 = within(criteria).getByText('CA-02').closest('li') as HTMLElement
    expect(within(ca02).queryByText(/Cambiado en v3|Nueva/)).toBeNull()
  })
})

describe('Iterar · acciones de la tarjeta de error (H-5)', () => {
  it('«Actualizar» (not_in_review) vuelve a leer la conversación y quita la tarjeta', async () => {
    await openFromList()
    let reads = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'GET' && /\/conversations\/[^/]+$/.test(new URL(request.url).pathname)) reads += 1
    })
    mockServer.use(
      http.post('/api/v1/conversations/:id/iterate', () =>
        HttpResponse.json({ error: { code: 'not_in_review', message: 'La conversación no tiene una propuesta en revisión.', retry_after: null } }, { status: 409 }),
      ),
    )
    await userEvent.type(composer(), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('La conversación no tiene una propuesta en revisión.')
    await userEvent.click(within(alert).getByRole('button', { name: 'Actualizar' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(reads).toBeGreaterThan(0)
    expect(panel()).toBeInTheDocument()
  })

  it('«Actualizar» lleva a Inicio si la conversación ya no está en revisión', async () => {
    await openFromList()
    mockServer.use(
      http.post('/api/v1/conversations/:id/iterate', () =>
        HttpResponse.json({ error: { code: 'not_in_review', message: 'Ya terminó.', retry_after: null } }, { status: 409 }),
      ),
      http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, state: 'discarded', review: null })),
    )
    await userEvent.type(composer(), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Actualizar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('«Volver a generar» reenvía el último cambio pedido sin repetirlo en el chat', async () => {
    await openFromList()
    const sent: string[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/iterate')) sent.push(((await request.clone().json()) as { feedback: string }).feedback)
    })
    mockServer.use(
      http.post(
        '/api/v1/conversations/:id/iterate',
        () => HttpResponse.json({ error: { code: 'provider_timeout', message: 'El modelo no respondió a tiempo.', retry_after: null } }, { status: 504 }),
        { once: true },
      ),
    )
    await userEvent.type(composer(), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Volver a generar' }))
    expect(await within(panel()).findByRole('button', { name: 'Versión 3' })).toBeInTheDocument()
    expect(sent).toEqual(['Cambio ficticio', 'Cambio ficticio'])
    expect(within(log()).getAllByText('Cambio ficticio')).toHaveLength(1)
  })
})

describe('Iterar · Reintentar repite la operación que falló (R-1) e Iniciar sesión (R-2)', () => {
  it('tras un cambio que salió bien, si falla Descartar, «Reintentar» vuelve a descartar y no itera', async () => {
    await openFromList()
    await askFor('Cambio ficticio', 3)
    const calls: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      const path = new URL(request.url).pathname
      if (request.method === 'POST') calls.push(path.split('/').at(-1) ?? path)
    })
    mockServer.use(
      http.post(
        '/api/v1/conversations/:id/discard',
        () => HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 }),
        { once: true },
      ),
    )
    await userEvent.click(within(panel()).getByRole('button', { name: 'Descartar' }))
    await userEvent.click(within(panel()).getByRole('button', { name: 'Sí, descartar' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
    expect(calls).toEqual(['discard', 'discard'])
  })

  it('si falla la relectura de «Actualizar», «Reintentar» vuelve a leer y no itera', async () => {
    await openFromList()
    const calls: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      const path = new URL(request.url).pathname
      if (path.endsWith('/iterate')) calls.push('iterate')
      else if (request.method === 'GET' && /\/conversations\/[^/]+$/.test(path)) calls.push('read')
    })
    mockServer.use(
      http.post('/api/v1/conversations/:id/iterate', () =>
        HttpResponse.json({ error: { code: 'not_in_review', message: 'No está en revisión (ficticio).', retry_after: null } }, { status: 409 }),
      ),
      http.get(
        '/api/v1/conversations/:id',
        () => HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 }),
        { once: true },
      ),
    )
    await userEvent.type(composer(), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Actualizar' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(calls).toEqual(['iterate', 'read', 'read'])
  })

  it('tras un `event: error` del SSE de la iteración, «Volver a generar» repite con /retry y sale la versión siguiente', async () => {
    await openFromList()
    const calls: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') calls.push(new URL(request.url).pathname.split('/').at(-1) ?? '')
    })
    const error = { code: 'citation_failed' as const, message: 'Citas no válidas (ficticio).', retry_after: null }
    mockServer.use(
      http.get(
        '/api/v1/conversations/:id/events',
        ({ params }) => {
          // Como la API real: la conversación queda en error y el evento la trae completa.
          const run = mockDb.runs.get(String(params.id))
          if (run) run.conversation = { ...run.conversation, state: 'error', error }
          return new HttpResponse(`event: error\ndata: ${JSON.stringify(run?.conversation)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
        },
        { once: true },
      ),
    )
    await userEvent.type(composer(), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Volver a generar' }))
    expect(await within(panel()).findByRole('button', { name: 'Versión 3' })).toBeInTheDocument()
    expect(calls).toEqual(['iterate', 'retry'])
    expect(within(log()).getAllByText('Cambio ficticio')).toHaveLength(1)
  })

  it('«Iniciar sesión» (unauthenticated) cierra la sesión y lleva al inicio de sesión', async () => {
    await openFromList()
    mockServer.use(
      http.post('/api/v1/conversations/:id/iterate', () =>
        HttpResponse.json({ error: { code: 'unauthenticated', message: 'La sesión ha caducado.', retry_after: null } }, { status: 401 }),
      ),
    )
    await userEvent.type(composer(), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Iniciar sesión' }))
    expect(await screen.findByLabelText(/usuario/i)).toBeInTheDocument()
  })
})

describe('Iterar · HU nueva sin HU de Jira (H-9)', () => {
  it('no habla de cambios «frente a Jira» cuando el flujo no es evolucionar', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, flow: 'need' })))
    await openFromList()
    expect(within(log()).queryByText(/frente a Jira/)).toBeNull()
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Cambios' }))
    expect(within(panel()).getByRole('tabpanel')).toHaveTextContent('Es una HU nueva: no hay una versión en Jira con la que compararla.')
  })
})

describe('Iterar · abrir en el panel con el panel plegado (H-11)', () => {
  it('«Abrir en el panel» vuelve a mostrar el panel plegado', async () => {
    await openFromList()
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
    const open = within(log()).getByRole('button', { name: /Propuesta de HU, versión 2/ })
    expect(open).toHaveTextContent('Abrir en el panel')
    expect(open).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(open)
    expect(panel()).toBeInTheDocument()
    expect(open).toHaveTextContent('Abierta en el panel')
    expect(screen.getByRole('button', { name: 'Ocultar el panel' })).toBeInTheDocument()
  })
})
