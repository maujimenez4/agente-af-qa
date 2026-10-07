// Editar a mano, parte B (T-56, RF-32): el editor en el panel de Iterar, guardar la versión N+1, rechazos de la API,
// errores HTTP, QA «disponible pronto» y el recibo. Con la App y la API simulada (MSW). Datos sintéticos (DEMO-3, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationOut, EditIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { SOON_TEXT } from '../../components/Button/SoonButton.tsx'
import { FINGERPRINT_MISMATCH } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openSuiteForDemo3 } from '../../test/qaFlow.tsx'
import { QA_EDIT_SOON } from './iterateText.ts'

const EXAMPLE_ID = '8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d'
const NEW_TITLE = 'Renovar un préstamo ficticio'
const SUMMARY_V3 = 'Versión 3 guardada: editada a mano, sin llamar al modelo. Afecta también a DEMO-2.'

async function openFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

const proposal = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const editor = () => screen.getByRole('complementary', { name: 'Editar a mano' })
const log = () => screen.getByRole('log', { name: 'Conversación' })
const conversations = () => screen.getByRole('complementary', { name: 'Conversaciones' })
const titleInput = () => within(editor()).getByLabelText('Título')
const saveButton = () => within(editor()).getByRole('button', { name: 'Guardar la versión 3' })

async function startEditing() {
  await openFromList()
  await userEvent.click(within(proposal()).getByRole('button', { name: 'Editar a mano' }))
  return editor()
}

async function editTitle(title = NEW_TITLE) {
  await userEvent.clear(titleInput())
  await userEvent.type(titleInput(), title)
}

