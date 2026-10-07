// Editar a mano, pulido final (T-56, PA-344): lo que cierra o cambia el editor desde fuera de su pie (*Actualizar* de la
// tarjeta de error, la tarjeta de la versión en la conversación) pasa por «¿Descartar los cambios?», y *Reintentar* tras
// un error HTTP guarda lo que hay ahora en el editor. Con la App y la API simulada (MSW). Datos sintéticos (DEMO-3).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { EditIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import type { UserStory } from '../Edit/storyDraft.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'

const EXAMPLE_ID = '8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d'
const ORIGINAL_TITLE = 'Renovar un préstamo'
const NEW_TITLE = 'Renovar un préstamo ficticio'
const OTHER_TITLE = 'Renovar un préstamo ficticio corregido'
const GET_CONVERSATION = `GET /api/v1/conversations/${EXAMPLE_ID}`

async function openFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

const proposal = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const editor = () => screen.getByRole('complementary', { name: 'Editar a mano' })
/** El panel del editor, plegado o no (plegado lleva `hidden` y no tiene rol accesible). */
const editorAside = () => screen.getByRole('heading', { level: 2, name: 'Editar a mano', hidden: true }).closest('aside') as HTMLElement
const log = () => screen.getByRole('log', { name: 'Conversación' })
const titleInput = () => within(editor()).getByLabelText('Título')
const saveButton = () => within(editor()).getByRole('button', { name: 'Guardar la versión 3' })
const confirmGroup = () => screen.queryByRole('group', { name: 'Descartar los cambios' })
const versionCard = () => within(log()).getByRole('button', { name: /Propuesta de HU, versión 2/ })

async function startEditing() {
  await openFromList()
  await userEvent.click(within(proposal()).getByRole('button', { name: 'Editar a mano' }))
  return editor()
}

async function editTitle(title = NEW_TITLE) {
  await userEvent.clear(titleInput())
  await userEvent.type(titleInput(), title)
}

