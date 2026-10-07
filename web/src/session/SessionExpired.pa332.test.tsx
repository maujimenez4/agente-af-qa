// PA-332: un 401 en cualquier pantalla lleva al inicio de sesión con la tarjeta «Sesión caducada» (antes
// solo desde Iterar; en el resto, «Iniciar sesión» reintentaba la carga). Al volver a entrar la misma
// persona, se reabre la conversación en la que estaba (el estado vive en el servidor). La sesión caduca
// en la API simulada al vaciar `mockDb.session`: el 401 llega cuando la pantalla hace su siguiente
// petición, sin esperas. Datos sintéticos (DEMO, af-demo, qa-demo).
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client.ts'
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
  vi.restoreAllMocks()
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

  it('con una revisión abierta, elegir una conversación que da 401 la recuerda como conversación (PA-407)', async () => {
    const reviewGets: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      const path = new URL(request.url).pathname
      if (request.method === 'GET' && /^\/api\/v1\/quality-reviews\/[^/]+$/.test(path)) reviewGets.push(path)
    })
    signIn()
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Revisar la calidad de DEMO-3/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Calidad de DEMO-3' })).toBeInTheDocument()
    const opened = reviewGets.length
    // La sesión caduca justo en la petición de la conversación elegida (la vista aún es la de calidad):
    // así el 401 lo da esa petición y no otra anterior.
    mockServer.use(
      http.get(
        '/api/v1/conversations/:id',
        () => {
          expire()
          return HttpResponse.json({ error: { code: 'unauthenticated', message: 'Inicia sesión para continuar.' } }, { status: 401 })
        },
        { once: true },
      ),
    )
    await userEvent.click(within(list).getByRole('button', { name: /Evolucionar DEMO-3/ }))
    await expectExpiredLogin()

    await logIn('af-demo')
    expect(await screen.findByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
    expect(reviewGets).toHaveLength(opened) // no se pide como revisión (daría 404)
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

/** Respuesta 401 retenida hasta que la prueba la suelta. */
function held401(message: string) {
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let arrive: () => void = () => undefined
  const arrived = new Promise<void>((resolve) => {
    arrive = resolve
  })
  const respond = async () => {
    arrive()
    await gate
    return HttpResponse.json({ error: { code: 'unauthenticated', message } }, { status: 401 })
  }
  return { respond, release: () => release(), arrived }
}

/** La promesa de cada llamada a `api[name]`: la prueba espera a que el cliente la haya resuelto. */
function trackCalls<K extends 'iterate'>(name: K) {
  const calls: Promise<unknown>[] = []
  const original = api[name] as (...args: unknown[]) => Promise<unknown>
  vi.spyOn(api, name).mockImplementation(((...args: unknown[]) => {
    const pending = original(...args)
    calls.push(pending)
    return pending
  }) as never)
  return calls
}

/** Espera (dentro de `act`) a que terminen esas peticiones, con éxito o con error. */
async function settled(calls: Promise<unknown>[]) {
  await act(async () => {
    await Promise.allSettled(calls)
  })
}

describe('401 que llegan tarde o a la vez (revisión de web/)', () => {
  it('el 401 de una petición lanzada antes de volver a entrar no vuelve a echar a la persona', async () => {
    const old = held401('Inicia sesión para continuar (petición antigua).')
    mockServer.use(http.post('/api/v1/conversations/:id/iterate', old.respond, { once: true }))
    const iterations = trackCalls('iterate')
    await openDemo3InReview()
    // Una petición larga queda en curso (como una consulta de fuentes o del vigilante)…
    await userEvent.type(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ }), 'Un cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    // …y otra petición descubre la sesión caducada: inicio de sesión.
    expire()
    await userEvent.click(within(screen.getByRole('complementary', { name: 'Conversaciones' })).getByRole('button', { name: 'Nueva conversación' }))
    await expectExpiredLogin()
    await logIn('af-demo')
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()

    // La petición antigua responde ahora con 401: es de la sesión anterior y se ignora.
    await old.arrived
    old.release()
    expect(iterations).toHaveLength(1)
    await settled(iterations) // el cliente ya procesó su 401
    expect(screen.queryByRole('heading', { name: 'Sesión caducada' })).toBeNull()
    expect(screen.getByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('varios 401 a la vez → un solo paso al inicio de sesión', async () => {
    signIn()
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
    // Con la app ya cargada, dos peticiones salen a la vez en esta sesión y las dos responden 401.
    const first = held401('Primer 401 ficticio.')
    const second = held401('Segundo 401 ficticio.')
    mockServer.use(
      http.get('/api/v1/issues/:key', first.respond, { once: true }),
      http.get('/api/v1/memories', second.respond, { once: true }),
    )
    // El rechazo de cada 401 se captura al crear la petición: si no, queda sin manejar hasta `settled` y Vitest acaba con código 1.
    const requests = [api.issue('DEMO-3'), api.memories()].map((call) => call.catch((cause: unknown) => cause))
    await Promise.all([first.arrived, second.arrived])

    first.release()
    await expectExpiredLogin()
    expect(screen.getByText('Primer 401 ficticio.')).toBeInTheDocument()
    second.release()
    await settled(requests) // el cliente ya procesó los dos 401
    // El segundo no vuelve a cambiar el estado: sigue la tarjeta del primero, una sola.
    expect(screen.getAllByRole('heading', { name: 'Sesión caducada' })).toHaveLength(1)
    expect(screen.getByText('Primer 401 ficticio.')).toBeInTheDocument()
    expect(screen.queryByText('Segundo 401 ficticio.')).toBeNull()
  })
})
