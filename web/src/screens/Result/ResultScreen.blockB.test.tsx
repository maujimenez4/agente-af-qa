// Bloque B · Resultado (UI.md §4.7 y §7, «Publicación parcial»; DESIGN-DECISIONS.md §4 bis, «Resultado»):
// `failed_ids` sin `errors`, suite de QA, teclado en las acciones «disponible pronto» y la hora en el pie.
// Solo datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { ResultScreen } from './ResultScreen.tsx'
import { approvedLine, hasResult, outcomeOf } from './resultText.ts'

const SIMULATED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as ConversationOut & { result: PublishOutcome }
const RESULT = SIMULATED.result

function renderResult(result: Partial<PublishOutcome>, extra: Partial<ConversationOut> = {}) {
  const conversation = { ...SIMULATED, ...extra, result: { ...RESULT, ...result } } as ConversationOut & { result: PublishOutcome }
  render(<ResultScreen conversation={conversation} />)
  return screen.getByRole('region', { name: /Publicación simulada|Publicado en Jira|Suite publicada en Jira|Publicada en parte/ })
}

describe('Resultado · en parte solo con `failed_ids` (RNF-13)', () => {
  it('fase 4 «Publicada en parte», «Fallaron: …», operaciones numeradas sin ✓ y ningún mensaje vacío', () => {
    const region = renderResult({ simulated: false, errors: [], failed_ids: ['CP-02', 'estrategia.md'], published_keys: ['DEMO-3'] }, { state: 'approved' })
    expect(screen.getByRole('img', { name: 'Avance: fase 4 de 4, Publicada en parte' })).toBeInTheDocument()
    expect(within(region).getByRole('heading', { level: 2, name: 'Publicada en parte' })).toBeInTheDocument()
    const failed = within(region).getByRole('alert')
    expect(failed).toHaveTextContent('Lo que no se pudo publicar')
    expect(failed).toHaveTextContent('Fallaron: CP-02, estrategia.md')
    expect(within(failed).queryAllByRole('listitem')).toHaveLength(0)
    const approved = within(region).getByRole('list', { name: 'Operaciones aprobadas' })
    expect(within(approved).queryByText('✓')).toBeNull()
    const marks = within(approved).getAllByRole('listitem').map((item) => item.querySelector('[aria-hidden="true"]')?.textContent)
    expect(marks.length).toBeGreaterThan(1)
    expect(marks).toEqual(marks.map((_, index) => String(index + 1)))
    expect(within(region).getByText('Claves en Jira: DEMO-3')).toBeInTheDocument()
  })

  it('con `errors` y `failed_ids` se ven los dos, cada mensaje tal cual', () => {
    const region = renderResult({ simulated: false, errors: ['No se pudo publicar CP-04 (ficticio).', 'No se pudo vincular DEMO-3 con DEMO-2 (ficticio).'], failed_ids: ['CP-04'] }, { state: 'approved' })
    const failed = within(region).getByRole('alert')
    expect(within(failed).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['No se pudo publicar CP-04 (ficticio).', 'No se pudo vincular DEMO-3 con DEMO-2 (ficticio).'])
    expect(failed).toHaveTextContent('Fallaron: CP-04')
  })

  it('publicada sin errores: todas las operaciones con ✓ y sin la caja de fallos', () => {
    const region = renderResult({ simulated: false, published_keys: ['DEMO-3'] }, { state: 'published' })
    const done = within(region).getByRole('list', { name: 'Operaciones hechas en Jira' })
    expect(within(done).getAllByText('✓')).toHaveLength(within(done).getAllByRole('listitem').length)
    expect(within(done).getByText('Añadir a DEMO-3 un comentario con los cambios')).toBeInTheDocument()
    expect(within(region).queryByRole('alert')).toBeNull()
  })

  it('una simulación con `errors` sigue siendo simulada (no escribe en Jira)', () => {
    expect(outcomeOf({ ...RESULT, simulated: true, errors: ['x'], failed_ids: ['CP-01'] })).toBe('simulated')
  })

  it('`hasResult` no abre el Resultado en revisión, generando o con error aunque haya `result`', () => {
    for (const state of ['in_review', 'generating', 'error', 'discarded'] as const) expect(hasResult({ ...SIMULATED, state })).toBe(false)
    expect(hasResult({ ...SIMULATED, state: 'published' })).toBe(true)
  })
})

