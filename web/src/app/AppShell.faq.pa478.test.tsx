// El asistente se llama FAQ (PA-478, docs/diseno/faq/README.md): inicio de sesión dividido, título de la pestaña, la Q del
// carril como ida a Inicio (con la pregunta del editor y sin cancelar una generación) y los textos con el nombre.
// Con la App y la API simulada (MSW). Datos sintéticos (DEMO-3, af-demo y la contraseña ficticia «demo»).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import examples from '../api/examples.json'
import type { ConversationOut } from '../api/types.ts'
import { App } from '../App.tsx'
import { mockDb, mockServer } from '../mocks/node.ts'
import { openEventStream } from '../test/sse.ts'
import indexHtml from '../../index.html?raw'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut

const HOME_HEADING = { level: 1, name: '¿En qué trabajamos hoy?' } as const
const railHome = () => within(screen.getByRole('navigation', { name: 'Zonas' })).getByRole('button', { name: 'FAQ · Inicio' })
const list = () => screen.getByRole('complementary', { name: 'Conversaciones' })
const proposal = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const editor = () => screen.getByRole('complementary', { name: 'Editar a mano' })
const confirmGroup = () => screen.queryByRole('group', { name: 'Descartar los cambios' })

async function signedIn() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  return screen.findByRole('heading', HOME_HEADING)
}

