// PA-325 · Pestaña Impacto: cada HU afectada enlaza a Jira con `SettingsOut.jira_browse_url`; sin él (o si
// GET /settings falla), la clave va como texto. Solo se pide /settings si hay HU afectadas.
// Datos sintéticos (af-demo, conversación de ejemplo «Evolucionar DEMO-3», DEMO-2, prefijo del ejemplo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { ImpactView } from './index.ts'

const BROWSE = 'https://villaficticia-ejemplo.atlassian.net/browse/'

/** Peticiones a GET /settings desde que se llama. */
function countSettingsRequests(): () => number {
  let count = 0
  mockServer.events.on('request:start', ({ request }) => {
    if (request.method === 'GET' && new URL(request.url).pathname === '/api/v1/settings') count += 1
  })
  return () => count
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

const panel = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })

/** Abre «Evolucionar DEMO-3» desde la lista y la pestaña Impacto; devuelve su tabpanel. */
async function openImpactTab() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel()).getByRole('tab', { name: 'Impacto (1)' }))
  return within(panel()).getByRole('tabpanel')
}

describe('PA-325 · Impacto en Iterar', () => {
  it('test_affected_story_links_to_jira_with_browse_url', async () => {
    /** PA-325: DEMO-2 (HU afectada) enlaza a `…/browse/DEMO-2` en otra pestaña. */
    mockDb.settings = { ...mockDb.settings, jira_browse_url: BROWSE }
    const tab = await openImpactTab()
    const link = await within(tab).findByRole('link', { name: /^DEMO-2\s*\(se abre en Jira, en otra pestaña\)$/ })
    expect(link).toHaveAttribute('href', `${BROWSE}DEMO-2`)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    // El resto de la fila sigue: tipo de impacto y motivo.
    expect(tab).toHaveTextContent('Comparte la regla de reservas')
  })

  it('test_opening_impact_tab_requests_settings', async () => {
    /** PA-325: con HU afectadas, abrir la pestaña Impacto pide GET /settings. */
    mockDb.settings = { ...mockDb.settings, jira_browse_url: BROWSE }
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    const asked = countSettingsRequests()
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Impacto (1)' }))
    await expect.poll(asked).toBe(1)
  })

  it('test_affected_story_is_text_when_browse_url_null', async () => {
    /** PA-325: con `jira_browse_url` a null, DEMO-2 va como texto, sin enlace. */
    mockDb.settings = { ...mockDb.settings, jira_browse_url: null }
    const asked = countSettingsRequests()
    const tab = await openImpactTab()
    await expect.poll(asked).toBeGreaterThan(0)
    expect(within(tab).queryByRole('link')).toBeNull()
    expect(within(tab).getByText('DEMO-2')).toBeInTheDocument()
  })

  it('test_affected_story_is_text_when_settings_fails', async () => {
    /** PA-325: si GET /settings falla (500), DEMO-2 va como texto y la pestaña sigue funcionando. */
    let asked = 0
    mockServer.use(
      http.get('/api/v1/settings', () => {
        asked += 1
        return HttpResponse.json({ error: { code: 'internal_error', message: 'Error interno (ficticio).', retry_after: null } }, { status: 500 })
      }),
    )
    const tab = await openImpactTab()
    await expect.poll(() => asked).toBeGreaterThan(0)
    expect(within(tab).queryByRole('link')).toBeNull()
    expect(within(tab).getByText('DEMO-2')).toBeInTheDocument()
    expect(tab).toHaveTextContent('Comparte la regla de reservas')
    expect(tab).toHaveTextContent('Revisar el flujo de reservas.')
    expect(screen.queryByRole('alert')).toBeNull()
    // Se puede seguir navegando por las pestañas.
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Fuentes (2)' }))
    expect(within(panel()).getByRole('tabpanel')).toHaveTextContent('DOC-01')
  })
})

describe('PA-325 · ImpactView sin HU afectadas', () => {
  it('test_no_settings_request_without_affected_stories_only_notes', async () => {
    /** PA-325: sin HU afectadas (solo notas de regresión) no se pide /settings. */
    const asked = countSettingsRequests()
    render(<ImpactView impact={{ affected: [], diffs: [], regression_notes: ['Revisar el flujo de reservas (ficticio).'] }} />)
    expect(screen.getByText('Revisar el flujo de reservas (ficticio).')).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(asked()).toBe(0)
    expect(screen.queryByRole('link')).toBeNull()
  })

  it.each([
    ['null', null],
    ['undefined', undefined],
    ['vacío', { affected: [], diffs: [], regression_notes: [] }],
  ])('test_no_settings_request_with_impact_%s', async (_case, impact) => {
    /** PA-325: sin impacto, «No afecta a otras HU.» y ninguna petición a /settings. */
    const asked = countSettingsRequests()
    render(<ImpactView impact={impact} />)
    expect(screen.getByText('No afecta a otras HU.')).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(asked()).toBe(0)
  })

  it('test_each_affected_story_links_with_direct_render', async () => {
    /** PA-325: renderizado directo con dos HU afectadas; cada una enlaza a su clave. */
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    mockDb.settings = { ...mockDb.settings, jira_browse_url: BROWSE }
    render(
      <ImpactView
        impact={{
          affected: [
            { jira_key: 'DEMO-2', reason: 'Motivo ficticio uno', kind: 'rule' },
            { jira_key: 'DEMO-5', reason: 'Motivo ficticio dos', kind: 'rule' },
          ],
          diffs: [],
          regression_notes: [],
        }}
      />,
    )
    const links = await screen.findAllByRole('link')
    expect(links.map((link) => link.getAttribute('href'))).toEqual([`${BROWSE}DEMO-2`, `${BROWSE}DEMO-5`])
  })
})