describe('Resultado · suite de QA (`publish_suite`)', () => {
  it('sin HU en las versiones, lista «Crear 3 subtareas en DEMO-3…» y abre DEMO-3, su HU', () => {
    const plan = [{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '3' }]
    const versions = SIMULATED.versions.map((item) => ({ ...item, artifact: { ...item.artifact, type: 'test_suite', content: { story_jira_key: 'DEMO-3', cases: [], sources: [] } } }))
    const region = renderResult({ simulated: false, plan, published_keys: ['DEMO-3'] }, { state: 'published', flow: 'tests', versions } as unknown as Partial<ConversationOut>)
    const done = within(region).getByRole('list', { name: 'Operaciones hechas en Jira' })
    expect(within(done).getByText('Crear 3 subtareas en DEMO-3 con la etiqueta «caso-prueba»')).toBeInTheDocument()
    expect(within(region).getByRole('button', { name: 'Abrir DEMO-3 en Jira' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('sin claves ni HU en el plan, el botón dice «Abrir en Jira»', () => {
    const region = renderResult({ simulated: false, plan: [{ op: 'publish_suite', project: 'DEMO', story: '', cases: '1' }], published_keys: [] }, { state: 'published' })
    expect(within(region).getByRole('button', { name: 'Abrir en Jira' })).toBeInTheDocument()
    expect(within(region).queryByText(/Claves en Jira/)).toBeNull()
  })
})

describe('Resultado · teclado en las acciones «disponible pronto»', () => {
  it('se llega a cada acción con Tab y ni Intro ni Espacio cambian la pantalla', async () => {
    const region = renderResult({ simulated: false, published_keys: ['DEMO-3'] }, { state: 'published' })
    const names = ['Abrir DEMO-3 en Jira', 'Ver la memoria']
    const before = region.innerHTML
    for (const name of names) {
      const button = within(region).getByRole('button', { name })
      await userEvent.tab()
      while (document.activeElement !== button && document.activeElement !== document.body) await userEvent.tab()
      expect(button).toHaveFocus()
      expect(button).toHaveAttribute('aria-disabled', 'true')
      expect(button).not.toBeDisabled()
      await userEvent.keyboard('{Enter}')
      await userEvent.keyboard(' ')
    }
    expect(region.innerHTML).toBe(before)
  })

  it('en la simulación, cada acción lleva su motivo como descripción accesible', () => {
    const region = renderResult({ simulated: true })
    expect(within(region).getByRole('button', { name: 'Ver el registro de auditoría' })).toHaveAccessibleDescription('El registro de auditoría aún no está en el contrato de la API.')
    expect(within(region).getByRole('button', { name: 'Ir al historial' })).toHaveAccessibleDescription(/solo para administración/)
  })
})

describe('approvedLine · zonas horarias', () => {
  const localTime = (iso: string) => new Intl.DateTimeFormat('es-ES', { hour: '2-digit', minute: '2-digit' }).format(new Date(iso))

  it('el mismo instante con `Z` o con desfase da la misma hora local', () => {
    const utc = approvedLine(2, { ...RESULT, approved_at: '2026-10-02T13:47:00Z' })
    const madrid = approvedLine(2, { ...RESULT, approved_at: '2026-10-02T15:47:00+02:00' })
    const newYork = approvedLine(2, { ...RESULT, approved_at: '2026-10-02T09:47:00-04:00' })
    expect(madrid).toBe(utc)
    expect(newYork).toBe(utc)
    expect(utc).toBe(`Versión 2 aprobada por af-demo a las ${localTime('2026-10-02T13:47:00Z')}`)
  })

  it('una hora sin desfase se lee como hora local, en formato de 24 h', () => {
    expect(approvedLine(3, { ...RESULT, approved_at: '2026-10-02T15:47:00' })).toBe('Versión 3 aprobada por af-demo a las 15:47')
    expect(approvedLine(3, { ...RESULT, approved_at: '2026-10-02T00:05:00' })).toBe('Versión 3 aprobada por af-demo a las 00:05')
  })

  it('un instante que cambia de día según la zona sigue dando solo la hora', () => {
    expect(approvedLine(1, { ...RESULT, approved_at: '2026-12-31T23:30:00-11:00' })).toMatch(/^Versión 1 aprobada por af-demo a las \d{2}:\d{2}$/)
  })

  it.each(['', '2026-13-45T99:99:99Z', 'mañana'])('sin hora si la fecha no se puede leer (%j)', (approvedAt) => {
    expect(approvedLine(1, { ...RESULT, approved_at: approvedAt })).toBe('Versión 1 aprobada por af-demo')
  })

  it('el usuario se pinta tal cual, aunque traiga HTML', () => {
    render(<ResultScreen conversation={{ ...SIMULATED, result: { ...RESULT, approved_by: '<i>usuario-ficticio</i>' } }} />)
    const line = screen.getByText(/aprobada por <i>usuario-ficticio<\/i>/)
    expect(line.querySelector('i')).toBeNull()
  })
})
