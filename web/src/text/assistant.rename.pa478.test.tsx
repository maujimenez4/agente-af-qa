// Un solo punto para el nombre (PA-478, docs/diseno/faq/README.md §3): con otro nombre en `text/assistant.ts`, cambian los
// textos de Inicio, el carril, la lista, la conversación, las esperas, los errores, la pestaña y el inicio de sesión.
// El módulo se sustituye por el mismo con «Zeta» en lugar de «FAQ» (nombre ficticio). API simulada (MSW), DEMO-3 sintético.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import examples from '../api/examples.json'
import type { ConversationOut } from '../api/types.ts'
import { App } from '../App.tsx'
import { presentError } from '../components/States/index.ts'
import { mockDb, mockServer } from '../mocks/node.ts'
import { ITERATING_LABEL } from '../screens/Iterate/iterateText.ts'
import { openEventStream } from '../test/sse.ts'

vi.mock('./assistant.ts', async (importOriginal) => {
  const original = await importOriginal<Record<string, unknown>>()
  return Object.fromEntries(
    Object.entries(original).map(([key, value]) => [key, typeof value === 'string' ? value.replaceAll('FAQ', 'Zeta') : value]),
  )
})

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const HOME_HEADING = { level: 1, name: '¿En qué trabajamos hoy?' } as const
const list = () => screen.getByRole('complementary', { name: 'Conversaciones' })

async function signedIn() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('heading', HOME_HEADING)
}

describe('El nombre sale de la constante (PA-478)', () => {
  it('inicio de sesión y pestaña', async () => {
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Entrar en Zeta' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Zeta' })).toBeInTheDocument()
    expect(screen.getByText('Inicia sesión para continuar en Zeta.')).toBeInTheDocument()
    expect(document.title).toBe('Zeta · Qaracter')
  })

  it('Inicio, el carril y la lista', async () => {
    await signedIn()
    expect(screen.getByRole('button', { name: 'Zeta · Inicio' })).toHaveAttribute('title', 'Zeta · Inicio')
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === 'Hola, soy Zeta, tu asistente de análisis funcional y QA.')).toBeInTheDocument()
    expect(screen.getByText('O escríbele a Zeta directamente')).toBeInTheDocument()
    expect(screen.getByText('Zeta propone; tú decides. Nada se publica en Jira sin tu aprobación.')).toBeInTheDocument()
    expect(within(list()).getByRole('heading', { name: 'Tus conversaciones con Zeta' })).toBeInTheDocument()
    expect(screen.queryByText(/\bFAQ\b/)).toBeNull()
  })

  it('la conversación: etiqueta del avatar, nombre para el lector y nota de control', async () => {
    await signedIn()
    await userEvent.click(await within(list()).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    const proposal = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    const log = screen.getByRole('log', { name: 'Conversación' })
    expect(within(log).getAllByText('Zeta').length).toBeGreaterThan(0)
    expect(within(log).getAllByText('Zeta:', { exact: false }).length).toBeGreaterThan(0)
    expect(within(proposal).getByText('La decisión es tuya: Zeta no publica nada sin tu aprobación.')).toBeInTheDocument()
  })

  it('las esperas: el título de Generando y el de Iterar', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, state: 'generating', review: null })),
      http.get('/api/v1/conversations/:id/events', openEventStream),
    )
    await signedIn()
    await userEvent.click(await within(list()).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    expect(await screen.findByText('Zeta está escribiendo la propuesta…')).toBeInTheDocument()
    expect(ITERATING_LABEL).toBe('Zeta está preparando una nueva versión…')
  })

  it('los cuatro títulos de error del asistente; el resto no cambia', () => {
    const title = (code: Parameters<typeof presentError>[0]['code']) => presentError({ code, message: 'Mensaje ficticio.', retry_after: null }).title
    expect(title('invalid_model_output')).toBe('Zeta no ha podido terminar la propuesta')
    expect(title('citation_failed')).toBe('Zeta no ha podido citar sus fuentes')
    expect(title('coverage_failed')).toBe('Zeta no ha podido cubrir todos los criterios')
    expect(title('quality_failed')).toBe('Zeta no ha podido revisar la calidad')
    expect(title('service_unavailable')).not.toMatch(/Zeta|FAQ/)
  })
})
