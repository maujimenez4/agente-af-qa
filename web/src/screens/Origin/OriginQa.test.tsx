// QA 1 · Origen (UI.md §6.1): HU reconocida, operación fijada en sus subtareas, tipos de caso (RF-22) e
// «Incluir además» como primer feedback, fuentes y «Generar la suite». Datos sintéticos (DEMO-3, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationCreateIn, IssueCard } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openEventStream } from '../../test/sse.ts'
import { extrasSummary, qaFeedback } from './qaOptions.ts'

const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })
const typesGroup = () => within(panel()).getByRole('group', { name: 'Tipos de caso' })
const extrasButton = () => within(panel()).getByRole('button', { name: /^Incluir además/ })
/** «Incluir además» está plegado al empezar: se abre antes de mirarlo. */
async function openExtras() {
  if (extrasButton().getAttribute('aria-expanded') !== 'true') await userEvent.click(extrasButton())
  return within(panel()).getByRole('group', { name: 'Incluir además' })
}

async function prepareTestsDemo3() {
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.click(screen.getAllByRole('textbox')[0] as HTMLElement)
  await userEvent.paste('DEMO-3')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Preparar pruebas de DEMO-3' }))
  await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
}

function createBodies(): ConversationCreateIn[] {
  const bodies: ConversationCreateIn[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/conversations') {
      bodies.push((await request.clone().json()) as ConversationCreateIn)
    }
  })
  return bodies
}

afterEach(() => mockServer.events.removeAllListeners())

describe('qaFeedback', () => {
  it('todo marcado: los cuatro tipos y los tres extras', () => {
    expect(qaFeedback(new Set(['positive', 'negative', 'alternate', 'exception']), new Set(['data', 'risks', 'strategy']))).toEqual([
      'Incluye casos: positivos, negativos, alternos, de excepción.',
      'Incluye además: datos sintéticos de prueba (identificadores ficticios); riesgos, dependencias y áreas de impacto; estrategia de pruebas (alcance, niveles, entornos, criterios de entrada y salida, prioridad).',
    ])
  })

  it('positivos y negativos van siempre; sin extras, sin «Incluye además»', () => {
    expect(qaFeedback(new Set(), new Set())).toEqual(['Incluye casos: positivos, negativos.'])
  })
})

