// QA 3 · Editar a mano la suite (PA-158, UI.md §6.3): abrir el editor con la suite en revisión, editar y guardar con
// POST /edit (suite completa, huella y nota), los errores junto al campo, la cobertura en vivo (un CA sin caso bloquea
// la aprobación; una RN, solo avisa), `review.error` tal cual, cancelar con cambios y el teclado. Con la App y la API
// simulada (MSW). Datos sintéticos (DEMO-3, qa-demo; CP-01…CP-04 sobre CA-01, CA-02, RN-01 y RN-02).
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ApproveIn, ConversationOut, EditIn, TestSuite } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openSuiteInReview } from '../../test/qaFlow.tsx'

const NOTE = 'Ajuste ficticio del título de CP-01'
const NEW_TITLE = 'Renovar un préstamo ficticio sin reservas'

const suitePanel = () => screen.getByRole('complementary', { name: 'Suite de pruebas' })
const editor = () => screen.getByRole('complementary', { name: 'Editar a mano' })
const log = () => screen.getByRole('log', { name: 'Conversación' })
const caseItem = (id: string) => within(editor()).getByRole('listitem', { name: id })
const saveButton = () => within(editor()).getByRole('button', { name: /^Guardar la versión/ })
const coverageStatus = () => within(editor()).getByText('Cobertura').closest('[role="status"]') as HTMLElement

async function openEditor() {
  await openSuiteInReview()
  await userEvent.click(within(suitePanel()).getByRole('button', { name: 'Editar a mano' }))
  return editor()
}

async function replace(field: HTMLElement, value: string) {
  await userEvent.clear(field)
  if (value) await userEvent.paste(value)
}