async function openDemo3() {
  await signedIn()
  await userEvent.click(await within(list()).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

async function editWithChanges() {
  await openDemo3()
  await userEvent.click(within(proposal()).getByRole('button', { name: 'Editar a mano' }))
  const title = within(editor()).getByLabelText('Título')
  await userEvent.clear(title)
  await userEvent.type(title, 'Renovar un préstamo ficticio')
}

/** Peticiones a la API simulada en orden («POST /api/v1/conversations/…/cancel»). */
function recordRequests(): string[] {
  const seen: string[] = []
  mockServer.events.on('request:start', ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`)
  })
  return seen
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Inicio de sesión de FAQ (PA-478 §1)', () => {
  it('muestra el logotipo «FAQ», el mensaje, «un asistente de Qaracter», el logo de Qaracter y el formulario', async () => {
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Hola de nuevo' })).toBeInTheDocument()
    const logo = screen.getByRole('img', { name: 'FAQ' })
    // Una sola imagen «FAQ»: «FA» y la Q son decorativas.
    expect(logo).toHaveTextContent('FA')
    for (const part of logo.children) expect(part).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByText(/^Historias de usuario y pruebas en segundos\./)).toHaveTextContent(
      'Historias de usuario y pruebas en segundos. Siempre con tu aprobación.',
    )
    expect(screen.getByText('Siempre con tu aprobación.')).toBeInTheDocument()
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === 'un asistente de Qaracter')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Qaracter' })).toBeInTheDocument()
    expect(screen.getByText('Inicia sesión para continuar en FAQ.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Entrar en FAQ' })).toBeEnabled()
  })

  it('funciona como antes: con el foco en el usuario, entrar con un usuario demo abre la app', async () => {
    render(<App />)
    const username = await screen.findByLabelText('Usuario')
    expect(username).toHaveFocus()
    await userEvent.type(username, 'af-demo')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'demo')
    await userEvent.click(screen.getByRole('button', { name: 'Entrar en FAQ' }))
    expect(await screen.findByRole('heading', HOME_HEADING)).toBeInTheDocument()
    expect(railHome()).toBeInTheDocument()
  })
})

describe('Título de la pestaña (PA-478 §2)', () => {
  it('es «FAQ · Qaracter», en index.html y al montar la App', async () => {
    expect(indexHtml).toContain('<title>FAQ · Qaracter</title>')
    document.title = 'Otro título'
    render(<App />)
    await screen.findByRole('heading', { level: 1, name: 'Hola de nuevo' })
    expect(document.title).toBe('FAQ · Qaracter')
  })
})

describe('La Q del carril (PA-478 §2, decisión c)', () => {
  it('es solo la Q, sin texto debajo, con nombre y title «FAQ · Inicio»', async () => {
    await signedIn()
    const home = railHome()
    expect(home).toHaveTextContent(/^$/)
    expect(home).toHaveAttribute('title', 'FAQ · Inicio')
    expect(home.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('con el teclado lleva a Inicio desde una conversación', async () => {
    await openDemo3()
    railHome().focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByRole('heading', HOME_HEADING)).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
  })

  it('con el editor con cambios pregunta antes de salir, igual que hoy; al confirmar va a Inicio', async () => {
    await editWithChanges()
    await userEvent.click(railHome())
    expect(confirmGroup()).toBeInTheDocument()
    expect(screen.queryByRole('heading', HOME_HEADING)).toBeNull()
    // «Seguir editando» conserva lo escrito.
    await userEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(within(editor()).getByLabelText('Título')).toHaveValue('Renovar un préstamo ficticio')
    await userEvent.click(railHome())
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('heading', HOME_HEADING)).toBeInTheDocument()
  })

  it('«Nueva conversación» hace la misma pregunta con el editor con cambios', async () => {
    await editWithChanges()
    await userEvent.click(within(list()).getByRole('button', { name: 'Nueva conversación' }))
    expect(confirmGroup()).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('heading', HOME_HEADING)).toBeInTheDocument()
  })

  it('sin cambios en el editor va a Inicio sin preguntar', async () => {
    await openDemo3()
    await userEvent.click(within(proposal()).getByRole('button', { name: 'Editar a mano' }))
    await userEvent.click(railHome())
    expect(await screen.findByRole('heading', HOME_HEADING)).toBeInTheDocument()
    expect(confirmGroup()).toBeNull()
  })

  it('una generación en curso no se cancela: va a Inicio y la conversación sigue en la lista', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, state: 'generating', review: null })),
      http.get('/api/v1/conversations/:id/events', openEventStream),
    )
    await signedIn()
    await userEvent.click(await within(list()).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    expect(await screen.findByText('FAQ está escribiendo la propuesta…')).toBeInTheDocument()
    const requests = recordRequests()
    await userEvent.click(railHome())
    expect(await screen.findByRole('heading', HOME_HEADING)).toBeInTheDocument()
    expect(requests.filter((request) => request.endsWith('/cancel'))).toEqual([])
    expect(within(list()).getByRole('button', { name: /Evolucionar DEMO-3/ })).toBeInTheDocument()
  })

  it('desde Memoria vuelve a la zona de trabajo, a Inicio', async () => {
    await openDemo3()
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Zonas' })).getByRole('button', { name: 'Memoria' }))
    await waitFor(() => expect(screen.queryByRole('heading', HOME_HEADING)).toBeNull())
    await userEvent.click(railHome())
    expect(await screen.findByRole('heading', HOME_HEADING)).toBeVisible()
  })
})

describe('El nombre en Inicio, la lista y la conversación (PA-478 §2)', () => {
  it('Inicio saluda como FAQ, con el rótulo del cuadro de texto y el pie', async () => {
    await signedIn()
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === 'Hola, soy FAQ, tu asistente de análisis funcional y QA.')).toBeInTheDocument()
    expect(screen.getByText('O escríbele a FAQ directamente')).toBeInTheDocument()
    expect(screen.getByText('FAQ propone; tú decides. Nada se publica en Jira sin tu aprobación.')).toBeInTheDocument()
    expect(screen.getByText('Cuéntale a FAQ lo que hace falta; si ya existe una HU parecida, te la propone.')).toBeInTheDocument()
    expect(within(list()).getByRole('heading', { name: 'Tus conversaciones con FAQ' })).toBeInTheDocument()
  })

  it('en la conversación, «FAQ» bajo el avatar y la nota de control en la propuesta', async () => {
    await openDemo3()
    const log = screen.getByRole('log', { name: 'Conversación' })
    const labels = within(log).getAllByText('FAQ')
    expect(labels.length).toBeGreaterThan(0)
    for (const label of labels) expect(label.closest('[aria-hidden="true"]')).not.toBeNull()
    expect(within(log).getAllByText('FAQ:', { exact: false }).length).toBeGreaterThan(0)
    expect(within(proposal()).getByText('La decisión es tuya: FAQ no publica nada sin tu aprobación.')).toBeInTheDocument()
  })
})
