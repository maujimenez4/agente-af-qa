// Bloque B · recibo de aprobación (UI.md §4.6, contrato §5.2-§5.5; DESIGN-DECISIONS.md §4 bis): teclado,
// `aria-live`, la huella del último payload, nada enviado sin todas las casillas y una conversación de QA.
// Solo datos sintéticos (proyecto DEMO, usuarios demo, huellas «huella-ficticia-…»).
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../../api/client.ts'
import examples from '../../api/examples.json'
import type { ApproveIn, ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { FINGERPRINT_MISMATCH } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { ReceiptScreen } from './ReceiptScreen.tsx'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const REVIEW = EXAMPLE.review as NonNullable<ConversationOut['review']>
const FIRST_ID = EXAMPLE.id
const SECOND_ID = '0d6c1e7a-1111-4b2a-9c3d-ficticio00002'

const operations = () => screen.getByRole('group', { name: /Qué se hará en Jira/ })
const approveButton = () => screen.getByRole('button', { name: 'Aprobar y publicar' })
const checkboxes = () => within(operations()).getAllByRole('checkbox')
/** El contador con N operaciones del plan (el plan del ejemplo puede crecer: no se fija el número). */
const counterText = (checked: number) => `${checked} de ${checkboxes().length} revisadas`

function recordApprovals(): ApproveIn[] {
  const bodies: ApproveIn[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/approve')) bodies.push((await request.clone().json()) as ApproveIn)
  })
  return bodies
}

async function openFromList(name: RegExp) {
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name }))
  const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
  return screen.findByRole('region', { name: /lista para revisar/ })
}

async function openReceipt() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  return openFromList(/Evolucionar DEMO-3/)
}

afterEach(() => mockServer.events.removeAllListeners())

describe('Recibo · teclado y foco (UI.md §4.6)', () => {
  it('con Tab se recorren las casillas y luego Descartar y Volver; Aprobar desactivado no recibe el foco', async () => {
    await openReceipt()
    const boxes = checkboxes()
    expect(boxes.length).toBeGreaterThan(1)
    ;(boxes[0] as HTMLElement).focus()
    for (const box of boxes.slice(1)) {
      await userEvent.tab()
      expect(box).toHaveFocus()
    }
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Descartar' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Volver a la propuesta' })).toHaveFocus()
    await userEvent.tab()
    expect(approveButton()).not.toHaveFocus()
  })

  it('con todas marcadas por teclado, Tab llega a Aprobar y publicar e Intro aprueba', async () => {
    const bodies = recordApprovals()
    await openReceipt()
    for (const box of checkboxes()) {
      box.focus()
      await userEvent.keyboard(' ')
    }
    screen.getByRole('button', { name: 'Volver a la propuesta' }).focus()
    await userEvent.tab()
    expect(approveButton()).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByText(/Publicación simulada/, undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(bodies).toEqual([{ fingerprint: REVIEW.fingerprint }])
  })

  it('la confirmación del descarte se cancela con «Seguir revisando» sin perder las casillas marcadas', async () => {
    await openReceipt()
    await userEvent.click(checkboxes()[0] as HTMLElement)
    await userEvent.click(screen.getByRole('button', { name: 'Descartar' }))
    await userEvent.click(within(screen.getByRole('group', { name: 'Confirmar el descarte' })).getByRole('button', { name: 'Seguir revisando' }))
    expect(screen.queryByRole('group', { name: 'Confirmar el descarte' })).toBeNull()
    expect(within(operations()).getByText(counterText(1))).toBeInTheDocument()
  })
})

describe('Recibo · contador accesible (DESIGN-DECISIONS.md §4 bis)', () => {
  it('el contador está en una región `aria-live="polite"` y cambia al marcar y desmarcar', async () => {
    await openReceipt()
    const counter = within(operations()).getByText(counterText(0))
    expect(counter).toHaveAttribute('aria-live', 'polite')
    const boxes = checkboxes()
    await userEvent.click(boxes.at(-1) as HTMLElement)
    expect(counter).toHaveTextContent(counterText(1))
    for (const box of boxes.slice(0, -1)) await userEvent.click(box)
    expect(counter).toHaveTextContent('Todo revisado')
    await userEvent.click(boxes[0] as HTMLElement)
    // El mismo nodo se actualiza (no se sustituye): así el lector de pantalla lo anuncia.
    expect(counter).toHaveTextContent(counterText(boxes.length - 1))
    expect(counter).toBeInTheDocument()
  })
})

