// QA 2 · Generando (UI.md §6.2): mismo patrón que Mixta 2b con los textos de la suite, y el titular
// «Suite lista · Versión 1 · N casos». Datos sintéticos (DEMO-3, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { mockSuiteConversation } from '../../mocks/qaSuite.ts'
import { openEventStream } from '../../test/sse.ts'
import { GeneratingScreen } from './GeneratingScreen.tsx'
import { qaHeaderTitle, readyHeadline } from './headline.ts'

const TAKEN = examples['POST /api/v1/qa/handoffs/{handoff_id}/take 202'] as unknown as ConversationOut
const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const SUITE = mockSuiteConversation(EXAMPLE, 'DEMO-3')

describe('readyHeadline en QA', () => {
  it('«Suite lista · Versión N · 4 casos»', () => {
    expect(readyHeadline(SUITE)).toBe(`Suite lista · Versión ${SUITE.review?.version ?? 1} · 4 casos`)
  })

  it('una suite de un caso dice «1 caso»', () => {
    const one = structuredClone(SUITE)
    const content = one.review?.artifact.content
    if (content && 'cases' in content) content.cases = content.cases.slice(0, 1)
    expect(readyHeadline(one)).toMatch(/· 1 caso$/)
  })

  it('una HU sigue diciendo «Propuesta lista»', () => {
    expect(readyHeadline(EXAMPLE)).toMatch(/^Propuesta lista · Versión/)
  })
})

describe('qaHeaderTitle', () => {
  it('«Preparar pruebas de DEMO-3» → «Pruebas de DEMO-3»; otro título, igual', () => {
    expect(qaHeaderTitle('Preparar pruebas de DEMO-3')).toBe('Pruebas de DEMO-3')
    expect(qaHeaderTitle('Pruebas de DEMO-3')).toBe('Pruebas de DEMO-3')
  })
})

describe('QA 2 · Generando', () => {
  it('generando: textos de la suite en el evento, el titular, el compositor y el panel', async () => {
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    render(<GeneratingScreen conversation={TAKEN} onReady={vi.fn()} onRetry={vi.fn()} />)
    expect(screen.getByText(/^Generar la suite ·/)).toHaveTextContent('Generar la suite · Preparar pruebas de DEMO-3')
    expect(await screen.findByText('Generando la suite…')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Espera a la suite para pedir cambios' })).toBeDisabled()
    const panel = screen.getByRole('complementary', { name: 'Suite de pruebas' })
    expect(screen.getByRole('heading', { level: 1, name: 'Pruebas de DEMO-3' })).toBeInTheDocument()
    expect(within(panel).getByText('La suite aparece aquí cuando la cobertura está comprobada.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Detener la generación' })).toBeEnabled()
    // Las etiquetas de los pasos son de la API, tal cual (PA-307); fuera de ellas, nada habla de «propuesta» (PA-327).
    const steps = screen.getByRole('status')
    const elsewhere = screen.queryAllByText(/propuesta/i).filter((element) => !steps.contains(element))
    expect(elsewhere).toEqual([])
  })

  it('al recoger una HU, la generación termina en «Suite lista · … · 4 casos» con *Ver la suite*', async () => {
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    render(<App />)
    const pending = await screen.findByRole('region', { name: 'Pendientes de pruebas' })
    await userEvent.click(await within(pending).findByRole('button', { name: 'Recoger DEMO-3' }))
    expect(await screen.findByRole('heading', { name: /^Suite lista · Versión \d+ · 4 casos$/ })).toBeInTheDocument()
    const panel = screen.getByRole('complementary', { name: 'Suite de pruebas' })
    expect(within(panel).getByText('La suite está lista. Ábrela para revisarla.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Ver la suite' }))
    // QA 3 · Iterar la suite.
    const suitePanel = await screen.findByRole('complementary', { name: 'Suite de pruebas' })
    expect(within(suitePanel).getByRole('tab', { name: 'Casos (4)' })).toHaveAttribute('aria-selected', 'true')
  })

  it('el MSW deja la conversación de QA en revisión con la suite y `publish_suite` en el plan', async () => {
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    render(<App />)
    const pending = await screen.findByRole('region', { name: 'Pendientes de pruebas' })
    await userEvent.click(await within(pending).findByRole('button', { name: 'Recoger DEMO-3' }))
    await screen.findByRole('button', { name: 'Ver la suite' })
    const run = [...mockDb.runs.values()].find((item) => item.conversation.mode === 'qa')
    expect(run?.conversation.state).toBe('in_review')
    expect(run?.conversation.review?.artifact.type).toBe('test_suite')
    expect(run?.conversation.review?.plan).toEqual([{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '4' }])
  })
})
