// PA-326 y PA-316 en Iterar (T-56): la cobertura de la suite según `review.uncovered` y `review.coverage_md`
// (distintivo, pestaña Cobertura, descarga de la matriz y resumen del chat) y el selector de versiones de una HU que
// evoluciona con la versión «Jira» del ejemplo del contrato. Datos sintéticos (DEMO-3, qa-demo, af-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { mockSuiteConversation } from '../../mocks/qaSuite.ts'
import { openSuiteForDemo3 } from '../../test/qaFlow.tsx'

const ALL_COVERED = 'Todos los CA cubiertos'
const suitePanel = () => screen.getByRole('complementary', { name: 'Suite de pruebas' })
const tab = (name: string | RegExp) => within(suitePanel()).getByRole('tab', { name })
const downloadButton = () => within(suitePanel()).queryByRole('button', { name: 'Descargar la matriz' })
const coverageTable = () => within(suitePanel()).getByRole('table', { name: 'Qué casos verifican cada CA y cada RN' })

/** El siguiente SSE entrega la suite del ejemplo con la revisión modificada (p. ej. `coverage_md: null`). */
function nextSuiteWith(change: (conversation: ConversationOut) => void) {
  mockServer.use(
    http.get(
      '/api/v1/conversations/:id/events',
      ({ params }) => {
        const run = mockDb.runs.get(String(params.id))
        if (!run) throw new Error('No hay conversación de QA en la API simulada')
        const reviewed = mockSuiteConversation('DEMO-3')
        change(reviewed)
        run.conversation = { ...reviewed, id: run.conversation.id, title: run.conversation.title, state: 'in_review' }
        run.script = []
        return new HttpResponse(`event: review_ready\ndata: ${JSON.stringify(run.conversation)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
      },
      { once: true },
    ),
  )
}

async function iterateOnce() {
  await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
  await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  await screen.findByText(/^Versión 2: añadí el CP-05/)
}

afterEach(() => mockServer.events.removeAllListeners())

describe('Iterar la suite · cobertura (PA-326)', () => {
  it('test_complete_coverage_shows_all_covered_badge_and_download', async () => {
    /** (a) `uncovered` con listas vacías → «Todos los CA cubiertos» y «Descargar la matriz». */
    await openSuiteForDemo3()
    expect(within(suitePanel()).getByText(ALL_COVERED)).toBeInTheDocument()
    expect(screen.getByText(/^Suite lista: 4 casos y todos los CA cubiertos\. Riesgo:/)).toBeInTheDocument()
    await userEvent.click(tab('Cobertura'))
    expect(downloadButton()).toBeInTheDocument()
    expect(downloadButton()).toHaveAccessibleDescription('Descarga el archivo matriz-DEMO-3.md.')
    expect(within(suitePanel()).getByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeInTheDocument()
    expect(coverageTable().querySelectorAll('tr[data-uncovered]')).toHaveLength(0)
  })

  it('test_gaps_show_warning_badge_and_list_uncovered_in_coverage_tab', async () => {
    /** (b) gaps → «1 CA y 1 RN sin caso», sin «Todos los CA cubiertos»; la pestaña lista y marca los no cubiertos. */
    mockDb.forceCoverage = 'gaps'
    await openSuiteForDemo3()
    expect(within(suitePanel()).getByText('1 CA y 1 RN sin caso')).toBeInTheDocument()
    expect(screen.queryByText(ALL_COVERED)).toBeNull()
    expect(screen.queryByText(/todos los CA cubiertos/)).toBeNull()
    // El resumen del chat nombra lo que falta.
    expect(screen.getByText(/^Suite lista: 4 casos\. Sin ningún caso: CA-03, RN-03\. Riesgo:/)).toBeInTheDocument()
    await userEvent.click(tab('Cobertura'))
    expect(within(suitePanel()).getByText('Sin ningún caso:').closest('p')).toHaveTextContent('Sin ningún caso: CA-03, RN-03.')
    const marked = [...coverageTable().querySelectorAll('tr[data-uncovered]')]
    expect(marked.map((row) => row.querySelector('th')?.textContent)).toEqual(['CA-03 · Sin caso', 'RN-03 · Sin caso'])
    expect(within(suitePanel()).queryByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeNull()
    // La matriz se sigue pudiendo descargar.
    expect(downloadButton()).toBeInTheDocument()
  })

  it('test_unknown_coverage_has_no_badge_and_never_says_all_covered', async () => {
    /** (c) `uncovered: null` → sin distintivo; ni «Todos los CA cubiertos» en el panel ni en el chat; nota de «no se pudo comprobar». */
    mockDb.forceCoverage = 'unknown'
    await openSuiteForDemo3()
    expect(screen.queryByText(ALL_COVERED)).toBeNull()
    expect(within(suitePanel()).queryByText(/sin caso$/)).toBeNull()
    expect(screen.getByText('Suite lista: 4 casos. Riesgo: El catálogo puede no responder al renovar.')).toBeInTheDocument()
    expect(screen.queryByText(/todos los CA cubiertos|cobertura sigue completa/)).toBeNull()
    await userEvent.click(tab('Cobertura'))
    expect(within(suitePanel()).getByText(/^No se ha podido comprobar qué CA y RN de la HU quedan sin caso:/)).toBeInTheDocument()
    expect(within(suitePanel()).queryByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeNull()
    expect(coverageTable().querySelectorAll('tr[data-uncovered]')).toHaveLength(0)
  })

  it('test_unknown_coverage_after_iterating_never_says_coverage_still_complete', async () => {
    /** (c) también en la versión siguiente: sin `uncovered`, el resumen no dice «la cobertura sigue completa». */
    mockDb.forceCoverage = 'unknown'
    await openSuiteForDemo3()
    await iterateOnce()
    expect(screen.getByText(/^Versión 2: añadí el CP-05 \(excepción\)\. 5 casos\.$/)).toBeInTheDocument()
    expect(screen.queryByText(/cobertura sigue completa|todos los CA cubiertos/)).toBeNull()
    expect(screen.queryByText(ALL_COVERED)).toBeNull()
  })

  it('test_missing_coverage_md_has_no_download_button', async () => {
    /** (d) `coverage_md: null` → la pestaña Cobertura no ofrece la descarga; el resto sigue igual. */
    nextSuiteWith((conversation) => {
      if (conversation.review) conversation.review.coverage_md = null
    })
    await openSuiteForDemo3()
    expect(within(suitePanel()).getByText(ALL_COVERED)).toBeInTheDocument()
    await userEvent.click(tab('Cobertura'))
    expect(coverageTable()).toBeInTheDocument()
    expect(within(suitePanel()).getByText('Matriz de cobertura CA/RN ↔ CP (RF-24) · se adjunta como matriz-DEMO-3.md')).toBeInTheDocument()
    expect(downloadButton()).toBeNull()
  })

  it('test_uncovered_absent_in_review_is_treated_as_unknown', async () => {
    /** (c) límite: una revisión sin el campo `uncovered` es «no se sabe», no «todo cubierto». */
    nextSuiteWith((conversation) => {
      if (conversation.review) Reflect.deleteProperty(conversation.review, 'uncovered')
    })
    await openSuiteForDemo3()
    expect(screen.queryByText(ALL_COVERED)).toBeNull()
    expect(screen.queryByText(/todos los CA cubiertos/)).toBeNull()
  })

  it('test_earlier_version_has_no_badge_nor_download', async () => {
    /** (e) Al elegir una versión anterior a la de revisión: sin distintivo y sin descarga (su cobertura no se sabe). */
    await openSuiteForDemo3()
    await iterateOnce()
    // La v2 es la de revisión: distintivo y descarga.
    expect(within(suitePanel()).getByText(ALL_COVERED)).toBeInTheDocument()
    await userEvent.click(within(within(suitePanel()).getByRole('group', { name: 'Versiones' })).getByRole('button', { name: 'Versión 1' }))
    expect(tab('Casos (4)')).toHaveAttribute('aria-selected', 'true')
    expect(within(suitePanel()).queryByText(ALL_COVERED)).toBeNull()
    await userEvent.click(tab('Cobertura'))
    expect(downloadButton()).toBeNull()
    expect(within(suitePanel()).getByText(/^No se ha podido comprobar/)).toBeInTheDocument()
    // Al volver a la v2, vuelven el distintivo y la descarga.
    await userEvent.click(within(within(suitePanel()).getByRole('group', { name: 'Versiones' })).getByRole('button', { name: 'Versión 2' }))
    expect(within(suitePanel()).getByText(ALL_COVERED)).toBeInTheDocument()
    await userEvent.click(tab('Cobertura'))
    expect(downloadButton()).toBeInTheDocument()
  })

  it('test_earlier_version_with_gaps_in_review_has_no_warning_badge', async () => {
    /** (e) con huecos en la revisión, la versión anterior tampoco lleva distintivo (ni de aviso). */
    mockDb.forceCoverage = 'gaps'
    await openSuiteForDemo3()
    await iterateOnce()
    // Al iterar, la API simulada cubre el CA que faltaba; RN-03 sigue sin caso (sigue habiendo huecos).
    expect(within(suitePanel()).getByText('1 RN sin caso')).toBeInTheDocument()
    await userEvent.click(within(within(suitePanel()).getByRole('group', { name: 'Versiones' })).getByRole('button', { name: 'Versión 1' }))
    expect(within(suitePanel()).queryByText(/sin caso$/)).toBeNull()
    expect(within(suitePanel()).queryByText(ALL_COVERED)).toBeNull()
  })
})

describe('Iterar la suite · tarjeta del asistente con coverageNote (PA-326)', () => {
  /** Las líneas «Generado con … · N fuentes …» de las tarjetas del chat, en orden. */
  const cards = () => screen.getAllByText(/^Generado con /).map((item) => item.textContent ?? '')

  it('test_assistant_card_complete_says_coverage_validated', async () => {
    await openSuiteForDemo3()
    expect(cards()).toHaveLength(1)
    expect(cards()[0]).toMatch(/^Generado con .+ · 1 fuentes? · cobertura validada$/)
  })

  it('test_assistant_card_gaps_says_what_has_no_case', async () => {
    mockDb.forceCoverage = 'gaps'
    await openSuiteForDemo3()
    expect(cards()[0]).toMatch(/^Generado con .+ · 1 fuentes? · 1 CA y 1 RN sin caso$/)
    expect(screen.queryByText(/cobertura validada/)).toBeNull()
  })

  it('test_assistant_card_unknown_has_no_coverage_note', async () => {
    mockDb.forceCoverage = 'unknown'
    await openSuiteForDemo3()
    expect(cards()[0]).toMatch(/^Generado con .+ · 1 fuentes?$/)
    expect(screen.queryByText(/cobertura validada|sin caso/)).toBeNull()
  })

  it('test_assistant_card_of_an_earlier_version_has_no_note', async () => {
    /** Solo la versión en revisión lleva la coletilla; la v1, tras iterar, ya no. */
    await openSuiteForDemo3()
    await iterateOnce()
    const [v1, v2] = cards()
    expect(v1).toMatch(/^Generado con .+ · 1 fuentes?$/)
    expect(v2).toMatch(/ · cobertura validada$/)
  })

  it('test_assistant_card_of_an_earlier_version_with_gaps_has_no_note', async () => {
    mockDb.forceCoverage = 'gaps'
    await openSuiteForDemo3()
    await iterateOnce()
    const [v1, v2] = cards()
    expect(v1).toMatch(/^Generado con .+ · 1 fuentes?$/)
    // La v2 cubre el CA que faltaba (API simulada); RN-03 sigue sin caso.
    expect(v2).toMatch(/ · 1 RN sin caso$/)
  })
})

describe('Iterar una HU · selector de versiones con la versión «Jira» del ejemplo (PA-316)', () => {
  const panel = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
  const versions = () => within(panel()).getByRole('group', { name: 'Versiones' })
  const criteria = () => within(panel()).getByRole('list', { name: 'Criterios de aceptación' })

  async function openFromList() {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    return screen.findByRole('complementary', { name: 'Propuesta de HU' })
  }

  it('test_version_selector_starts_with_jira', async () => {
    await openFromList()
    const buttons = within(versions()).getAllByRole('button')
    expect(buttons[0]).toHaveTextContent('Jira')
    expect(buttons[0]).toHaveAccessibleName('Versión de Jira')
    expect(buttons.map((button) => button.textContent)).toEqual(['Jira', 'v2'])
  })

  it('test_jira_version_does_not_show_ca_02', async () => {
    await openFromList()
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión de Jira' }))
    expect(within(criteria()).getByText('CA-01')).toBeInTheDocument()
    expect(within(criteria()).queryByText('CA-02')).toBeNull()
  })

  it('test_proposal_version_marks_ca_02_as_new_against_jira', async () => {
    await openFromList()
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión de Jira' }))
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión 2' }))
    const ca02 = within(criteria()).getByText('CA-02').closest('li') as HTMLElement
    expect(within(ca02).getByText('Nueva')).toBeInTheDocument()
    // CA-01 ya está en Jira: no es nuevo.
    const ca01 = within(criteria()).getByText('CA-01').closest('li') as HTMLElement
    expect(within(ca01).queryByText('Nueva')).toBeNull()
  })
})
