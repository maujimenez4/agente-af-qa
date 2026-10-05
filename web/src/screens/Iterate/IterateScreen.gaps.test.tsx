// T-56: huecos de IterateScreen.test.tsx sobre UI.md §4.5 (Mixta 3 · Iterar), §7 y
// DESIGN-DECISIONS.md §4 bis (Iterar, plegar el panel) y §6. Datos sintéticos (DEMO-3, af-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const EXAMPLE_ID = '8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d'

async function openFromList(name: RegExp = /Evolucionar DEMO-3/) {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

const panel = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const composer = () => screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta' })
const sse = (text: string) => new HttpResponse(text, { headers: { 'Content-Type': 'text/event-stream' } })

async function askChange(text: string) {
  await userEvent.type(composer(), text)
  await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Iterar: huecos (UI.md §4.5, DESIGN-DECISIONS.md §4 bis)', () => {
  it('la versión retomada marca «Nueva» el CA añadido en ella y no marca el que no cambió', async () => {
    await openFromList()
    const added = within(panel()).getByText('Renovación rechazada por reservas').closest('li') as HTMLElement
    expect(within(added).getByText('Nueva')).toBeInTheDocument()
    const same = within(panel()).getByText('Renovación permitida').closest('li') as HTMLElement
    expect(within(same).queryByText(/Cambiado en v|Nueva/)).toBeNull()
  })

  it('el selector empieza por «Jira» (PA-316) y el aviso «CA sin fuente» no se pinta, porque el contrato no da la cita de cada CA (PA-315)', async () => {
    await openFromList()
    const versions = within(panel()).getByRole('group', { name: 'Versiones' })
    expect(within(versions).getAllByRole('button').map((button) => button.textContent)).toEqual(['Jira', 'v2'])
    expect(screen.queryByText(/Sin respaldo en las fuentes/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pedir fuente' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Confirmar' })).toBeNull()
  })

  it('el subtítulo del panel dice «en revisión» y pasa a «generando» mientras se itera', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')))
    await openFromList()
    expect(within(panel()).getByText('Evolucionar DEMO-3 · en revisión')).toBeInTheDocument()
    await askChange('Aclara el alcance')
    expect(await within(panel()).findByText('Evolucionar DEMO-3 · generando')).toBeInTheDocument()
  })

  it('una HU nueva en una épica se titula «HU nueva en la épica DEMO-1» en la cabecera y en el panel (PA-317)', async () => {
    const summary = mockDb.conversations.find((item) => item.thread_id === EXAMPLE_ID)
    if (summary) Object.assign(summary, { title: 'Nueva HU en DEMO-1', origin_kind: 'epic', origin_key: 'DEMO-1' })
    await openFromList(/HU nueva en la épica DEMO-1/)
    expect(screen.getByRole('heading', { level: 1, name: 'HU nueva en la épica DEMO-1' })).toBeInTheDocument()
    expect(within(panel()).getByText('HU nueva en la épica DEMO-1 · en revisión')).toBeInTheDocument()
    expect(screen.queryByText(/Nueva HU en DEMO-1/)).toBeNull()
  })

  it('plegar el panel en Iterar conserva la pestaña abierta al volver a mostrarlo', async () => {
    await openFromList()
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Impacto (1)' }))
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel' }))
    expect(within(panel()).getByRole('tab', { name: 'Impacto (1)' })).toHaveAttribute('aria-selected', 'true')
    expect(within(panel()).getByRole('tabpanel')).toHaveTextContent('DEMO-2')
  })

  it('un error en el SSE de la iteración muestra su tarjeta y vuelve a dejar pedir cambios', async () => {
    const failure = { error: { code: 'citation_failed', message: 'La propuesta cita fuentes que no están en el contexto recibido.' } }
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(`event: error\ndata: ${JSON.stringify(failure)}\n\n`)))
    await openFromList()
    await askChange('Cambio ficticio')
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'La propuesta no es válida' })).toBeInTheDocument()
    expect(composer()).toBeEnabled()
    expect(within(panel()).getByRole('button', { name: 'Descartar' })).toBeEnabled()
    expect(within(panel()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
  })

  it.each(['restart', 'approval_rejected'] as const)('el code %s lleva «Empezar de nuevo», que vuelve a Inicio (§6)', async (code) => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/iterate', () =>
        HttpResponse.json({ error: { code, message: 'Esta conversación no puede continuar. Empieza una nueva; nada se ha escrito en Jira.' } }, { status: 409 }),
      ),
    )
    await openFromList()
    await askChange('Cambio ficticio')
    const alert = await screen.findByRole('alert')
    await userEvent.click(within(alert).getByRole('button', { name: 'Empezar de nuevo' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('«Descartar» no llama a /discard hasta confirmar', async () => {
    let discards = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/discard')) discards += 1
    })
    await openFromList()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Descartar' }))
    expect(within(panel()).getByRole('group', { name: 'Confirmar el descarte' })).toHaveTextContent(
      '¿Descartar la propuesta? No se publicará nada en Jira y la conversación terminará.',
    )
    expect(discards).toBe(0)
    await userEvent.click(within(panel()).getByRole('button', { name: 'Sí, descartar' }))
    await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })
    expect(discards).toBe(1)
  })

  it('si /discard falla, muestra la tarjeta del error, cierra la confirmación y sigue en Iterar', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/discard', () =>
        HttpResponse.json(
          { error: { code: 'not_in_review', message: 'La conversación no tiene una propuesta en revisión (está generando o ya terminó).' } },
          { status: 409 },
        ),
      ),
    )
    await openFromList()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Descartar' }))
    await userEvent.click(within(panel()).getByRole('button', { name: 'Sí, descartar' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'La revisión ya no está abierta' })).toBeInTheDocument()
    expect(within(alert).getByRole('button', { name: 'Actualizar' })).toBeInTheDocument()
    expect(within(panel()).queryByRole('group', { name: 'Confirmar el descarte' })).toBeNull()
    expect(screen.queryByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeNull()
  })

  it('«Editar a mano» y «Revisar y aprobar» se pueden enfocar con el teclado aunque no hagan nada', async () => {
    await openFromList()
    for (const name of ['Editar a mano', 'Revisar y aprobar']) {
      const button = within(panel()).getByRole('button', { name })
      expect(button).not.toBeDisabled()
      button.focus()
      expect(button).toHaveFocus()
      await userEvent.keyboard('{Enter}')
      expect(within(panel()).queryByRole('group', { name: 'Confirmar el descarte' })).toBeNull()
    }
  })
})