describe('Recibo · nada se envía sin todas las casillas (contrato §5.5)', () => {
  it('con una casilla sin marcar, ni el clic, ni Intro, ni Espacio envían POST /approve', async () => {
    const bodies = recordApprovals()
    await openReceipt()
    const [first, second] = checkboxes() as [HTMLElement, HTMLElement]
    await userEvent.click(first)
    expect(approveButton()).toBeDisabled()

    await userEvent.click(approveButton())
    fireEvent.click(approveButton())
    // Desactivado de verdad (`disabled` nativo): no recibe el foco, así que Intro no llega a él.
    approveButton().focus()
    expect(approveButton()).not.toHaveFocus()
    fireEvent.keyDown(approveButton(), { key: 'Enter', code: 'Enter' })
    // Intro sobre la casilla pendiente no la marca (solo Espacio) ni envía nada.
    second.focus()
    await userEvent.keyboard('{Enter}')
    expect(second).not.toBeChecked()
    fireEvent.submit(operations())

    expect(screen.queryByText('Aprobando y publicando…')).toBeNull()
    expect(bodies).toEqual([])
  })

  it('tras desmarcar una casilla que ya estaba marcada, tampoco se envía nada', async () => {
    const bodies = recordApprovals()
    await openReceipt()
    for (const box of checkboxes()) await userEvent.click(box)
    expect(approveButton()).toBeEnabled()
    const first = checkboxes()[0] as HTMLElement
    first.focus()
    await userEvent.keyboard(' ')
    await userEvent.keyboard('{Enter}')
    fireEvent.click(approveButton())
    expect(bodies).toEqual([])
  })
})

