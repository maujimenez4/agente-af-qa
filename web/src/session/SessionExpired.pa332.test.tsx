// PA-332: un 401 en cualquier pantalla lleva al inicio de sesión con la tarjeta «Sesión caducada» (antes
// solo desde Iterar; en el resto, «Iniciar sesión» reintentaba la carga). Al volver a entrar la misma
// persona, se reabre la conversación en la que estaba (el estado vive en el servidor). La sesión caduca
// en la API simulada al vaciar `mockDb.session`: el 401 llega cuando la pantalla hace su siguiente
// petición, sin esperas. Datos sintéticos (DEMO, af-demo, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../App.tsx'
import { DEMO_PASSWORD } from '../mocks/db.ts'
import { mockDb, mockServer } from '../mocks/node.ts'

const expire = () => {
  mockDb.session = null
}

function signIn(username: 'af-demo' | 'qa-demo' = 'af-demo') {
  mockDb.session = { username, role: username === 'qa-demo' ? 'qa' : 'functional', csrf: 'csrf-ficticio' }
}

async function expectExpiredLogin() {
  const card = await screen.findByRole('heading', { name: 'Sesión caducada' })
  expect(card).toBeInTheDocument()
  expect(screen.getByLabelText('Usuario')).toBeInTheDocument()
  expect(screen.getByLabelText('Contraseña')).toBeInTheDocument()
  expect(screen.queryByRole('complementary', { name: 'Conversaciones' })).toBeNull()
}

async function logIn(username: string) {
  await userEvent.type(screen.getByLabelText('Usuario'), username)
  await userEvent.type(screen.getByLabelText('Contraseña'), DEMO_PASSWORD)
  await userEvent.click(screen.getByRole('button', { name: 'Iniciar sesión' }))
}

async function openDemo3InReview() {
  signIn()
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Sesión caducada en cualquier pantalla (PA-332)', () => {
  it('en Inicio, un 401 al continuar lleva al inicio de sesión con la tarjeta', async () => {
    signIn()
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    expire()
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await expectExpiredLogin()
  })

  it('en Origen y fuentes, un 401 al elegir la operación (consulta de fuentes) lleva al inicio de sesión', async () => {
    signIn()
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    const evolve = await screen.findByRole('button', { name: 'Evolucionar DEMO-3' })
    expire()
    await userEvent.click(evolve)
    await expectExpiredLogin()
  })

  it('en el recibo, un 401 al aprobar lleva al inicio de sesión (sin aprobar nada)', async () => {
    const approvals: string[] = []
    mockServer.events.on('response:mocked', ({ request, response }) => {
      if (new URL(request.url).pathname.endsWith('/approve')) approvals.push(String(response.status))
    })
    const panel = await openDemo3InReview()
    await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
    const operations = await screen.findByRole('group', { name: /Qué se hará en Jira/ })
    for (const box of within(operations).getAllByRole('checkbox')) await userEvent.click(box)
    expire()
    await userEvent.click(screen.getByRole('button', { name: 'Aprobar y publicar' }))
    await expectExpiredLogin()
    expect(approvals).toEqual(['401'])
  })

  it('el mensaje es el de la API y no hay botón que reintente la carga', async () => {
    mockServer.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ error: { code: 'unauthenticated', message: 'Tu sesión ha caducado (mensaje ficticio).' } }, { status: 401 }),
      ),
    )
    signIn()
    render(<App />)
    await expectExpiredLogin()
    expect(screen.getByText('Tu sesión ha caducado (mensaje ficticio).')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull()
  })
})

describe('Volver a entrar tras la sesión caducada (PA-332)', () => {
  it('la misma persona vuelve a la conversación en la que estaba', async () => {
    await openDemo3InReview()
    // Pedir un cambio en Iterar (POST /iterate) con la sesión ya caducada: 401.
    await userEvent.type(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ }), 'Un cambio ficticio')
    expire()
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await expectExpiredLogin()

    await logIn('af-demo')
    expect(await screen.findByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
    const list = screen.getByRole('complementary', { name: 'Conversaciones' })
    expect(within(list).getByRole('button', { name: /Evolucionar DEMO-3/ })).toHaveAttribute('aria-current')
  })

  it('una revisión de calidad abierta se reabre como revisión, sin pedirla como conversación (PA-407)', async () => {
    const conversationGets: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      const path = new URL(request.url).pathname
      if (request.method === 'GET' && /^\/api\/v1\/conversations\/[^/]+$/.test(path)) conversationGets.push(path)
    })
    signIn()
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Revisar la calidad de DEMO-3/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Calidad de DEMO-3' })).toBeInTheDocument()
    // «Evolucionar con esto» (POST /conversations) con la sesión ya caducada: 401.
    expire()
    await userEvent.click(screen.getByRole('button', { name: 'Evolucionar DEMO-3 con esto' }))
    await expectExpiredLogin()

    await logIn('af-demo')
    expect(await screen.findByRole('heading', { level: 1, name: 'Calidad de DEMO-3' })).toBeInTheDocument()
    const again = screen.getByRole('complementary', { name: 'Conversaciones' })
    expect(await within(again).findByRole('button', { name: /Revisar la calidad de DEMO-3/ })).toHaveAttribute('aria-current', 'true')
    expect(conversationGets).toEqual([]) // nunca GET /conversations/{id de la revisión} (daría 404)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('otra persona no hereda la conversación: entra en su inicio', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id', () => {
        if (mockDb.session === null) {
          return HttpResponse.json({ error: { code: 'unauthenticated', message: 'Inicia sesión para continuar.' } }, { status: 401 })
        }
        return undefined
      }),
    )
    signIn()
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    const item = await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ })
    expire()
    await userEvent.click(item)
    await expectExpiredLogin()

    await logIn('qa-demo')
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
  })

  it('un usuario o contraseña incorrectos en el inicio de sesión no es una sesión caducada', async () => {
    render(<App />)
    await screen.findByLabelText('Usuario')
    expect(screen.queryByRole('heading', { name: 'Sesión caducada' })).toBeNull() // el 401 de /auth/me al arrancar
    await userEvent.type(screen.getByLabelText('Usuario'), 'af-demo')
    await userEvent.type(screen.getByLabelText('Contraseña'), 'no-es-la-buena')
    await userEvent.click(screen.getByRole('button', { name: 'Iniciar sesión' }))
    expect(await screen.findByText('Usuario o contraseña incorrectos.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sesión caducada' })).toBeNull()
  })
})
