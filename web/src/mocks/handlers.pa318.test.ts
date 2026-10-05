// API simulada con las respuestas de la PR del 2026-10-05: `jira_browse_url` en /settings (PA-318) y la
// operación `comment` tras `update_story` en el plan (PA-319). Salen de los ejemplos del contrato. Datos sintéticos.
import { describe, expect, it } from 'vitest'
import type { ConversationOut, SessionOut, SettingsOut } from '../api/types.ts'
import { DEMO_PASSWORD } from './db.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(): Promise<void> {
  const response = await fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'af-demo', password: DEMO_PASSWORD }),
  })
  expect(((await response.json()) as SessionOut).user.username).toBe('af-demo')
}

describe('API simulada · PA-318 y PA-319', () => {
  it('GET /settings trae `jira_browse_url` con https', async () => {
    await login()
    const settings = (await (await fetch(url('/settings'))).json()) as SettingsOut
    expect(settings.jira_browse_url).toMatch(/^https:\/\/.+\/browse\/$/)
  })

  it('el plan de la revisión trae `comment` justo después de `update_story`', async () => {
    await login()
    const list = (await (await fetch(url('/conversations'))).json()) as Array<{ thread_id: string; status: string }>
    const inReview = list.find((item) => item.status === 'in_review')
    expect(inReview).toBeDefined()
    const conversation = (await (await fetch(url(`/conversations/${inReview?.thread_id ?? ''}`))).json()) as ConversationOut
    const ops = (conversation.review?.plan ?? []).map((item) => item.op)
    expect(ops).toContain('update_story')
    expect(ops.indexOf('comment')).toBe(ops.indexOf('update_story') + 1)
  })
})
