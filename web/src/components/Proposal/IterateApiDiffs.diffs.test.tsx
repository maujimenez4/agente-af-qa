// PA-341 de punta a punta: una conversación cuyos `impact.diffs` llegan con el formato de la API real
// («acceptance_criteria[CA-02]», core/impact/diff.py `_diff_by_id`), en la v1 y sin versión «Jira».
// Pestaña «Cambios (N)», marcas «Nueva» y «Cambiado en v1» y recibo. Datos sintéticos del ejemplo del contrato.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const REVIEW = EXAMPLE.review as NonNullable<ConversationOut['review']>

/** Diffs como los devuelve la API real: CA-02 nuevo, RN-01 cambiado y CA-09 quitado. */
const IMPACT = {
  ...REVIEW.impact,
  diffs: [
    { field: 'acceptance_criteria[CA-02]', before: null, after: 'Renovación rechazada por reservas' },
    { field: 'business_rules[RN-01]', before: 'Regla ficticia anterior', after: 'Máximo 2 renovaciones por préstamo.' },
    { field: 'acceptance_criteria[CA-09]', before: 'Criterio ficticio quitado', after: null },
  ],
} as NonNullable<ConversationOut['review']>['impact']

const ARTIFACT = { ...REVIEW.artifact, version: 1, impact: IMPACT }

/** v1 de una evolución sin `jira_baseline`: las marcas salen de los diffs (changeMarks sin versión anterior). */
const API_CONVERSATION: ConversationOut = {
  ...EXAMPLE,
  flow: 'evolve',
  jira_baseline: null,
  review: { ...REVIEW, version: 1, artifact: ARTIFACT, impact: IMPACT },
  versions: [{ ...EXAMPLE.versions[0]!, version: 1, artifact: ARTIFACT }],
}

beforeEach(() => {
  mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(API_CONVERSATION)))
})

async function openFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

describe('Iterar con los diffs de la API real (PA-341)', () => {
  it('la v1 sin versión «Jira» marca CA-02 como «Nueva» y RN-01 como «Cambiado en v1»', async () => {
    const panel = await openFromList()
    const versions = within(panel).getByRole('group', { name: 'Versiones' })
    expect(within(versions).getAllByRole('button').map((button) => button.textContent)).toEqual(['v1'])
    expect(within(versions).queryByRole('button', { name: 'Versión de Jira' })).toBeNull()

    const criteria = within(panel).getByRole('list', { name: 'Criterios de aceptación' })
    const ca02 = within(criteria).getByText('CA-02').closest('li') as HTMLElement
    expect(within(ca02).getByText('Nueva')).toBeInTheDocument()
    const ca01 = within(criteria).getByText('CA-01').closest('li') as HTMLElement
    expect(within(ca01).queryByText(/Nueva|Cambiado en/)).toBeNull()
    const rules = within(panel).getByRole('list', { name: 'Reglas de negocio' })
    const rn01 = within(rules).getByText('RN-01').closest('li') as HTMLElement
    expect(within(rn01).getByText('Cambiado en v1')).toBeInTheDocument()
  })

  it('la pestaña «Cambios (3)» nombra cada cambio por su id, sin el nombre técnico del campo', async () => {
    const panel = await openFromList()
    await userEvent.click(within(panel).getByRole('tab', { name: 'Cambios (3)' }))
    const items = within(within(panel).getByRole('list', { name: 'Cambios' })).getAllByRole('listitem')
    expect(items.map((item) => item.querySelector('b')?.textContent)).toEqual(['CA-02', 'RN-01', 'CA-09'])
    expect(within(items[0] as HTMLElement).getByText('Nuevo')).toBeInTheDocument()
    expect(within(items[2] as HTMLElement).getByText('Eliminado')).toBeInTheDocument()
    expect(within(panel).queryByText(/acceptance_criteria|business_rules/)).toBeNull()
  })

  it('el recibo dice qué cambia con el id: «Cambia: CA-02 (nuevo), RN-01, CA-09 (se quita).»', async () => {
    const panel = await openFromList()
    await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
    await screen.findByRole('region', { name: /lista para revisar/ })
    const operations = screen.getByRole('group', { name: /Qué se hará en Jira/ })
    expect(within(operations).getByText('Actualizar DEMO-3 con la versión 1')).toBeInTheDocument()
    expect(within(operations).getByText('Cambia: CA-02 (nuevo), RN-01, CA-09 (se quita).')).toBeInTheDocument()
    expect(within(operations).queryByText(/acceptance_criteria|business_rules/)).toBeNull()
  })
})
