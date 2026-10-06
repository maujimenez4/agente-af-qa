// PA-328 · plurales de los recuentos visibles con una función común (`countLabel`): «1 fuente», «2 fuentes»,
// «1 criterio y 1 regla», «dentro de 1 segundo», «0 de 1 revisada». Datos sintéticos (DEMO-3, af-demo, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import examples from '../api/examples.json'
import type { ConversationOut, IssueCard } from '../api/types.ts'
import { App } from '../App.tsx'
import { changesLabel } from '../components/Proposal/index.ts'
import { ErrorCard } from '../components/States/ErrorCard.tsx'
import { casesLabel } from '../components/Suite/index.ts'
import { mockDb, mockServer } from '../mocks/node.ts'
import { mockSuiteConversation } from '../mocks/qaSuite.ts'
import { readyHeadline } from '../screens/Generating/headline.ts'
import { aiNotice, receiptOperations, reviewedCounter } from '../screens/Receipt/receiptText.ts'
import { countLabel, pluralWord } from './plural.ts'

describe('countLabel y pluralWord', () => {
  it.each([
    [0, '0 fuentes'],
    [1, '1 fuente'],
    [2, '2 fuentes'],
    [2350, '2.350 fuentes'],
  ])('%i → «%s»', (count, text) => {
    expect(countLabel(count, 'fuente', 'fuentes')).toBe(text)
  })

  it('pluralWord solo usa el singular con 1', () => {
    expect(pluralWord(1, 'regla', 'reglas')).toBe('regla')
    expect(pluralWord(0, 'regla', 'reglas')).toBe('reglas')
    expect(pluralWord(-1, 'regla', 'reglas')).toBe('reglas')
  })
})

describe('recuentos que ya pasan por countLabel', () => {
  it('casos, cambios, subtareas y fuentes en singular y en plural', () => {
    expect(casesLabel(1)).toBe('1 caso')
    expect(casesLabel(4)).toBe('4 casos')
    expect(changesLabel(1)).toBe('1 cambio frente a Jira')
    expect(changesLabel(3)).toBe('3 cambios frente a Jira')
    expect(aiNotice(1)).toBe('Generado con IA a partir de 1 fuente. Revisa cada operación antes de aprobar.')
    expect(aiNotice(2)).toBe('Generado con IA a partir de 2 fuentes. Revisa cada operación antes de aprobar.')
    const [one] = receiptOperations([{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '1' }], 1, 'DEMO-3', null)
    expect(one?.label).toMatch(/^Crear 1 subtarea en DEMO-3/)
  })

  it('el contador del recibo concuerda con el total: «0 de 1 revisada», «1 de 3 revisadas»', () => {
    expect(reviewedCounter(0, 1)).toBe('0 de 1 revisada')
    expect(reviewedCounter(1, 3)).toBe('1 de 3 revisadas')
    expect(reviewedCounter(1, 1)).toBe('Todo revisado')
  })

  it('Generando de QA: «Suite lista · Versión 1 · 1 caso»', () => {
    const suite = mockSuiteConversation('DEMO-3')
    const content = suite.review?.artifact.content as { cases: unknown[] }
    content.cases = content.cases.slice(0, 1)
    expect(readyHeadline(suite)).toBe('Suite lista · Versión 1 · 1 caso')
  })

  it('tarjeta de error: «dentro de 1 segundo» y «dentro de 2 segundos»', () => {
    const { unmount } = render(<ErrorCard error={{ code: 'rate_limited', message: 'Límite ficticio.', retry_after: 1 }} onAction={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Podrás reintentar dentro de 1 segundo.')
    unmount()
    render(<ErrorCard error={{ code: 'rate_limited', message: 'Límite ficticio.', retry_after: 2 }} onAction={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Podrás reintentar dentro de 2 segundos.')
  })
})

describe('pantallas', () => {
  it('ficha de Origen en QA: «1 criterio y 1 regla · 1 caso de prueba en Jira»', async () => {
    mockServer.use(
      http.get('/api/v1/issues/:key', () =>
        HttpResponse.json({
          key: 'DEMO-3',
          project: 'DEMO',
          issue_type: 'Story',
          status: 'Por hacer',
          summary: 'Renovar un préstamo',
          epic_key: 'DEMO-1',
          criteria_count: 1,
          rules_count: 1,
          test_cases: 1,
          published_by_agent: false,
        } satisfies IssueCard),
      ),
    )
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.click(screen.getAllByRole('textbox')[0] as HTMLElement)
    await userEvent.paste('DEMO-3')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Preparar pruebas de DEMO-3' }))
    expect(await screen.findByText('Épica DEMO-1 · 1 criterio y 1 regla · 1 caso de prueba en Jira')).toBeInTheDocument()
  })

  it('tarjeta del asistente en Iterar (HU): «2 fuentes» con las dos del ejemplo y «1 fuente» con una', async () => {
    const example = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
    const oneSource = structuredClone(example)
    const story = oneSource.review?.artifact.content as { sources: unknown[] }
    story.sources = story.sources.slice(0, 1)
    for (const item of oneSource.versions) (item.artifact.content as { sources: unknown[] }).sources = story.sources
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    expect(await screen.findByText(/^Generado con .+ · 2 fuentes$/)).toBeInTheDocument()

    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(oneSource)))
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    expect(await screen.findByText(/^Generado con .+ · 1 fuente$/)).toBeInTheDocument()
  })
})