/** Peticiones a la API simulada en orden («GET /api/v1/conversations/…»). */
function recordRequests(): string[] {
  const seen: string[] = []
  mockServer.events.on('request:start', ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`)
  })
  return seen
}

/** Respuesta de error HTTP de la API (`ErrorBody`). */
const httpError = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message, retry_after: null } }, { status })

const NOT_IN_REVIEW = 'La conversación no tiene una propuesta en revisión (ficticio).'

/** Abre el editor, cambia el título y guarda contra un 409 `not_in_review`: queda la tarjeta con *Actualizar*. */
async function editAndFailWith409() {
  mockServer.use(http.post('/api/v1/conversations/:id/edit', () => httpError(409, 'not_in_review', NOT_IN_REVIEW), { once: true }))
  await startEditing()
  await editTitle()
  await userEvent.click(saveButton())
  const card = await within(log()).findByRole('alert')
  expect(within(card).getByRole('heading', { name: 'La revisión ya no está abierta' })).toBeInTheDocument()
  return card
}

afterEach(() => {
  mockServer.events.removeAllListeners()
  mockServer.resetHandlers()
})

describe('Iterar · Actualizar con el editor abierto (PA-344)', () => {
  it('test_refresh_asks_confirmation_with_focus_on_keep_editing_when_dirty', async () => {
    /** PA-344(a): *Actualizar* con cambios sin guardar abre «¿Descartar los cambios?» con el foco en «Seguir editando». */
    const card = await editAndFailWith409()
    const requests = recordRequests()
    await userEvent.click(within(card).getByRole('button', { name: 'Actualizar' }))
    const confirm = within(editor()).getByRole('group', { name: 'Descartar los cambios' })
    expect(confirm).toHaveTextContent('¿Descartar los cambios? La versión 2 se queda como está.')
    await waitFor(() => expect(within(confirm).getByRole('button', { name: 'Seguir editando' })).toHaveFocus())
    expect(requests).not.toContain(GET_CONVERSATION)
  })

  it('test_keep_editing_preserves_text_and_skips_reload_when_refresh_dismissed', async () => {
    /** PA-344(a) (negativa): «Seguir editando» conserva el texto escrito y no vuelve a leer la conversación. */
    const card = await editAndFailWith409()
    const requests = recordRequests()
    await userEvent.click(within(card).getByRole('button', { name: 'Actualizar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(confirmGroup()).toBeNull()
    expect(titleInput()).toHaveValue(NEW_TITLE)
    expect(saveButton()).toBeEnabled()
    expect(requests).not.toContain(GET_CONVERSATION)
  })

  it('test_discard_leaves_editor_and_reloads_conversation_when_refresh_confirmed', async () => {
    /** PA-344(a): «Sí, descartar» sale del editor y hace GET /conversations/{id}; se ve la propuesta en la versión 2. */
    const card = await editAndFailWith409()
    const requests = recordRequests()
    await userEvent.click(within(card).getByRole('button', { name: 'Actualizar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    await waitFor(() => expect(requests).toContain(GET_CONVERSATION))
    expect(screen.queryByRole('heading', { name: 'Editar a mano', hidden: true })).toBeNull()
    expect(within(proposal()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(proposal()).getByText(/^Renovar un préstamo$/)).toBeInTheDocument()
    await waitFor(() => expect(within(log()).queryByRole('alert')).toBeNull())
  })

  it('test_refresh_reloads_without_asking_and_keeps_editor_when_clean', async () => {
    /** Actualizar sin cambios: relee sin preguntar y el editor sigue abierto (la versión en revisión no cambió). */
    const card = await editAndFailWith409()
    await editTitle(ORIGINAL_TITLE)
    const requests = recordRequests()
    await userEvent.click(within(card).getByRole('button', { name: 'Actualizar' }))
    await waitFor(() => expect(requests).toContain(GET_CONVERSATION))
    expect(confirmGroup()).toBeNull()
    await waitFor(() => expect(within(log()).queryByRole('alert')).toBeNull())
    expect(editor()).toBeInTheDocument()
    expect(titleInput()).toHaveValue(ORIGINAL_TITLE)
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
  })

  it('test_refresh_opens_folded_panel_to_show_question_when_dirty', async () => {
    /** Con el panel plegado («Ocultar el panel») y cambios, *Actualizar* abre el panel para mostrar la pregunta. */
    const card = await editAndFailWith409()
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    expect(editorAside()).toHaveAttribute('hidden')
    const requests = recordRequests()
    await userEvent.click(within(card).getByRole('button', { name: 'Actualizar' }))
    expect(editorAside()).not.toHaveAttribute('hidden')
    expect(screen.getByRole('button', { name: 'Ocultar el panel' })).toHaveAttribute('aria-expanded', 'true')
    expect(within(editor()).getByRole('group', { name: 'Descartar los cambios' })).toBeInTheDocument()
    expect(requests).not.toContain(GET_CONVERSATION)
  })
})

describe('Iterar · Reintentar tras un error HTTP al guardar (PA-344)', () => {
  it('test_retry_sends_current_editor_content_when_changed_after_503', async () => {
    /** PA-344: tras un 503, si el usuario vuelve a cambiar un campo, *Reintentar* envía el valor nuevo, no el del primer intento. */
    mockServer.use(
      http.post('/api/v1/conversations/:id/edit', () => httpError(503, 'service_unavailable', 'Servicio ficticio caído.'), { once: true }),
    )
    const bodies: EditIn[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/edit')) bodies.push((await request.clone().json()) as EditIn)
    })
    await startEditing()
    await editTitle()
    await userEvent.click(saveButton())
    const card = await within(log()).findByRole('alert')
    expect(within(card).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
    await editTitle(OTHER_TITLE)
    await userEvent.click(within(card).getByRole('button', { name: 'Reintentar' }))
    const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(panel).getByRole('button', { name: 'Versión 3' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel).getByText(OTHER_TITLE)).toBeInTheDocument()
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect((bodies[0]?.content as UserStory).title).toBe(NEW_TITLE)
    expect((bodies[1]?.content as UserStory).title).toBe(OTHER_TITLE)
  })
})

describe('Iterar · abrir una versión desde la conversación mientras se edita (PA-344)', () => {
  /** Abre DEMO-3, deja la versión de Jira seleccionada en el panel y abre el editor (que edita la 2, la que está en revisión). */
  async function editWithJiraSelected() {
    await openFromList()
    await userEvent.click(within(proposal()).getByRole('button', { name: 'Versión de Jira' }))
    expect(within(proposal()).getByRole('button', { name: 'Versión de Jira' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(within(proposal()).getByRole('button', { name: 'Editar a mano' }))
    return editor()
  }

  it('test_version_card_asks_confirmation_when_dirty', async () => {
    /** PA-344(b): con cambios, la tarjeta de la versión pregunta y el editor sigue abierto. */
    await editWithJiraSelected()
    await editTitle()
    await userEvent.click(versionCard())
    expect(within(editor()).getByRole('group', { name: 'Descartar los cambios' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Seguir editando' })).toHaveFocus())
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
  })

  it('test_version_card_keeps_editor_when_keep_editing', async () => {
    /** PA-344(b) (negativa): «Seguir editando» no abre la versión y conserva el texto. */
    await editWithJiraSelected()
    await editTitle()
    await userEvent.click(versionCard())
    await userEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(confirmGroup()).toBeNull()
    expect(titleInput()).toHaveValue(NEW_TITLE)
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
  })

  it('test_version_card_opens_that_version_when_discard_confirmed', async () => {
    /** PA-344(b): al descartar, sale del editor y se ve la propuesta de esa versión (la 2, antes estaba la de Jira). */
    await editWithJiraSelected()
    await editTitle()
    await userEvent.click(versionCard())
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(screen.queryByRole('heading', { name: 'Editar a mano', hidden: true })).toBeNull()
    expect(within(proposal()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(proposal()).getByRole('tab', { name: 'Propuesta' })).toHaveAttribute('aria-selected', 'true')
    expect(versionCard()).toHaveAttribute('aria-pressed', 'true')
    expect(within(proposal()).queryByText(NEW_TITLE)).toBeNull()
  })

  it('test_version_card_opens_that_version_directly_when_clean', async () => {
    /** PA-344(b): sin cambios, la tarjeta sale del editor y abre esa versión sin preguntar. */
    await editWithJiraSelected()
    await userEvent.click(versionCard())
    expect(confirmGroup()).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Editar a mano', hidden: true })).toBeNull()
    expect(within(proposal()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(versionCard()).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ })).toBeEnabled()
  })
})