describe('Recibo · la huella (contrato §5.4)', () => {
  it('tras una huella rechazada, el segundo intento envía la huella del último payload, no la primera', async () => {
    const bodies = recordApprovals()
    await openReceipt()
    // Otra versión en el servidor: la huella de la pantalla ya no casa y vuelve `review_ready` con `error`.
    const run = mockDb.runs.get(FIRST_ID)
    if (!run?.conversation.review) throw new Error('El recibo necesita la revisión simulada')
    run.conversation = { ...run.conversation, review: { ...run.conversation.review, fingerprint: 'huella-ficticia-nueva' } }

    for (const box of checkboxes()) await userEvent.click(box)
    await userEvent.click(approveButton())
    expect(await screen.findByRole('alert')).toHaveTextContent(FINGERPRINT_MISMATCH)

    for (const box of checkboxes()) await userEvent.click(box)
    await userEvent.click(approveButton())
    expect(await screen.findByText(/Publicación simulada/, undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(bodies).toEqual([{ fingerprint: REVIEW.fingerprint }, { fingerprint: 'huella-ficticia-nueva' }])
  })

  it('la huella de una conversación no pasa a otra, ni tampoco sus casillas', async () => {
    mockDb.conversations.push({
      ...mockDb.conversations[0]!,
      thread_id: SECOND_ID,
      origin_key: 'DEMO-4',
      title: 'Evolucionar DEMO-4',
    })
    mockDb.runs.set(SECOND_ID, {
      conversation: { ...EXAMPLE, id: SECOND_ID, title: 'Evolucionar DEMO-4', review: { ...REVIEW, fingerprint: 'huella-ficticia-segunda' } },
      script: [],
    })
    const bodies = recordApprovals()
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)

    await openFromList(/Evolucionar DEMO-3/)
    for (const box of checkboxes()) await userEvent.click(box)
    expect(within(operations()).getByText('Todo revisado')).toBeInTheDocument()

    await openFromList(/Evolucionar DEMO-4/)
    expect(within(operations()).getByText(counterText(0))).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
    for (const box of checkboxes()) await userEvent.click(box)
    await userEvent.click(approveButton())
    expect(await screen.findByText(/Publicación simulada/, undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(bodies).toEqual([{ fingerprint: 'huella-ficticia-segunda' }])
  })

  // Fija un fallo ya corregido al cerrar el bloque B. Antes: src/app/AppShell.tsx:179 (`key={view.conversation.id}`) con src/screens/Iterate/IterateScreen.tsx:68
  // (`useState(initial)`): al reabrir desde la lista la conversación que ya está en Iterar, GET /conversations/{id}
  // trae la huella nueva, pero Iterar no se vuelve a montar y sigue con el payload anterior; *Revisar y aprobar*
  // abre el recibo con la huella vieja y POST /approve la envía (contrato §5.4: «la del último interrupt»).
  it('al volver a la propuesta y reabrir la misma conversación, se envía la huella que trae la conversación entonces', async () => {
    const bodies = recordApprovals()
    await openReceipt()
    await userEvent.click(screen.getByRole('button', { name: 'Volver a la propuesta' }))
    // Una versión nueva mientras tanto (p. ej. otra pestaña): la API devuelve otra huella.
    mockServer.use(
      http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, review: { ...REVIEW, fingerprint: 'huella-ficticia-actual' } })),
      http.post('/api/v1/conversations/:id/approve', () =>
        HttpResponse.json({ error: { code: 'approval_rejected', message: 'Aprobación rechazada (mensaje ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    const list = screen.getByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(within(list).getByRole('button', { name: /Evolucionar DEMO-3/ }))
    const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
    await screen.findByRole('region', { name: /lista para revisar/ })
    for (const box of checkboxes()) await userEvent.click(box)
    await userEvent.click(approveButton())
    await screen.findByRole('alert')
    expect(bodies).toEqual([{ fingerprint: 'huella-ficticia-actual' }])
  })
})

describe('Recibo · la huella al cambiar de conversación', () => {
  it('ir a otra conversación y volver abre el recibo con la huella que trae la API en ese momento', async () => {
    mockDb.conversations.push({ ...mockDb.conversations[0]!, thread_id: SECOND_ID, origin_key: 'DEMO-4', title: 'Evolucionar DEMO-4' })
    mockDb.runs.set(SECOND_ID, { conversation: { ...EXAMPLE, id: SECOND_ID, title: 'Evolucionar DEMO-4', review: { ...REVIEW, fingerprint: 'huella-ficticia-segunda' } }, script: [] })
    const bodies = recordApprovals()
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await openFromList(/Evolucionar DEMO-3/)
    await openFromList(/Evolucionar DEMO-4/)
    // Mientras tanto, DEMO-3 tiene una versión nueva en el servidor.
    const run = mockDb.runs.get(FIRST_ID)
    if (!run?.conversation.review) throw new Error('El recibo necesita la revisión simulada')
    run.conversation = { ...run.conversation, review: { ...run.conversation.review, fingerprint: 'huella-ficticia-actual' } }
    await openFromList(/Evolucionar DEMO-3/)
    for (const box of checkboxes()) await userEvent.click(box)
    await userEvent.click(approveButton())
    expect(await screen.findByText(/Publicación simulada/, undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(bodies).toEqual([{ fingerprint: 'huella-ficticia-actual' }])
  })
})

describe('Recibo · otros caminos', () => {
  it('con `review.error` en el payload de entrada se muestra «No se aprobó» con el motivo tal cual', () => {
    render(
      <ReceiptScreen
        conversation={{ ...EXAMPLE, review: { ...REVIEW, error: 'Motivo ficticio <b>sin HTML</b>.' } }}
        onBack={vi.fn()}
        onDone={vi.fn()}
        onDiscarded={vi.fn()}
        onRestart={vi.fn()}
      />,
    )
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('No se aprobó')
    expect(alert).toHaveTextContent('Motivo ficticio <b>sin HTML</b>.')
    expect(alert.querySelector('b b')).toBeNull()
  })

  it('«Volver a la propuesta» entrega la conversación tal como está y no llama a nada más', async () => {
    const onBack = vi.fn()
    const onDone = vi.fn()
    render(<ReceiptScreen conversation={EXAMPLE} onBack={onBack} onDone={onDone} onDiscarded={vi.fn()} onRestart={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Volver a la propuesta' }))
    expect(onBack).toHaveBeenCalledWith(EXAMPLE)
    expect(onDone).not.toHaveBeenCalled()
  })

  it('si el descarte falla, se muestra el error y no se sale del recibo', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    mockServer.use(
      http.post('/api/v1/conversations/:id/discard', () =>
        HttpResponse.json({ error: { code: 'not_in_review', message: 'No se puede descartar ahora (mensaje ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    const onDiscarded = vi.fn()
    render(<ReceiptScreen conversation={EXAMPLE} onBack={vi.fn()} onDone={vi.fn()} onDiscarded={onDiscarded} onRestart={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Descartar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No se puede descartar ahora (mensaje ficticio).')
    expect(onDiscarded).not.toHaveBeenCalled()
    expect(screen.getByRole('region', { name: /lista para revisar/ })).toBeInTheDocument()
  })
})

describe('Recibo · conversación de QA (contrato §5.2, `publish_suite`)', () => {
  const suite = {
    story_jira_key: 'DEMO-3',
    strategy_md: '# Estrategia ficticia',
    cases: [],
    sources: [
      { kind: 'jira', ref: 'DEMO-3', title: 'HU ficticia' },
      { kind: 'doc', ref: 'doc-ficticio', title: 'Documento ficticio' },
      { kind: 'doc', ref: 'doc-ficticio-2', title: 'Otro documento ficticio' },
    ],
    risks: [],
    dependencies: [],
    impact_areas: [],
    synthetic_data: [],
  }
  const QA = {
    ...EXAMPLE,
    flow: 'tests',
    mode: 'qa',
    title: 'Preparar pruebas de DEMO-3',
    jira_baseline: null,
    review: {
      ...REVIEW,
      version: 1,
      fingerprint: 'huella-ficticia-qa',
      impact: null,
      artifact: { ...REVIEW.artifact, type: 'test_suite', version: 1, content: suite },
      plan: [{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '3' }],
    },
  } as unknown as ConversationOut

  it('una casilla «Publicar 3 casos de prueba en DEMO-3» con su detalle y el aviso con las fuentes de la suite', async () => {
    render(<ReceiptScreen conversation={QA} onBack={vi.fn()} onDone={vi.fn()} onDiscarded={vi.fn()} onRestart={vi.fn()} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Versión 1 lista para revisar' })).toBeInTheDocument()
    const boxes = checkboxes()
    expect(boxes).toHaveLength(1)
    expect(within(operations()).getByText('Publicar 3 casos de prueba en DEMO-3')).toBeInTheDocument()
    expect(within(operations()).getByText('Como subtareas con la etiqueta «caso-prueba».')).toBeInTheDocument()
    expect(screen.getByText('Generado con IA a partir de 3 fuentes. Revisa cada operación antes de aprobar.')).toBeInTheDocument()
    await userEvent.click(boxes[0] as HTMLElement)
    expect(within(operations()).getByText('Todo revisado')).toBeInTheDocument()
    expect(approveButton()).toBeEnabled()
  })

  it('aprobar la suite envía su huella exacta y entrega el resultado', async () => {
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    const done = { ...QA, state: 'simulated', review: null, result: { simulated: true, plan: QA.review?.plan ?? [], approved_by: 'qa-demo', approved_at: '2026-10-02T10:30:00Z', published_keys: [], errors: [], failed_ids: [] } }
    const bodies: ApproveIn[] = []
    mockServer.use(
      http.post('/api/v1/conversations/:id/approve', async ({ request }) => {
        bodies.push((await request.json()) as ApproveIn)
        return HttpResponse.json(done, { status: 202 })
      }),
    )
    const onDone = vi.fn()
    render(<ReceiptScreen conversation={QA} onBack={vi.fn()} onDone={onDone} onDiscarded={vi.fn()} onRestart={vi.fn()} />)
    await userEvent.click(checkboxes()[0] as HTMLElement)
    await userEvent.click(approveButton())
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(bodies).toEqual([{ fingerprint: 'huella-ficticia-qa' }])
    expect((onDone.mock.calls[0]?.[0] as ConversationOut).state).toBe('simulated')
  })
})

describe('Recibo · fallo de la publicación ya en marcha (UI.md §7, `publish_failed`)', () => {
  const FAILED_ERROR = { code: 'publish_failed', message: 'No consta una aprobación humana vigente (mensaje ficticio).', retry_after: null }
  const failedConversation = { ...EXAMPLE, state: 'error', review: null, error: FAILED_ERROR } as unknown as ConversationOut

  function failingStream() {
    return http.get(
      '/api/v1/conversations/:id/events',
      () => new HttpResponse(`event: error\ndata: ${JSON.stringify(failedConversation)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }),
    )
  }

  it('con la conversación en `state=error`, lee el estado y sale con `onDone`, sin un segundo POST /approve', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    mockDb.runs.set(FIRST_ID, { conversation: structuredClone(EXAMPLE), script: [] })
    setCsrfToken('csrf-ficticio')
    const bodies = recordApprovals()
    mockServer.use(failingStream())
    const onDone = vi.fn()
    render(<ReceiptScreen conversation={EXAMPLE} onBack={vi.fn()} onDone={onDone} onDiscarded={vi.fn()} onRestart={vi.fn()} />)
    for (const box of checkboxes()) await userEvent.click(box)
    // La lectura del estado tras el fallo ya ve la conversación en error.
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(failedConversation)))
    await userEvent.click(approveButton())
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect((onDone.mock.calls[0]?.[0] as ConversationOut).state).toBe('error')
    expect(bodies).toHaveLength(1)
  })

  it('si el fallo no deja la conversación en error, muestra la tarjeta y *Aprobar* queda desactivado', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    mockDb.runs.set(FIRST_ID, { conversation: structuredClone(EXAMPLE), script: [] })
    setCsrfToken('csrf-ficticio')
    const bodies = recordApprovals()
    mockServer.use(
      http.get(
        '/api/v1/conversations/:id/events',
        () => new HttpResponse(`event: error\ndata: ${JSON.stringify({ error: FAILED_ERROR })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }),
      ),
    )
    render(<ReceiptScreen conversation={EXAMPLE} onBack={vi.fn()} onDone={vi.fn()} onDiscarded={vi.fn()} onRestart={vi.fn()} />)
    for (const box of checkboxes()) await userEvent.click(box)
    await userEvent.click(approveButton())
    expect(await screen.findByRole('alert')).toHaveTextContent(FAILED_ERROR.message)
    expect(approveButton()).toBeDisabled()
    fireEvent.click(approveButton())
    expect(bodies).toHaveLength(1)
  })
})
