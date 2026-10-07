// PA-325 · Resultado en la app: «Claves en Jira: …» enlaza cada clave publicada con `SettingsOut.jira_browse_url`
// (siempre por safeHref); con `null`, texto. HU (af-demo) y suite de QA (qa-demo) contra la API simulada.
// Datos sintéticos (DEMO-3, DEMO-21…, prefijo del ejemplo de GET /settings).
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openSuiteInReview } from '../../test/qaFlow.tsx'

const BROWSE = 'https://villaficticia-ejemplo.atlassian.net/browse/'

const isSettings = (request: Request) => request.method === 'GET' && new URL(request.url).pathname === '/api/v1/settings'

/**
 * PA-127: GET /settings retenido desde `hold()`. `settle()` lo suelta y espera a que todas las peticiones retenidas
 * (también la del Resultado) tengan respuesta: lo que se comprueba después ya es con ese `jira_browse_url`.
 */
function holdSettings(): { hold: () => void; settle: () => Promise<void> } {
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let asked = 0
  let answered = 0
  return {
    hold: () => {
      mockServer.events.on('request:start', ({ request }) => {
        if (isSettings(request)) asked += 1
      })
      mockServer.events.on('response:mocked', ({ request }) => {
        if (isSettings(request)) answered += 1
      })
      mockServer.use(
        http.get('/api/v1/settings', async () => {
          await gate
          // Sin respuesta: la da la API simulada con `mockDb.settings`.
          return undefined
        }),
      )
    },
    settle: async () => {
      // La del Resultado sale al pintarse, pero llega a MSW unas promesas después.
      await expect.poll(() => asked).toBeGreaterThan(0)
      release()
      await expect.poll(() => answered).toBe(asked)
      // La respuesta llega en una promesa: se deja que React la aplique.
      await act(async () => {})
    },
  }
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

/** HU: abrir «Evolucionar DEMO-3», revisar y aprobar; devuelve la región del resultado. */
async function approveStory(regionName: string | RegExp, beforeApprove?: () => void) {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
  const receipt = await screen.findByRole('region', { name: /^Versión \d+ lista para revisar$/ })
  for (const box of within(receipt).getAllByRole('checkbox')) await userEvent.click(box)
  beforeApprove?.()
  await userEvent.click(within(receipt).getByRole('button', { name: 'Aprobar y publicar' }))
  return screen.findByRole('region', { name: regionName })
}

/** QA: la suite de DEMO-3 ya en revisión; revisar y aprobar; devuelve la región del resultado. */
async function approveSuite(regionName: string | RegExp, beforeApprove?: () => void) {
  await openSuiteInReview()
  await userEvent.click(await screen.findByRole('button', { name: 'Revisar y aprobar' }))
  const receipt = await screen.findByRole('region', { name: 'Suite, versión 1 lista para revisar' })
  await userEvent.click(within(receipt).getAllByRole('checkbox')[0] as HTMLElement)
  beforeApprove?.()
  await userEvent.click(within(receipt).getByRole('button', { name: 'Aprobar y publicar' }))
  return screen.findByRole('region', { name: regionName })
}

/** El párrafo «Claves en Jira: …» de la región. */
const keysParagraph = (region: HTMLElement) => within(region).getByText(/^Claves en Jira:/, { selector: 'p' })

describe('PA-325 · Resultado de la HU', () => {
  it('test_published_story_keys_link_to_jira', async () => {
    /** PA-325: HU publicada → «Claves en Jira: DEMO-3» con DEMO-3 enlazada a `…/browse/DEMO-3`, en otra pestaña. */
    mockDb.forceApprove = 'published'
    mockDb.settings = { ...mockDb.settings, jira_browse_url: BROWSE }
    const region = await approveStory('Publicado en Jira')
    const keys = keysParagraph(region)
    const link = await within(keys).findByRole('link', { name: /^DEMO-3\s*\(se abre en Jira/ })
    expect(link).toHaveAttribute('href', `${BROWSE}DEMO-3`)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAccessibleName(/^DEMO-3\s*\(se abre en Jira, en otra pestaña\)$/)
    expect(within(keys).getAllByRole('link')).toHaveLength(1)
  })

  it('test_published_story_keys_are_text_when_browse_url_null', async () => {
    /** PA-325: con `jira_browse_url` a null, la clave publicada va como texto, sin enlace. */
    mockDb.forceApprove = 'published'
    mockDb.settings = { ...mockDb.settings, jira_browse_url: null }
    const settings = holdSettings()
    const region = await approveStory('Publicado en Jira', settings.hold)
    await settings.settle()
    const keys = keysParagraph(region)
    expect(within(keys).queryByRole('link')).toBeNull()
    expect(keys).toHaveTextContent(/^Claves en Jira: DEMO-3$/)
  })

  it('test_partial_story_keys_link_to_jira', async () => {
    /** PA-325 + PA-324: publicada en parte, las claves que sí se publicaron también enlazan. */
    mockDb.forceApprove = 'partial'
    mockDb.settings = { ...mockDb.settings, jira_browse_url: BROWSE }
    const region = await approveStory('Publicada en parte')
    const link = await within(keysParagraph(region)).findByRole('link', { name: /^DEMO-3\s*\(se abre en Jira/ })
    expect(link).toHaveAttribute('href', `${BROWSE}DEMO-3`)
  })

  it('test_simulated_story_has_no_keys_nor_links', async () => {
    /** PA-325: en una simulación no hay claves publicadas ni enlaces a Jira. */
    const region = await approveStory('Publicación simulada')
    expect(within(region).queryByText(/Claves en Jira/)).toBeNull()
    expect(within(region).queryByRole('link')).toBeNull()
  })
})

describe('PA-325 · Resultado de la suite de QA', () => {
  it('test_published_suite_subtasks_link_to_jira', async () => {
    /** PA-325: suite publicada (`?simular=publicado`) → DEMO-21…DEMO-24 enlazan a sus subtareas, separadas por «, ». */
    mockDb.forceApprove = 'published'
    mockDb.settings = { ...mockDb.settings, jira_browse_url: BROWSE }
    const region = await approveSuite('Suite publicada en Jira')
    const keys = keysParagraph(region)
    await within(keys).findAllByRole('link')
    const links = within(keys).getAllByRole('link')
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['DEMO-21', 'DEMO-22', 'DEMO-23', 'DEMO-24'].map((key) => `${BROWSE}${key}`))
    for (const link of links) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    }
    const visible = keys.cloneNode(true) as HTMLElement
    for (const hidden of visible.querySelectorAll('.visually-hidden')) hidden.remove()
    expect(visible.textContent).toBe('Claves en Jira: DEMO-21, DEMO-22, DEMO-23, DEMO-24')
  })

  it('test_published_suite_subtasks_are_text_when_browse_url_null', async () => {
    /** PA-325: con `jira_browse_url` a null, las subtareas van como texto. */
    mockDb.forceApprove = 'published'
    mockDb.settings = { ...mockDb.settings, jira_browse_url: null }
    const settings = holdSettings()
    const region = await approveSuite('Suite publicada en Jira', settings.hold)
    await settings.settle()
    const keys = keysParagraph(region)
    expect(within(keys).queryByRole('link')).toBeNull()
    expect(keys).toHaveTextContent(/^Claves en Jira: DEMO-21, DEMO-22, DEMO-23, DEMO-24$/)
  })

  it('test_simulated_suite_has_no_keys_nor_links', async () => {
    /** PA-325: la suite simulada no tiene claves en Jira ni enlaces. */
    const region = await approveSuite('Publicación simulada')
    expect(within(region).queryByText(/Claves en Jira/)).toBeNull()
    expect(within(region).queryByRole('link')).toBeNull()
  })
})
