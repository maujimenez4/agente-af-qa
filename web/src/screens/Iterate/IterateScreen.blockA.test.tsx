// Bloque A (T-56): Iterar · versión «Jira» con el teclado y en QA (PA-316), Detener (PA-314) y la tarjeta de
// error de /retry (PA-276). DESIGN-DECISIONS.md §4 bis (Iterar). Datos sintéticos.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const SLOW_STEP_MS = 150

async function openFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

const panel = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const versions = () => within(panel()).getByRole('group', { name: 'Versiones' })
const jiraButton = () => within(versions()).getByRole('button', { name: 'Versión de Jira' })

async function askChange(change = 'Cambio ficticio') {
  mockDb.stepDelayMs = SLOW_STEP_MS
  await userEvent.type(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' }), change)
  await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
}

afterEach(() => mockServer.events.removeAllListeners())

describe('Iterar · versión «Jira» (bloque A)', () => {
  it('con el teclado: Intro en «Jira» la muestra y Espacio en «v2» vuelve a la propuesta', async () => {
    /** §4 bis: el selector empieza por *Jira*; se maneja con el teclado como el resto de versiones. */
    await openFromList()
    jiraButton().focus()
    await userEvent.keyboard('{Enter}')
    expect(jiraButton()).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel()).getByText('Así está la HU en Jira ahora. Elige una versión para ver qué cambia.')).toBeInTheDocument()

    await userEvent.tab()
    const v2 = within(versions()).getByRole('button', { name: 'Versión 2' })
    expect(v2).toHaveFocus()
    await userEvent.keyboard(' ')
    expect(v2).toHaveAttribute('aria-pressed', 'true')
    expect(jiraButton()).toHaveAttribute('aria-pressed', 'false')
    expect(within(panel()).getByRole('tablist')).toBeInTheDocument()
  })

  it('con la HU en QA (mode qa, jira_baseline null) no hay versión «Jira»', async () => {
    /** README «Novedades» PA-316: jira_baseline es null en QA; §4 bis: «solo al evolucionar». */
    mockServer.use(
      http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, flow: 'tests', mode: 'qa', jira_baseline: null })),
    )
    await openFromList()
    expect(within(versions()).queryByRole('button', { name: 'Versión de Jira' })).toBeNull()
    expect(within(versions()).getAllByRole('button').map((button) => button.textContent)).toEqual(['v2'])
  })

  it('la versión «Jira» se puede elegir mientras se itera y no tiene pestañas', async () => {
    await openFromList()
    await askChange()
    await screen.findByRole('button', { name: 'Detener la generación' })
    await userEvent.click(jiraButton())
    expect(jiraButton()).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel()).queryByRole('tablist')).toBeNull()
  })
})

describe('Iterar · Detener (bloque A)', () => {
  it('un not_cancellable al detener no se muestra y la iteración termina', async () => {
    /** §4 bis: «*Detener* funciona igual que en Generando»: un not_cancellable no se muestra. */
    mockServer.use(
      http.post('/api/v1/conversations/:id/cancel', () =>
        HttpResponse.json({ error: { code: 'not_cancellable', message: 'No hay nada que detener (ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    await openFromList()
    await askChange()
    await userEvent.click(await screen.findByRole('button', { name: 'Detener la generación' }))
    expect(await within(panel()).findByRole('button', { name: 'Versión 3' }, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.queryByText('No hay nada que detener (ficticio).')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('si falla la petición de detener, lo dice, el botón vuelve a estar activo y la iteración sigue', async () => {
    /** §4 bis: otro error sí se muestra «y la generación sigue». */
    mockServer.use(
      http.post('/api/v1/conversations/:id/cancel', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 }),
      ),
    )
    await openFromList()
    await askChange()
    await userEvent.click(await screen.findByRole('button', { name: 'Detener la generación' }))
    expect(await screen.findByText('Servicio no disponible (ficticio).')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Detener la generación' })).toBeEnabled()
  })

  // Fija un fallo ya corregido al cerrar el bloque A. Antes: IterateScreen.tsx:135 (`if (failure) fail(failure, () => void stop())`) deja el error de detener en
  // `error`, y onReady (IterateScreen.tsx:327-334) no lo limpia. Tras llegar la v3 sigue la tarjeta «Servicio no
  // disponible» con un «Reintentar» que ya no hace nada (stop() sale porque no hay `iterating`). En Generando el
  // error de detener solo se pinta mientras genera (GeneratingScreen.tsx:116, `stopError && state.status === 'running'`).
  // Esperado: al llegar la versión nueva desaparece la tarjeta. Observado: sigue visible.
  it('el error al detener desaparece cuando llega la versión nueva', async () => {
    /** §4 bis: «*Detener* funciona igual que en Generando». */
    mockServer.use(
      http.post('/api/v1/conversations/:id/cancel', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 }),
      ),
    )
    await openFromList()
    await askChange()
    await userEvent.click(await screen.findByRole('button', { name: 'Detener la generación' }))
    await screen.findByText('Servicio no disponible (ficticio).')
    await within(panel()).findByRole('button', { name: 'Versión 3' }, { timeout: 4000 })
    await waitFor(() => expect(screen.queryByText('Servicio no disponible (ficticio).')).toBeNull(), { timeout: 1000 })
  })
})

describe('Iterar · tarjeta de error de /retry (bloque A)', () => {
  it('un /retry rechazado (not_in_error) muestra su tarjeta y «Actualizar» vuelve a la revisión', async () => {
    /** §4 bis Iterar: tarjeta de error; *Actualizar* vuelve a leer la conversación. */
    mockServer.use(
      http.post('/api/v1/conversations/:id/retry', () =>
        HttpResponse.json({ error: { code: 'not_in_error', message: 'No hay nada que reintentar (ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    await openFromList()
    await askChange()
    await userEvent.click(await screen.findByRole('button', { name: 'Detener la generación' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No hay nada que reintentar' })).toBeInTheDocument()
    // La conversación sigue en error en la API simulada: se devuelve en revisión para comprobar que relee.
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(EXAMPLE)))
    await userEvent.click(within(alert).getByRole('button', { name: 'Actualizar' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' })).toBeEnabled()
  })

  it('el titular de «Generación detenida» lleva el tono neutro y «Reintentar»', async () => {
    /** §6: cancelled → «Generación detenida», neutral, Reintentar. */
    await openFromList()
    await askChange()
    await userEvent.click(await screen.findByRole('button', { name: 'Detener la generación' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveAttribute('data-tone', 'neutral')
    expect(within(alert).getByRole('heading', { name: 'Generación detenida' })).toBeInTheDocument()
    expect(within(alert).getByRole('button', { name: 'Reintentar' })).toBeEnabled()
  })
})
