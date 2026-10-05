// Recibo de aprobación (UI.md §4.6, contrato §5): casillas por operación, huella exacta y rechazos.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ApproveIn, ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { FINGERPRINT_MISMATCH } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { aiNotice, receiptOperations, reviewedCounter } from './receiptText.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const FINGERPRINT = EXAMPLE.review?.fingerprint ?? ''

async function openReceipt() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
  return screen.findByRole('region', { name: /lista para revisar/ })
}

const operations = () => screen.getByRole('group', { name: /Qué se hará en Jira/ })
const approveButton = () => screen.getByRole('button', { name: 'Aprobar y publicar' })

async function checkAll() {
  for (const box of within(operations()).getAllByRole('checkbox')) await userEvent.click(box)
}

afterEach(() => mockServer.events.removeAllListeners())

describe('textos del recibo', () => {
  const impact = {
    diffs: [
      { field: 'acceptance_criteria.CA-02', before: null, after: 'x' },
      { field: 'description', before: 'a', after: 'b' },
      { field: 'business_rules.RN-03', before: 'a', after: null },
    ],
    affected: [{ jira_key: 'DEMO-2', reason: 'Comparte la regla de reservas', kind: 'rule' as const }],
    regression_notes: [],
  }

  it('una operación por elemento del plan, con su detalle', () => {
    const ops = receiptOperations(
      [
        { op: 'update_story', project: 'DEMO', key: 'DEMO-3' },
        { op: 'link', from: 'DEMO-3', to: 'DEMO-2', type: 'relates to' },
        { op: 'link', from: 'DEMO-3', to: 'DEMO-9', type: 'relates to' },
      ],
      3,
      'Renovar un préstamo',
      impact,
    )
    expect(ops.map(({ label, detail }) => [label, detail])).toEqual([
      ['Actualizar DEMO-3 con la versión 3', 'Cambia: CA-02 (nuevo), Descripción, RN-03 (se quita).'],
      ['Vincular DEMO-3 con DEMO-2', 'Comparte la regla de reservas.'],
      ['Vincular DEMO-3 con DEMO-9', 'Vínculo «relates to».'],
    ])
    expect(new Set(ops.map((op) => op.id)).size).toBe(3)
  })

  it.each([
    [{ op: 'create_story', project: 'DEMO', epic: 'DEMO-1' }, 'Crear la HU en la épica DEMO-1'],
    [{ op: 'create_story', project: 'DEMO', epic: '' }, 'Crear la HU en el proyecto DEMO'],
    [{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '1' }, 'Publicar 1 caso de prueba en DEMO-3'],
    [{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '4' }, 'Publicar 4 casos de prueba en DEMO-3'],
    [{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: 'x' }, 'Publicar los casos de prueba en DEMO-3'],
    [{ op: 'otra_cosa', key: 'DEMO-3' }, 'Operación «otra_cosa»'],
  ])('%j → «%s»', (item, label) => {
    expect(receiptOperations([item], 1, 'Título', null)[0]?.label).toBe(label)
  })

  it('una actualización sin diffs muestra el título de la HU', () => {
    expect(receiptOperations([{ op: 'update_story', project: 'DEMO', key: 'DEMO-3' }], 1, 'Renovar un préstamo', null)[0]?.detail).toBe('Renovar un préstamo')
  })

  it('el contador y el aviso de IA', () => {
    expect(reviewedCounter(0, 2)).toBe('0 de 2 revisadas')
    expect(reviewedCounter(2, 2)).toBe('Todo revisado')
    expect(aiNotice(1)).toBe('Generado con IA a partir de 1 fuente. Revisa cada operación antes de aprobar.')
    expect(aiNotice(5)).toMatch(/^Generado con IA a partir de 5 fuentes\./)
  })
})

