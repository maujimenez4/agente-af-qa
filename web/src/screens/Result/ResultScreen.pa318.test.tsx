// PA-318 («Abrir DEMO-3 en Jira» con `SettingsOut.jira_browse_url`) y PA-324 (estado tras una publicación
// parcial: suite → `approved`, HU → `published`; en los dos, `result.errors`). Solo datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { ButtonLink } from '../../components/Button/index.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { ResultScreen } from './ResultScreen.tsx'
import { hasResult, jiraIssueUrl, outcomeOf } from './resultText.ts'

const SIMULATED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as ConversationOut & { result: PublishOutcome }
const BROWSE = 'https://villaficticia-ejemplo.atlassian.net/browse/'

function renderPublished(result: Partial<PublishOutcome> = {}, state: ConversationOut['state'] = 'published') {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  const conversation = { ...SIMULATED, state, result: { ...SIMULATED.result, simulated: false, published_keys: ['DEMO-3'], ...result } }
  render(<ResultScreen conversation={conversation as ConversationOut & { result: PublishOutcome }} />)
}

describe('PA-318 · jiraIssueUrl', () => {
  it('une el prefijo https y la clave', () => {
    expect(jiraIssueUrl(BROWSE, 'DEMO-3')).toBe(`${BROWSE}DEMO-3`)
  })

  it.each([
    [null, 'DEMO-3'],
    [undefined, 'DEMO-3'],
    ['', 'DEMO-3'],
    ['http://villaficticia-ejemplo.atlassian.net/browse/', 'DEMO-3'],
    ['javascript:alert(1)//', 'DEMO-3'],
    ['https://usuario:clave@villaficticia-ejemplo.atlassian.net/browse/', 'DEMO-3'],
    [BROWSE, undefined],
    [BROWSE, 'DEMO-3/../../otra'],
    [BROWSE, 'demo-3'],
    [BROWSE, 'DEMO-3?x=1'],
    ['https://villaficticia-ejemplo.atlassian.net', 'DEMO-3'],
    ['https://villaficticia-ejemplo.atlassian.net/browse', 'DEMO-3'],
    ['https://villaficticia-ejemplo.atlassian.net/browse/?x=', 'DEMO-3'],
    ['https://villaficticia-ejemplo.atlassian.net/browse/#', 'DEMO-3'],
  ])('sin enlace con prefijo %j y clave %j', (browse, key) => {
    expect(jiraIssueUrl(browse, key)).toBeUndefined()
  })
})

describe('PA-318 · Resultado', () => {
  it('publicada con `jira_browse_url`: «Abrir DEMO-3 en Jira» es un enlace a la HU en otra pestaña', async () => {
    mockDb.settings = { ...mockDb.settings, jira_browse_url: BROWSE }
    renderPublished()
    const link = await screen.findByRole('link', { name: /Abrir DEMO-3 en Jira/ })
    expect(link).toHaveAttribute('href', `${BROWSE}DEMO-3`)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAccessibleName('Abrir DEMO-3 en Jira (se abre en otra pestaña)')
  })

  it('con `jira_browse_url` a null sigue «disponible pronto», sin enlace', async () => {
    let asked = 0
    mockServer.use(
      http.get('/api/v1/settings', () => {
        asked += 1
        return HttpResponse.json({ ...mockDb.settings, jira_browse_url: null })
      }),
    )
    renderPublished()
    await expect.poll(() => asked).toBe(1)
    expect(screen.getByRole('button', { name: /Abrir DEMO-3 en Jira/ })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('si /settings falla, no hay enlace y la pantalla sigue entera', async () => {
    let asked = 0
    mockServer.use(
      http.get('/api/v1/settings', () => {
        asked += 1
        return HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 })
      }),
    )
    renderPublished()
    await expect.poll(() => asked).toBe(1)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByRole('heading', { level: 2, name: 'Publicado en Jira' })).toBeInTheDocument()
  })

  it('en una simulación no pide /settings ni ofrece abrir Jira', () => {
    let asked = 0
    mockServer.use(
      http.get('/api/v1/settings', () => {
        asked += 1
        return HttpResponse.json(mockDb.settings)
      }),
    )
    render(<ResultScreen conversation={SIMULATED} />)
    expect(screen.queryByText(/en Jira$/)).toBeNull()
    expect(asked).toBe(0)
  })

  it('ButtonLink con un destino que no es seguro se pinta como texto, sin enlace', () => {
    render(<ButtonLink href="javascript:alert(1)">Abrir</ButtonLink>)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Abrir')).toBeInTheDocument()
  })
})

describe('PA-324 · publicación parcial', () => {
  it('HU escrita con un vínculo fallido: `published` con `result.errors` → «Publicada en parte» con el mensaje', () => {
    const conversation = { ...SIMULATED, state: 'published' as const, result: { ...SIMULATED.result, simulated: false, errors: ['No se pudo vincular DEMO-3 con DEMO-2 (ficticio).'] } }
    expect(hasResult(conversation)).toBe(true)
    expect(outcomeOf(conversation.result)).toBe('partial')
    renderPublished({ errors: ['No se pudo vincular DEMO-3 con DEMO-2 (ficticio).'] }, 'published')
    const region = screen.getByRole('region', { name: 'Publicada en parte' })
    expect(within(region).getByRole('alert')).toHaveTextContent('No se pudo vincular DEMO-3 con DEMO-2 (ficticio).')
  })

  it('suite con casos sin crear: `approved` con `result.errors` → «Publicada en parte» con el mensaje', () => {
    const result = { ...SIMULATED.result, simulated: false, errors: ['No se pudo crear CP-04 (ficticio).'], failed_ids: ['CP-04'] }
    expect(hasResult({ ...SIMULATED, state: 'approved', result })).toBe(true)
    renderPublished({ errors: ['No se pudo crear CP-04 (ficticio).'], failed_ids: ['CP-04'] }, 'approved')
    const region = screen.getByRole('region', { name: 'Publicada en parte' })
    expect(within(region).getByRole('alert')).toHaveTextContent('No se pudo crear CP-04 (ficticio).')
    expect(within(region).getByRole('alert')).toHaveTextContent('Fallaron: CP-04')
  })
})
