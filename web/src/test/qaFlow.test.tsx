// PA-127 · openSuiteInReview: deja QA 3 con la suite de DEMO-3 en revisión, igual que el recorrido por la interfaz
// (QA 1 → QA 2 → «Ver la suite»). Datos sintéticos (DEMO-3, qa-demo, csrf-ficticio).
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { setCsrfToken } from '../api/client.ts'
import type { ConversationCreateIn } from '../api/types.ts'
import { mockDb, mockServer, resetMockApi } from '../mocks/node.ts'
import { openSuiteForDemo3, openSuiteInReview } from './qaFlow.tsx'

const panel = () => screen.getByRole('complementary', { name: 'Suite de pruebas' })

/** Cuerpos de POST /conversations desde que se llama. */
function createBodies(): ConversationCreateIn[] {
  const bodies: ConversationCreateIn[] = []
  mockServer.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/conversations') {
      void request.clone().json().then((body) => bodies.push(body as ConversationCreateIn))
    }
  })
  return bodies
}

/** Lo que se ve de la suite en QA 3: pestañas, casos y acciones del pie. */
function suiteView() {
  const view = panel()
  return {
    tabs: within(view).getAllByRole('tab').map((item) => [item.textContent, item.getAttribute('aria-selected')]),
    text: view.textContent,
    review: within(view).getByRole('button', { name: 'Revisar y aprobar' }) instanceof HTMLElement,
  }
}

afterEach(() => mockServer.events.removeAllListeners())

describe('openSuiteInReview (PA-127)', () => {
  it('test_open_suite_in_review_leaves_qa3_with_demo3_suite_in_review', async () => {
    /** Criterio 2: QA 3 con la suite de DEMO-3 (versión 1, en revisión, pestaña Casos) y sesión de QA. */
    await openSuiteInReview()
    expect(mockDb.session?.role).toBe('qa')
    const runs = [...mockDb.runs.values()].filter((run) => run.conversation.mode === 'qa')
    expect(runs).toHaveLength(1)
    const conversation = runs[0]?.conversation
    expect(conversation?.state).toBe('in_review')
    expect(conversation?.review?.version).toBe(1)
    expect(conversation?.title).toContain('DEMO-3')
    expect(within(panel()).getByRole('tab', { name: 'Casos (4)' })).toHaveAttribute('aria-selected', 'true')
    expect(within(panel()).getByRole('button', { name: 'Revisar y aprobar' })).toBeEnabled()
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la suite/ })).toBeEnabled()
  })

  it('test_open_suite_in_review_sends_the_same_body_and_shows_the_same_suite_as_the_ui_route', async () => {
    /** Criterio 2: mismo cuerpo de POST /conversations que Origen por defecto y la misma vista que tras «Ver la suite». */
    const bodies = createBodies()
    await openSuiteForDemo3()
    const byUi = suiteView()
    cleanup()
    resetMockApi()
    setCsrfToken(null)
    await openSuiteInReview()
    const byHelper = suiteView()
    await expect.poll(() => bodies.length).toBe(2)
    expect(bodies[1]).toEqual(bodies[0])
    expect(byHelper.tabs).toEqual(byUi.tabs)
    expect(byHelper.text).toBe(byUi.text)
    expect(byHelper.review).toBe(true)
  })
})