describe('Recibo de aprobación (UI.md §4.6)', () => {
  it('muestra la fase 3, una casilla por operación y *Aprobar y publicar* desactivado hasta marcarlas todas', async () => {
    await openReceipt()
    expect(screen.getByRole('img', { name: 'Avance: fase 3 de 4, Revisión' })).toBeInTheDocument()
    const boxes = within(operations()).getAllByRole('checkbox')
    expect(boxes.map((box) => box.closest('label')?.querySelector('b')?.textContent)).toEqual(['Actualizar DEMO-3 con la versión 2', 'Vincular DEMO-3 con DEMO-2'])
    expect(within(operations()).getByText('Cambia: CA-02 (nuevo).')).toBeInTheDocument()
    expect(within(operations()).getByText('Comparte la regla de reservas.')).toBeInTheDocument()
    expect(within(operations()).getByText('0 de 2 revisadas')).toBeInTheDocument()
    expect(screen.getByText('Generado con IA a partir de 2 fuentes. Revisa cada operación antes de aprobar.')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()

    const first = boxes[0] as HTMLElement
    await userEvent.click(first)
    expect(within(operations()).getByText('1 de 2 revisadas')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
    await userEvent.click(boxes[1] as HTMLElement)
    expect(within(operations()).getByText('Todo revisado')).toBeInTheDocument()
    expect(approveButton()).toBeEnabled()
    await userEvent.click(first)
    expect(approveButton()).toBeDisabled()
  })

  it('las casillas se marcan con el teclado', async () => {
    await openReceipt()
    for (const box of within(operations()).getAllByRole('checkbox')) {
      box.focus()
      await userEvent.keyboard(' ')
    }
    expect(approveButton()).toBeEnabled()
  })

  it('aprobar envía exactamente la huella del último payload y termina en «Publicación simulada»', async () => {
    const bodies: ApproveIn[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/approve')) bodies.push((await request.clone().json()) as ApproveIn)
    })
    await openReceipt()
    await checkAll()
    await userEvent.click(approveButton())
    expect(await screen.findByText(/Publicación simulada/)).toBeInTheDocument()
    expect(bodies).toEqual([{ fingerprint: FINGERPRINT }])
  })

  it('una huella que no casa vuelve al recibo con el motivo tal cual y obliga a revisar de nuevo', async () => {
    await openReceipt()
    // Otra versión en el servidor: la huella que tiene la pantalla ya no es la vigente.
    const run = [...mockDb.runs.values()].at(-1)
    if (run?.conversation.review) run.conversation = { ...run.conversation, review: { ...run.conversation.review, fingerprint: 'huella-ficticia-nueva' } }
    await checkAll()
    await userEvent.click(approveButton())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No se aprobó')
    expect(alert).toHaveTextContent(FINGERPRINT_MISMATCH)
    expect(within(operations()).getByText('0 de 2 revisadas')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
  })

  it('409 approval_rejected: tarjeta con «Empezar de nuevo», que vuelve a Inicio', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/approve', () =>
        HttpResponse.json({ error: { code: 'approval_rejected', message: 'La aprobación no corresponde a la versión revisada; empieza de nuevo.', retry_after: null } }, { status: 409 }),
      ),
    )
    await openReceipt()
    await checkAll()
    await userEvent.click(approveButton())
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Aprobación rechazada' })).toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Empezar de nuevo' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('409 not_in_review: «Actualizar» lee el estado y, si ya no está en revisión, sale del recibo', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/approve', () =>
        HttpResponse.json({ error: { code: 'not_in_review', message: 'La conversación no está en revisión (ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    await openReceipt()
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, state: 'discarded', review: null })))
    await checkAll()
    await userEvent.click(approveButton())
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Actualizar' }))
    expect(await screen.findByText(/Propuesta descartada/)).toBeInTheDocument()
  })

  it('«Volver a la propuesta» vuelve a Iterar sin aprobar nada', async () => {
    let approvals = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/approve')) approvals += 1
    })
    await openReceipt()
    await userEvent.click(screen.getByRole('button', { name: 'Volver a la propuesta' }))
    expect(await screen.findByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
    expect(approvals).toBe(0)
  })

  it('*Descartar* pide confirmación y vuelve a Inicio', async () => {
    await openReceipt()
    await userEvent.click(screen.getByRole('button', { name: 'Descartar' }))
    await userEvent.click(within(screen.getByRole('group', { name: 'Confirmar el descarte' })).getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('sin operaciones en el plan no se puede aprobar', async () => {
    const review = EXAMPLE.review
    if (!review) throw new Error('El ejemplo necesita review')
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, review: { ...review, plan: [] } })))
    await openReceipt()
    expect(screen.getByText('Esta propuesta no tiene operaciones de Jira que aprobar.')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
  })

  it('el historial lista las versiones con su modelo', async () => {
    await openReceipt()
    const history = screen.getByRole('list', { name: 'Versiones de la propuesta' })
    expect(within(history).getByText('Versión 2 generada')).toBeInTheDocument()
    expect(within(history).getByText('Versión de partida desde Jira')).toBeInTheDocument()
    expect(within(history).getAllByText(/local · /).length).toBeGreaterThan(0)
  })

  it('mientras publica no se puede volver, descartar ni aprobar otra vez', async () => {
    mockDb.stepDelayMs = 300
    await openReceipt()
    await checkAll()
    await userEvent.click(approveButton())
    expect(await screen.findByText('Aprobando y publicando…')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Volver a la propuesta' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Descartar' })).toBeDisabled()
    await waitFor(() => expect(screen.getByText(/Publicación simulada/)).toBeInTheDocument(), { timeout: 4000 })
  })
})