/** Peticiones a la API simulada en orden («POST /api/v1/conversations/…/edit»). */
function recordRequests(): string[] {
  const seen: string[] = []
  mockServer.events.on('request:start', ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`)
  })
  return seen
}

/** Cuerpos enviados a POST /edit. */
function recordEditBodies(): EditIn[] {
  const bodies: EditIn[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/edit')) bodies.push((await request.clone().json()) as EditIn)
  })
  return bodies
}

/** Respuesta de error HTTP de la API (`ErrorBody`). */
const httpError = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message, retry_after: null } }, { status })

afterEach(() => {
  mockServer.events.removeAllListeners()
  mockServer.resetHandlers()
})

describe('Iterar · Editar a mano abre el editor (parte B)', () => {
  it('test_editor_opens_with_focus_on_first_field_when_edit_clicked', async () => {
    /** CA 2: *Editar a mano* abre el panel «Editar a mano» con el foco en el primer campo (Título). */
    const panel = await startEditing()
    expect(within(panel).getByRole('heading', { level: 2, name: 'Editar a mano' })).toBeInTheDocument()
    expect(within(panel).getByText('Evolucionar DEMO-3 · versión 2')).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
    expect(titleInput()).toHaveFocus()
    expect(titleInput()).toHaveValue('Renovar un préstamo')
  })

  it('test_composer_disabled_with_hint_when_editing', async () => {
    /** CA 2: mientras se edita, el compositor está desactivado con «Guarda o cancela la edición para pedir cambios». */
    await startEditing()
    const composer = screen.getByRole('textbox', { name: /^Guarda o cancela la edición para pedir cambios/ })
    expect(composer).toBeDisabled()
    expect(composer).toHaveAttribute('placeholder', 'Guarda o cancela la edición para pedir cambios')
  })

  it('test_cancel_returns_to_proposal_when_no_changes', async () => {
    /** CA 2: *Cancelar* sin cambios vuelve a la propuesta sin preguntar y reactiva el compositor. */
    const requests = recordRequests()
    await startEditing()
    await userEvent.click(within(editor()).getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('group', { name: 'Descartar los cambios' })).toBeNull()
    expect(screen.queryByRole('complementary', { name: 'Editar a mano' })).toBeNull()
    expect(within(proposal()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ })).toBeEnabled()
    expect(requests.some((item) => item.endsWith('/edit'))).toBe(false)
  })

  it('test_cancel_asks_confirmation_and_discards_when_changes', async () => {
    /** CA 2 (negativa): con cambios, *Cancelar* pregunta; «Sí, descartar» vuelve a la versión 2 sin llamar a la API. */
    const requests = recordRequests()
    await startEditing()
    await editTitle()
    await userEvent.click(within(editor()).getByRole('button', { name: 'Cancelar' }))
    const confirm = within(editor()).getByRole('group', { name: 'Descartar los cambios' })
    expect(confirm).toHaveTextContent('¿Descartar los cambios? La versión 2 se queda como está.')
    await userEvent.click(within(confirm).getByRole('button', { name: 'Sí, descartar' }))
    expect(within(proposal()).getByText(/^Renovar un préstamo$/)).toBeInTheDocument()
    expect(requests.some((item) => item.endsWith('/edit'))).toBe(false)
  })
})

describe('Iterar · guardar la edición (parte B)', () => {
  it('test_panel_shows_new_version_selected_when_saved', async () => {
    /** CA 3: al guardar, el panel vuelve a la propuesta con la versión 3 seleccionada y el título editado. */
    await startEditing()
    await editTitle()
    await userEvent.click(saveButton())
    const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(panel).getByRole('button', { name: 'Versión 3' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'false')
    expect(within(panel).getByRole('tab', { name: 'Propuesta' })).toHaveAttribute('aria-selected', 'true')
    expect(within(panel).getByText(NEW_TITLE)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ })).toBeEnabled()
  })

  it('test_conversation_adds_edited_summary_and_meta_when_saved', async () => {
    /** CA 3: la conversación añade «Versión 3 guardada: editada a mano…» y «Editada a mano · 2 fuentes», sin modelo. */
    await startEditing()
    await editTitle()
    await userEvent.click(saveButton())
    await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(log()).getAllByText(SUMMARY_V3).length).toBeGreaterThan(0)
    expect(within(log()).getByText('Editada a mano · 2 fuentes')).toBeInTheDocument()
    expect(within(log()).getByRole('button', { name: /Propuesta de HU, versión 3/ })).toHaveAttribute('aria-pressed', 'true')
    // La versión 2 sigue citando su modelo; la 3 no.
    expect(within(log()).getAllByText(/^Generado con /)).toHaveLength(1)
    expect(within(log()).queryByText(/Nota de la edición/)).toBeNull()
  })

  it('test_conversation_shows_note_when_saved_with_note', async () => {
    /** CA 3: con nota, la conversación la muestra como «Nota de la edición: …» y se envía como feedback. */
    const bodies = recordEditBodies()
    await startEditing()
    await editTitle()
    await userEvent.type(within(editor()).getByLabelText('Nota de la edición (opcional)'), '  Ajuste ficticio del título  ')
    await userEvent.click(saveButton())
    await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(log()).getByText('Nota de la edición: Ajuste ficticio del título')).toBeInTheDocument()
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]?.feedback).toBe('Ajuste ficticio del título')
    expect(bodies[0]?.fingerprint).toBe('4f'.repeat(32))
  })

  it('test_conversation_list_reloaded_after_post_when_saved', async () => {
    /** CA 3: tras el POST /edit se vuelve a leer GET /conversations y la lista pasa a «Versión 3». */
    await openFromList()
    const item = within(conversations()).getByRole('button', { name: /Evolucionar DEMO-3/ })
    expect(item).toHaveTextContent('Versión 2')
    const requests = recordRequests()
    await userEvent.click(within(proposal()).getByRole('button', { name: 'Editar a mano' }))
    await editTitle()
    await userEvent.click(saveButton())
    await waitFor(() => expect(within(conversations()).getByRole('button', { name: /Evolucionar DEMO-3/ })).toHaveTextContent('Versión 3'))
    const post = requests.indexOf(`POST /api/v1/conversations/${EXAMPLE_ID}/edit`)
    expect(post).toBeGreaterThanOrEqual(0)
    expect(requests.slice(post + 1)).toContain('GET /api/v1/conversations')
  })
})

describe('Iterar · rechazos y errores al guardar (parte B)', () => {
  it('test_stays_in_editor_with_message_verbatim_when_review_error', async () => {
    /** CA 4: rechazo de la API (`review.error`, huella que no casa): se queda en el editor, con el motivo tal cual. */
    await startEditing()
    const run = mockDb.runs.get(EXAMPLE_ID)
    if (!run?.conversation.review) throw new Error('La API simulada no tiene la conversación de ejemplo')
    run.conversation = { ...run.conversation, review: { ...run.conversation.review, fingerprint: 'ab'.repeat(32) } }
    const requests = recordRequests()
    await editTitle()
    await userEvent.click(saveButton())
    const alert = await within(editor()).findByRole('alert')
    expect(alert).toHaveTextContent(`No se guardó la edición. ${FINGERPRINT_MISMATCH}`)
    expect(titleInput()).toHaveValue(NEW_TITLE)
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
    expect(within(log()).queryByText(/Versión 3 guardada/)).toBeNull()
    expect(within(log()).queryByRole('button', { name: /Propuesta de HU, versión 3/ })).toBeNull()
    // Sin versión nueva no se vuelve a leer la lista.
    expect(requests).not.toContain('GET /api/v1/conversations')
  })

  it('test_review_error_shown_as_text_when_it_contains_markup', async () => {
    /** CA 4 (límite): el motivo se pinta como texto, nunca como HTML. */
    const reason = '<b>Motivo ficticio</b> de rechazo: revisa acceptance_criteria.0.given.'
    mockServer.use(
      http.post('/api/v1/conversations/:id/edit', () => {
        const current = mockDb.runs.get(EXAMPLE_ID)?.conversation as ConversationOut
        return HttpResponse.json({ ...current, review: { ...current.review, error: reason } })
      }),
    )
    await startEditing()
    await editTitle()
    await userEvent.click(saveButton())
    const alert = await within(editor()).findByRole('alert')
    expect(alert).toHaveTextContent(`No se guardó la edición. ${reason}`)
    expect(alert.querySelector('b b')).toBeNull()
  })

  it('test_error_card_in_conversation_when_http_409', async () => {
    /** CA 4: un 409 (`not_in_review`) sale como tarjeta en la conversación, con su mensaje tal cual. */
    const message = 'La conversación no tiene una propuesta en revisión (está generando o ya terminó).'
    mockServer.use(
      http.post('/api/v1/conversations/:id/edit', () => httpError(409, 'not_in_review', message)),
    )
    await startEditing()
    await editTitle()
    await userEvent.click(saveButton())
    const card = await within(log()).findByRole('alert')
    expect(within(card).getByRole('heading', { name: 'La revisión ya no está abierta' })).toBeInTheDocument()
    expect(card).toHaveTextContent(message)
    expect(within(editor()).queryByRole('alert')).toBeNull()
    expect(within(log()).queryByText(/Versión 3 guardada/)).toBeNull()
  })

  it('test_error_card_with_retry_when_http_503_and_retry_saves', async () => {
    /** CA 4: un 503 sale como tarjeta con *Reintentar*; reintentar repite el guardado con el mismo contenido. */
    const message = 'El servicio ficticio no está disponible ahora.'
    mockServer.use(
      http.post('/api/v1/conversations/:id/edit', () => httpError(503, 'service_unavailable', message), { once: true }),
    )
    const bodies = recordEditBodies()
    await startEditing()
    await editTitle()
    await userEvent.click(saveButton())
    const card = await within(log()).findByRole('alert')
    expect(within(card).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
    expect(card).toHaveTextContent(message)
    expect(editor()).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: 'Reintentar' }))
    const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(panel).getByRole('button', { name: 'Versión 3' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(log()).queryByRole('alert')).toBeNull()
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[1]?.content).toEqual(bodies[0]?.content)
  })
})

describe('Iterar QA · Editar a mano (parte B)', () => {
  it('test_edit_by_hand_still_soon_when_qa', async () => {
    /** CA 5: en QA, *Editar a mano* sigue «disponible pronto» (aria-disabled, con la nota) y no abre el editor. */
    await openSuiteForDemo3()
    const panel = screen.getByRole('complementary', { name: 'Suite de pruebas' })
    const button = within(panel).getByRole('button', { name: 'Editar a mano' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    // PA-346: el motivo propio de la suite (también visible en el pie), no el genérico.
    expect(button).toHaveAccessibleDescription(`Disponible pronto: ${QA_EDIT_SOON}`)
    expect(button).not.toHaveAccessibleDescription(SOON_TEXT)
    await userEvent.click(button)
    expect(screen.queryByRole('complementary', { name: 'Editar a mano' })).toBeNull()
    expect(screen.getByRole('complementary', { name: 'Suite de pruebas' })).toBeInTheDocument()
  })
})

describe('Recibo · versiones editadas a mano (parte B)', () => {
  it('test_receipt_history_marks_edited_version_without_model_or_prompt', async () => {
    /** CA 6: en el recibo, «Versión 3 editada a mano» sin modelo ni versión del prompt; la 2 sigue «generada». */
    await startEditing()
    await editTitle()
    await userEvent.click(saveButton())
    const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
    await screen.findByRole('heading', { level: 2, name: 'Versión 3 lista para revisar' })
    const history = screen.getByRole('list', { name: 'Versiones de la propuesta' })
    const items = within(history).getAllByRole('listitem')
    const edited = items.find((item) => item.textContent?.includes('Versión 3')) as HTMLElement
    const generated = items.find((item) => item.textContent?.includes('Versión 2')) as HTMLElement
    expect(within(edited).getByText('Versión 3 editada a mano')).toBeInTheDocument()
    expect(edited).not.toHaveTextContent(/qwen|local ·|prompt v/)
    expect(within(generated).getByText('Versión 2 generada')).toBeInTheDocument()
    expect(generated).toHaveTextContent('local · qwen3:4b-instruct')
    expect(generated).toHaveTextContent('prompt v2')
  })

  it('test_receipt_history_says_generated_when_not_edited', async () => {
    /** CA 6 (negativa): sin editar, la versión en revisión sale «generada» con su modelo. */
    await openFromList()
    await userEvent.click(within(proposal()).getByRole('button', { name: 'Revisar y aprobar' }))
    await screen.findByRole('heading', { level: 2, name: 'Versión 2 lista para revisar' })
    const history = screen.getByRole('list', { name: 'Versiones de la propuesta' })
    expect(within(history).getByText('Versión 2 generada')).toBeInTheDocument()
    expect(within(history).queryByText(/editada a mano/)).toBeNull()
  })
})