/** Peticiones de la API simulada: cuerpos de /edit y /approve, y la última conversación que devolvió /edit. */
function record() {
  const edits: EditIn[] = []
  const approvals: ApproveIn[] = []
  const answers: ConversationOut[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method !== 'POST') return
    const path = new URL(request.url).pathname
    if (path.endsWith('/edit')) edits.push((await request.clone().json()) as EditIn)
    if (path.endsWith('/approve')) approvals.push((await request.clone().json()) as ApproveIn)
  })
  mockServer.events.on('response:mocked', async ({ request, response }) => {
    if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/edit')) answers.push((await response.clone().json()) as ConversationOut)
  })
  return { edits, approvals, answers }
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('QA 3 · Editar a mano la suite (PA-158)', () => {
  it('abre el editor con la suite en revisión y el foco en el primer campo', async () => {
    await openEditor()
    expect(screen.queryByRole('complementary', { name: 'Suite de pruebas' })).toBeNull()
    expect(within(editor()).getByText(/HU DEMO-3 · 1 fuente\. La clave de la HU y las fuentes no se editan\./)).toBeInTheDocument()
    expect(within(editor()).getByRole('heading', { name: 'Casos (4)' })).toBeInTheDocument()
    const first = caseItem('CP-01')
    expect(within(first).getByLabelText('Identificador de CP-01')).toHaveFocus()
    expect(within(first).getByLabelText('Identificador de CP-01')).toHaveValue('CP-01')
    expect(within(first).getByLabelText('Tipo')).toHaveValue('positivo')
    expect(within(first).getByLabelText('Prioridad')).toHaveValue('Must')
    expect(within(first).getByLabelText('Verifica (CA y RN)')).toHaveValue('CA-01, RN-01')
    expect(within(first).getByRole('listitem', { name: 'paso 1 de CP-01' })).toBeInTheDocument()
    expect(within(editor()).getByLabelText('prestamo, fila 1')).toHaveValue('PR-0001')
    expect(within(editor()).getByLabelText('Riesgos')).toHaveValue('El catálogo puede no responder al renovar.')
    expect((within(editor()).getByLabelText(/^Estrategia de pruebas/) as HTMLTextAreaElement).value).toMatch(/^# Estrategia de pruebas · DEMO-3/)
    expect(coverageStatus()).toHaveTextContent('Cada CA y cada RN de la HU tiene al menos un caso.')
    // El compositor espera a que se guarde o se cancele.
    expect(screen.getByRole('textbox', { name: /Guarda o cancela la edición/ })).toBeDisabled()
    expect(saveButton()).toBeDisabled()
  })

  it('editar un caso y guardar: POST /edit con la suite completa, la huella mostrada y la nota', async () => {
    const calls = record()
    await openEditor()
    const fingerprint = mockDb.runs.values().next().value?.conversation.review?.fingerprint
    await replace(within(caseItem('CP-01')).getByLabelText('Título de CP-01'), NEW_TITLE)
    await userEvent.type(within(editor()).getByLabelText('Nota de la edición (opcional)'), NOTE)
    expect(saveButton()).toHaveTextContent('Guardar la versión 2')
    await userEvent.click(saveButton())
    await screen.findByRole('complementary', { name: 'Suite de pruebas' })
    await waitFor(() => expect(calls.edits).toHaveLength(1))
    const body = calls.edits[0] as EditIn
    const content = body.content as TestSuite
    expect(body.fingerprint).toBe(fingerprint)
    expect(body.feedback).toBe(NOTE)
    expect(content.story_jira_key).toBe('DEMO-3')
    expect(content.cases.map((item) => item.internal_id)).toEqual(['CP-01', 'CP-02', 'CP-03', 'CP-04'])
    expect(content.cases[0]?.title).toBe(NEW_TITLE)
    expect(content.cases[1]).toMatchObject({ internal_id: 'CP-02', type: 'negativo', criterion_ids: ['CA-02'], rule_ids: ['RN-02'] })
    expect(content.synthetic_data).toHaveLength(3)
    expect(content.strategy_md).toMatch(/^# Estrategia de pruebas · DEMO-3/)
    expect(content.sources).toHaveLength(1)
    // En la conversación: la nota y la versión guardada sin el modelo.
    expect(within(log()).getByText(`Nota de la edición: ${NOTE}`)).toBeInTheDocument()
    expect(within(log()).getAllByText('Versión 2 guardada: editada a mano, sin llamar al modelo. 4 casos; todos los CA cubiertos.').length).toBeGreaterThan(0)
    expect(within(suitePanel()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(suitePanel()).getByText(NEW_TITLE)).toBeInTheDocument()
  })

  it('ids repetidos o vacíos: el error va junto a su campo, se anuncia y no deja guardar', async () => {
    await openEditor()
    const id = within(caseItem('CP-02')).getByLabelText('Identificador de CP-02')
    await replace(id, 'CP-01')
    const repeated = within(editor()).getAllByLabelText('Identificador de CP-01')
    for (const field of repeated) {
      expect(field).toHaveAttribute('aria-invalid', 'true')
      expect(field).toHaveAccessibleDescription('El identificador CP-01 está repetido.')
    }
    expect(saveButton()).toBeDisabled()
    // El resumen del pie (aria-live) lo dice también.
    expect(within(editor()).getByText('Antes de guardar:').closest('[aria-live="polite"]')).toHaveTextContent('El identificador CP-01 está repetido.')
    const third = within(editor()).getByLabelText('Identificador de CP-03')
    await replace(third, '')
    expect(within(editor()).getByLabelText('Identificador de caso 3')).toHaveAccessibleDescription(
      'El caso 3: el identificador debe ser «CP-» y un número (por ejemplo, CP-05).',
    )
  })

  it('sin un caso negativo no se puede guardar: el aviso describe cada selector de tipo', async () => {
    await openEditor()
    await userEvent.selectOptions(within(caseItem('CP-02')).getByLabelText('Tipo'), 'positivo')
    expect(within(editor()).getByRole('heading', { name: 'Casos (4)' }).parentElement).toHaveTextContent('La suite necesita al menos un caso negativo.')
    expect(within(caseItem('CP-01')).getByLabelText('Tipo')).toHaveAccessibleDescription('La suite necesita al menos un caso negativo.')
    expect(saveButton()).toBeDisabled()
  })

  it('una referencia a un CA que no existe en la HU: error junto a «Verifica»', async () => {
    await openEditor()
    const refs = within(caseItem('CP-01')).getByLabelText('Verifica (CA y RN)')
    expect(refs).toHaveAccessibleDescription(/En la HU: CA-01, CA-02, RN-01, RN-02\./)
    await replace(refs, 'CA-01, CA-09')
    expect(refs).toHaveAttribute('aria-invalid', 'true')
    expect(refs).toHaveAccessibleDescription(/CA-09 no existe en la HU\./)
    expect(saveButton()).toBeDisabled()
  })

  it('quitar el único caso de un CA: la cobertura avisa al momento, se guarda y el recibo no deja aprobar', async () => {
    await openEditor()
    await replace(within(caseItem('CP-02')).getByLabelText('Verifica (CA y RN)'), 'CA-01, RN-02')
    expect(coverageStatus()).toHaveTextContent('Falta un caso para CA-02. Podrás guardar, pero no aprobar la suite hasta que cada CA tenga un caso.')
    expect(saveButton()).toBeEnabled()
    await userEvent.click(saveButton())
    await screen.findByRole('complementary', { name: 'Suite de pruebas' })
    // La revisión nueva trae `uncovered` con CA-02: el aviso de Iterar y el bloqueo del recibo.
    expect(await within(suitePanel()).findByRole('note')).toHaveTextContent('Falta un caso para CA-02.')
    await userEvent.click(within(suitePanel()).getByRole('button', { name: 'Revisar y aprobar' }))
    const approve = await screen.findByRole('button', { name: 'Aprobar y publicar' })
    for (const box of screen.getAllByRole('checkbox')) await userEvent.click(box)
    expect(approve).toBeDisabled()
    expect(screen.getByText('Falta un caso para CA-02.')).toBeInTheDocument()
  })

  it('el único caso de una RN: solo avisa; tras guardar se aprueba con la huella de la versión editada', async () => {
    const calls = record()
    await openEditor()
    await replace(within(caseItem('CP-02')).getByLabelText('Verifica (CA y RN)'), 'CA-02')
    expect(coverageStatus()).toHaveTextContent('Sin ningún caso: RN-02. Una RN sin caso no impide aprobar.')
    await userEvent.click(saveButton())
    await screen.findByRole('complementary', { name: 'Suite de pruebas' })
    await waitFor(() => expect(calls.answers).toHaveLength(1))
    const edited = calls.answers[0]?.review
    expect(edited?.version).toBe(2)
    expect(edited?.uncovered).toEqual({ criteria: [], rules: ['RN-02'] })
    await userEvent.click(within(suitePanel()).getByRole('button', { name: 'Revisar y aprobar' }))
    const approve = await screen.findByRole('button', { name: 'Aprobar y publicar' })
    for (const box of screen.getAllByRole('checkbox')) await userEvent.click(box)
    expect(approve).toBeEnabled()
    await userEvent.click(approve)
    await waitFor(() => expect(calls.approvals).toHaveLength(1))
    // Principio 1: editar no publica; se aprueba la versión editada con su huella.
    expect(calls.approvals[0]?.fingerprint).toBe(edited?.fingerprint)
  })

  it('si la API rechaza la edición (review.error), su mensaje sale tal cual y el editor sigue abierto', async () => {
    const message = 'La edición no se puede guardar: synthetic_data[0].prestamo parece un DNI real; usa un valor ficticio.'
    mockServer.use(
      http.post('/api/v1/conversations/:id/edit', ({ params }) => {
        const run = mockDb.runs.get(String(params.id))
        const conversation = run?.conversation as ConversationOut
        return HttpResponse.json({ ...conversation, review: { ...conversation.review, error: message } })
      }),
    )
    await openEditor()
    await replace(within(caseItem('CP-01')).getByLabelText('Título de CP-01'), NEW_TITLE)
    await userEvent.click(saveButton())
    const alert = await within(editor()).findByRole('alert')
    expect(alert).toHaveTextContent(`No se guardó la edición. ${message}`)
    expect(within(caseItem('CP-01')).getByLabelText('Título de CP-01')).toHaveValue(NEW_TITLE)
  })

  it('cancelar con cambios pregunta antes; «Seguir editando» los conserva y «Sí, descartar» vuelve a la suite', async () => {
    const calls = record()
    await openEditor()
    await replace(within(caseItem('CP-01')).getByLabelText('Título de CP-01'), NEW_TITLE)
    await userEvent.click(within(editor()).getByRole('button', { name: 'Cancelar' }))
    const confirm = within(editor()).getByRole('group', { name: 'Descartar los cambios' })
    expect(confirm).toHaveTextContent('¿Descartar los cambios? La versión 1 se queda como está.')
    await waitFor(() => expect(within(confirm).getByRole('button', { name: 'Seguir editando' })).toHaveFocus())
    await userEvent.click(within(confirm).getByRole('button', { name: 'Seguir editando' }))
    expect(within(caseItem('CP-01')).getByLabelText('Título de CP-01')).toHaveValue(NEW_TITLE)
    await userEvent.click(within(editor()).getByRole('button', { name: 'Cancelar' }))
    await userEvent.click(within(editor()).getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('complementary', { name: 'Suite de pruebas' })).toBeInTheDocument()
    expect(calls.edits).toHaveLength(0)
  })

  it('con el teclado: mover, quitar y añadir casos y pasos, sin perder el foco', async () => {
    await openEditor()
    const ids = () => within(editor()).getAllByLabelText(/^Identificador de /).map((field) => (field as HTMLInputElement).value)
    // Bajar CP-01 con Intro: pasa a la segunda posición y el foco sigue en su botón.
    within(caseItem('CP-01')).getByRole('button', { name: 'Bajar CP-01' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(ids()).toEqual(['CP-02', 'CP-01', 'CP-03', 'CP-04'])
    expect(within(caseItem('CP-01')).getByRole('button', { name: 'Bajar CP-01' })).toHaveFocus()
    expect(within(editor()).getByText('CP-01 pasa a la posición 2.')).toBeInTheDocument()
    // Subir el que ha quedado primero no es posible: al subirlo, el foco va a «Bajar».
    within(caseItem('CP-01')).getByRole('button', { name: 'Subir CP-01' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(ids()).toEqual(['CP-01', 'CP-02', 'CP-03', 'CP-04'])
    expect(within(caseItem('CP-01')).getByRole('button', { name: 'Bajar CP-01' })).toHaveFocus()
    // Quitar CP-04 con Espacio: el foco va a «Añadir un caso».
    within(caseItem('CP-04')).getByRole('button', { name: 'Quitar CP-04' }).focus()
    await userEvent.keyboard(' ')
    expect(ids()).toEqual(['CP-01', 'CP-02', 'CP-03'])
    const add = within(editor()).getByRole('button', { name: 'Añadir un caso' })
    expect(add).toHaveFocus()
    // Añadir un caso: CP-04 otra vez libre, el foco en su identificador.
    await userEvent.keyboard('{Enter}')
    expect(ids()).toEqual(['CP-01', 'CP-02', 'CP-03', 'CP-04'])
    expect(within(caseItem('CP-04')).getByLabelText('Identificador de CP-04')).toHaveFocus()
    // Pasos: añadir uno a CP-01 y subirlo.
    within(caseItem('CP-01')).getByRole('button', { name: 'Añadir un paso a CP-01' }).focus()
    await userEvent.keyboard('{Enter}')
    const steps = () => within(caseItem('CP-01')).getAllByRole('listitem').map((item) => item.getAttribute('aria-label'))
    expect(steps()).toEqual(['paso 1 de CP-01', 'paso 2 de CP-01', 'paso 3 de CP-01'])
    const third = within(caseItem('CP-01')).getByRole('listitem', { name: 'paso 3 de CP-01' })
    await userEvent.type(within(third).getByLabelText('Acción'), 'Pulsar «Renovar» otra vez')
    within(third).getByRole('button', { name: 'Subir paso 3 de CP-01' }).focus()
    await userEvent.keyboard('{Enter}')
    const second = within(caseItem('CP-01')).getByRole('listitem', { name: 'paso 2 de CP-01' })
    expect(within(second).getByLabelText('Acción')).toHaveValue('Pulsar «Renovar» otra vez')
    expect(within(second).getByRole('button', { name: 'Subir paso 2 de CP-01' })).toHaveFocus()
  })
})

describe('QA 3 · Editar a mano · datos ficticios (PA-158)', () => {
  it('añadir una columna con nombre y valor y quitar una fila, con el teclado; se envía así', async () => {
    const calls = record()
    await openEditor()
    within(editor()).getByRole('button', { name: 'Añadir una columna' }).focus()
    await userEvent.keyboard('{Enter}')
    const name = within(editor()).getByLabelText('Nombre de la columna 4')
    // Sin nombre y sin valores, solo avisa; con un valor, necesita nombre.
    expect(name).toHaveAccessibleDescription('La columna 4 de los datos no tiene nombre ni valores: no se enviará.')
    await userEvent.type(within(editor()).getByLabelText('columna 4, fila 1'), 'ficticio')
    expect(name).toHaveAttribute('aria-invalid', 'true')
    expect(name).toHaveAccessibleDescription('La columna 4 de los datos necesita un nombre.')
    await userEvent.type(name, 'motivo')
    expect(name).not.toHaveAttribute('aria-invalid')
    within(editor()).getByRole('button', { name: 'Quitar la fila 3' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(within(editor()).getByRole('button', { name: 'Añadir una fila' })).toHaveFocus()
    expect(within(editor()).getByText('Fila 3 quitada.')).toBeInTheDocument()
    await userEvent.click(saveButton())
    await screen.findByRole('complementary', { name: 'Suite de pruebas' })
    await waitFor(() => expect(calls.edits).toHaveLength(1))
    expect((calls.edits[0]?.content as TestSuite).synthetic_data).toEqual([
      { prestamo: 'PR-0001', renovaciones: '0', reservas: '0', motivo: 'ficticio' },
      { prestamo: 'PR-0002', renovaciones: '0', reservas: '1' },
    ])
  })
})

describe('QA 3 · Editar a mano sin saber la HU (uncovered null)', () => {
  it('solo comprueba el formato: no hay cobertura en vivo y lo dice', async () => {
    mockDb.forceCoverage = 'unknown'
    await openEditor()
    expect(coverageStatus()).toHaveTextContent('No se sabe qué CA y RN tiene la HU: FAQ comprobará las referencias y la cobertura al guardar.')
    const refs = within(caseItem('CP-01')).getByLabelText('Verifica (CA y RN)')
    await replace(refs, 'CA-09')
    expect(refs).not.toHaveAttribute('aria-invalid')
    expect(saveButton()).toBeEnabled()
    await replace(refs, 'CA9')
    expect(refs).toHaveAttribute('aria-invalid', 'true')
  })
})