describe('QA 1 · Origen', () => {
  it('la cabecera es «Pruebas de DEMO-3» y la operación fijada dice dónde irán los casos', async () => {
    await prepareTestsDemo3()
    expect(screen.getByRole('heading', { level: 1, name: 'Pruebas de DEMO-3' })).toBeInTheDocument()
    expect(screen.getByText('Operación fijada: suite de pruebas de DEMO-3')).toBeInTheDocument()
    expect(screen.getByText('Los casos serán subtareas de DEMO-3 con la etiqueta «caso-prueba»; la estrategia y la matriz, adjuntos.')).toBeInTheDocument()
    expect(screen.getByText('Elige en el panel qué tipos de caso quieres y qué fuentes uso. La HU y su memoria ya están incluidas.')).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Generar la suite' })).toBeEnabled()
    expect(within(panel()).queryByLabelText('Restricciones (opcional)')).toBeNull()
  })

  it('tipos de caso: positivos y negativos marcados y fijos; alternos y de excepción, marcados y se pueden quitar', async () => {
    await prepareTestsDemo3()
    const group = typesGroup()
    for (const name of [/^Positivoss*· obligatorio$/, /^Negativoss*· obligatorio$/]) {
      const box = within(group).getByRole('checkbox', { name })
      expect(box).toBeChecked()
      expect(box).toBeDisabled()
      expect(box).toHaveAccessibleDescription('Positivos y negativos son obligatorios: la suite necesita al menos uno de cada.')
    }
    for (const name of ['Alternos', 'De excepción']) {
      expect(within(group).getByRole('checkbox', { name })).toBeChecked()
      expect(within(group).getByRole('checkbox', { name })).toBeEnabled()
    }
    const extras = await openExtras()
    expect(within(extras).getAllByRole('checkbox')).toHaveLength(3)
    within(extras).getAllByRole('checkbox').forEach((box) => expect(box).toBeChecked())
  })

  it('«Generar la suite» envía flow tests, los tipos y extras elegidos como primer feedback y después las indicaciones', async () => {
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    await prepareTestsDemo3()
    await userEvent.click(within(typesGroup()).getByRole('checkbox', { name: 'Alternos' }))
    await userEvent.click(within(await openExtras()).getByRole('checkbox', { name: /Estrategia de pruebas/ }))
    await userEvent.click(screen.getByRole('textbox', { name: /Indicaciones para QA \(opcional\)/ }))
    await userEvent.paste('Prioriza la renovación con reservas.')
    await userEvent.keyboard('{Enter}')
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar la suite' }))
    await screen.findByRole('img', { name: /Avance: fase 2 de 4/ })
    expect(bodies[0]).toMatchObject({
      flow: 'tests',
      origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
      feedback: [
        'Incluye casos: positivos, negativos, de excepción.',
        'Incluye además: datos sintéticos de prueba (identificadores ficticios); riesgos, dependencias y áreas de impacto.',
        'Prioriza la renovación con reservas.',
      ],
    })
  })

  it('«Incluir además» empieza plegado con su resumen, se abre con el teclado y el resumen sigue a las casillas', async () => {
    await prepareTestsDemo3()
    const button = extrasButton()
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveAccessibleName('Incluir además, 3 de 3 incluidos')
    expect(within(panel()).queryByRole('group', { name: 'Incluir además' })).toBeNull()
    // Las fuentes siguen a la vista con «Incluir además» plegado.
    expect(within(panel()).getByRole('group', { name: 'Fuentes que se usarán' })).toBeVisible()
    button.focus()
    await userEvent.keyboard('{Enter}')
    expect(button).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(within(panel()).getByRole('checkbox', { name: /Riesgos, dependencias e impacto/ }))
    expect(button).toHaveAccessibleName('Incluir además, 2 de 3 incluidos')
    // Espacio sobre el botón lo pliega; el resumen conserva lo elegido.
    button.focus()
    await userEvent.keyboard(' ')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveAccessibleName('Incluir además, 2 de 3 incluidos')
  })

  it('extrasSummary', () => {
    expect(extrasSummary(3, 3)).toBe('3 de 3 incluidos')
    expect(extrasSummary(1, 3)).toBe('1 de 3 incluido')
    expect(extrasSummary(0, 3)).toBe('Ninguno incluido')
  })

  it('la ficha dice cuántos casos de prueba tiene en Jira y si la publicó el agente', async () => {
    mockServer.use(
      http.get('/api/v1/issues/:key', () =>
        HttpResponse.json({
          key: 'DEMO-3',
          project: 'DEMO',
          issue_type: 'Story',
          status: 'Por hacer',
          summary: 'Renovar un préstamo',
          epic_key: 'DEMO-1',
          criteria_count: 4,
          rules_count: 2,
          test_cases: 0,
          published_by_agent: true,
        } satisfies IssueCard),
      ),
    )
    await prepareTestsDemo3()
    expect(await screen.findByText('Épica DEMO-1 · 4 criterios y 2 reglas · sin casos de prueba en Jira · publicada por FAQ')).toBeInTheDocument()
  })

  it('al evolucionar una HU no salen ni los tipos de caso ni los casos de prueba de Jira', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.click(screen.getAllByRole('textbox')[0] as HTMLElement)
    await userEvent.paste('Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
    expect(within(panel()).queryByRole('group', { name: 'Tipos de caso' })).toBeNull()
    expect(within(panel()).getByLabelText('Restricciones (opcional)')).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Generar propuesta' })).toBeInTheDocument()
    expect(screen.queryByText(/casos de prueba en Jira/)).toBeNull()
  })
})
