// PA-330 (T-56): presupuesto rápido en Origen. Al desmarcar una fuente sale al instante una estimación con
// `SourcePreview.tokens`; la respuesta de POST /start/sources la confirma y manda. Deterministas: las consultas con
// exclusiones quedan retenidas hasta que la prueba las suelta, así que la estimación se mira antes de cualquier respuesta.
// Datos sintéticos (DEMO-3, DOC-xx, af-demo). En la API simulada: DEMO-3 900 + 3 × 450 (RAG) + 550 (memoria) = 2.800.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, setCsrfToken } from '../../api/client.ts'
import type { OriginIn, SourcePreview, SourcesIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { MOCK_BUDGET_LIMIT, MOCK_NEED_FIXED_TOKENS, MOCK_REFILL_TOKENS } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { REFILL_NOTE } from './budget.ts'

const SOURCES_URL = '/api/v1/start/sources'
const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })
const label = () => within(panel()).getByText(/^Contexto ·/)
const box = () => label().parentElement as HTMLElement
const liveRegion = () => panel().querySelector('[aria-live="polite"]') as HTMLElement
const checkbox = (name: RegExp) => within(panel()).getByRole('checkbox', { name })

function login() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
}

async function evolveDemo3() {
  login()
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.click(screen.getByRole('textbox'))
  await userEvent.paste('Renovar un préstamo desde la app')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
  await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
  await within(panel()).findByText('Contexto · 2.800 de 6.000 tokens')
}

/**
 * Las consultas de POST /start/sources con exclusiones quedan retenidas hasta `release()`; luego siguen al handler de la
 * API simulada (o responden `respond()` si se da). La lista inicial (sin exclusiones) no se retiene.
 */
function holdExclusions(respond?: () => Response) {
  const bodies: SourcesIn[] = []
  const gates: Array<() => void> = []
  mockServer.use(
    http.post(SOURCES_URL, async ({ request }) => {
      const body = (await request.clone().json()) as SourcesIn
      if (body.excluded_sources.length === 0) return undefined
      bodies.push(body)
      await new Promise<void>((resolve) => gates.push(resolve))
      return respond ? respond() : undefined
    }),
  )
  return {
    bodies,
    release: () => gates.splice(0).forEach((resolve) => resolve()),
  }
}

/** Señales con las que la pantalla hizo cada consulta con exclusiones (la de MSW no refleja el `abort` del cliente). */
function spySignals() {
  const calls: Array<{ excluded: string[]; signal: AbortSignal | undefined }> = []
  const original = api.sources
  vi.spyOn(api, 'sources').mockImplementation((origin, excluded = [], signal) => {
    if (excluded.length > 0) calls.push({ excluded: [...excluded], signal })
    return original(origin, excluded, signal)
  })
  return calls
}

afterEach(() => {
  mockServer.events.removeAllListeners()
  vi.restoreAllMocks()
  setCsrfToken(null)
})

describe('Origen · estimación al desmarcar (PA-330, criterio 5)', () => {
  it('test_estimate_shows_immediately_when_source_is_unchecked_before_api_answers', async () => {
    /** Criterio 5: la estimación sale en el acto, con la respuesta retenida. */
    const held = holdExclusions()
    await evolveDemo3()
    await userEvent.click(checkbox(/Reglamento de préstamo/))
    expect(label()).toHaveTextContent('Contexto · ≈ 2.350 de 6.000 tokens · estimación')
    expect(box()).toHaveAttribute('data-estimate')
    expect(held.bodies).toHaveLength(0) // aún no ha salido ni la consulta (espera entre clics)
    held.release()
  })

  it('test_confirmed_number_replaces_estimate_when_api_answers', async () => {
    /** Criterio 5: con la respuesta, el número confirmado sin «≈» ni «estimación». */
    const held = holdExclusions()
    await evolveDemo3()
    await userEvent.click(checkbox(/Memoria validada de reservas/))
    expect(label()).toHaveTextContent('≈ 2.250')
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await waitFor(() => expect(label()).toHaveTextContent(/^Contexto · 2\.250 de 6\.000 tokens$/))
    expect(box()).not.toHaveAttribute('data-estimate')
  })

  it('test_refill_note_shows_when_confirmation_differs_more_than_one_percent', async () => {
    /** Criterio 5: al quitar un documento del RAG entra otro (+200, más del 1 % de 6.000): sale REFILL_NOTE. */
    const held = holdExclusions()
    await evolveDemo3()
    await userEvent.click(checkbox(/Reglamento de préstamo/))
    expect(within(panel()).queryByText(REFILL_NOTE)).toBeNull() // con la estimación aún no
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await waitFor(() => expect(label()).toHaveTextContent(/^Contexto · 2\.550 de 6\.000 tokens$/))
    const note = 'Al quitar un documento puede entrar otro relacionado en su lugar: la cifra confirmada es la que cuenta.'
    expect(within(box()).getByText(note)).toBeInTheDocument()
  })

  it('test_refill_note_hidden_when_confirmation_matches_estimate', async () => {
    /** Criterio 5 (negativo): la memoria no se rellena; confirmación = estimación, sin nota. */
    const held = holdExclusions()
    await evolveDemo3()
    await userEvent.click(checkbox(/Memoria validada de reservas/))
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await waitFor(() => expect(label()).toHaveTextContent(/^Contexto · 2\.250 de 6\.000 tokens$/))
    expect(within(panel()).queryByText(REFILL_NOTE)).toBeNull()
  })

  it('test_refill_note_disappears_when_a_new_estimate_starts', async () => {
    /** Criterio 5 (límite): la nota es de la confirmación; al volver a tocar una casilla, mientras se estima, no sale. */
    const held = holdExclusions()
    await evolveDemo3()
    await userEvent.click(checkbox(/Reglamento de préstamo/))
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await within(panel()).findByText(REFILL_NOTE)
    await userEvent.click(checkbox(/Memoria validada de reservas/))
    expect(label()).toHaveTextContent('Contexto · ≈ 1.800 de 6.000 tokens · estimación')
    expect(within(panel()).queryByText(REFILL_NOTE)).toBeNull()
    await waitFor(() => expect(held.bodies).toHaveLength(2))
    held.release()
  })
})

describe('Origen · varios clics seguidos (PA-330, criterio 6)', () => {
  it('test_single_request_with_final_exclusions_when_clicks_are_quick', async () => {
    /** Criterio 6: clics en el mismo instante, una sola POST con las exclusiones finales; la estimación sigue cada clic. */
    const held = holdExclusions()
    await evolveDemo3()
    fireEvent.click(checkbox(/Reglamento de préstamo/))
    expect(label()).toHaveTextContent('≈ 2.350')
    fireEvent.click(checkbox(/Acta de la comisión/))
    expect(label()).toHaveTextContent('≈ 1.900')
    fireEvent.click(checkbox(/Reglamento de préstamo/))
    expect(label()).toHaveTextContent('≈ 2.350')
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    expect(held.bodies[0]?.excluded_sources).toEqual(['DOC-20'])
    held.release()
    await waitFor(() => expect(label()).toHaveTextContent(/^Contexto · 2\.550 de 6\.000 tokens$/))
    expect(held.bodies).toHaveLength(1)
  })

  it('test_previous_requests_aborted_when_clicks_arrive_after_debounce', async () => {
    /** Criterio 6: si la consulta anterior ya salió, se aborta; solo cuenta la última, con las exclusiones finales. */
    const held = holdExclusions()
    await evolveDemo3()
    const calls = spySignals()
    await userEvent.click(checkbox(/Reglamento de préstamo/))
    await waitFor(() => expect(calls).toHaveLength(1))
    await userEvent.click(checkbox(/Memoria validada de reservas/))
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[0]?.signal?.aborted).toBe(true)
    expect(calls[1]?.signal?.aborted).toBe(false)
    expect(calls[1]?.excluded).toEqual(['DOC-01', 'memoria-DEMO-2'])
    expect(label()).toHaveTextContent('Contexto · ≈ 1.800 de 6.000 tokens · estimación')
    await waitFor(() => expect(held.bodies).toHaveLength(2))
    held.release()
    // 2.800 − 450 − 550 + 200 (relleno del RAG): la confirmación es la de la última consulta, no la abortada.
    await waitFor(() => expect(label()).toHaveTextContent(/^Contexto · 2\.000 de 6\.000 tokens$/))
  })
})

describe('Origen · accesibilidad del presupuesto (PA-330, criterio 7)', () => {
  it('test_live_region_never_announces_estimate_when_boxes_change', async () => {
    /** Criterio 7: mientras hay estimación, la región viva no cambia ni lleva «≈»; tras confirmar, el texto confirmado y la nota. */
    const held = holdExclusions()
    await evolveDemo3()
    expect(liveRegion()).toHaveTextContent('Presupuesto confirmado: 2.800 de 6.000 tokens.')
    const seen: string[] = []
    const observer = new MutationObserver(() => seen.push(liveRegion().textContent ?? ''))
    observer.observe(liveRegion(), { childList: true, characterData: true, subtree: true })

    await userEvent.click(checkbox(/Reglamento de préstamo/))
    expect(label()).toHaveTextContent('estimación')
    const duringEstimate = liveRegion().textContent
    await userEvent.click(checkbox(/Acta de la comisión/))
    expect(label()).toHaveTextContent('≈ 1.900')
    expect(liveRegion().textContent).toBe(duringEstimate) // otra estimación: la región no cambia
    expect(duringEstimate).not.toMatch(/≈|estimación|2\.350|1\.900/)

    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await waitFor(() =>
      expect(liveRegion()).toHaveTextContent(
        'Presupuesto confirmado: 2.100 de 6.000 tokens. ' +
          'Al quitar un documento puede entrar otro relacionado en su lugar: la cifra confirmada es la que cuenta.',
      ),
    )
    observer.disconnect()
    expect(seen.some((text) => /≈|estimación/.test(text))).toBe(false)
  })

  it('test_live_region_omits_refill_note_when_confirmation_matches', async () => {
    /** Criterio 7: sin diferencia, solo «Presupuesto confirmado: N de L tokens.». */
    const held = holdExclusions()
    await evolveDemo3()
    await userEvent.click(checkbox(/Memoria validada de reservas/))
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await waitFor(() => expect(liveRegion().textContent).toBe('Presupuesto confirmado: 2.250 de 6.000 tokens.'))
  })

  it('test_visible_box_has_no_aria_live_when_estimating_or_confirmed', async () => {
    /** Criterio 7: la caja visible no es una región viva (ni ella ni lo que contiene). */
    const held = holdExclusions()
    await evolveDemo3()
    await userEvent.click(checkbox(/Reglamento de préstamo/))
    expect(box()).not.toHaveAttribute('aria-live')
    expect(box().querySelector('[aria-live]')).toBeNull()
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await within(panel()).findByText(REFILL_NOTE)
    expect(box()).not.toHaveAttribute('aria-live')
    expect(box().querySelector('[aria-live]')).toBeNull()
    expect(box().contains(liveRegion())).toBe(false)
  })
})

describe('Origen · API sin tokens por fuente (PA-330, criterio 8)', () => {
  const LEGACY_SOURCES: SourcePreview[] = [
    { ref: 'DEMO-3', kind: 'jira', title: 'HU de origen: Renovar un préstamo', category: 'Story', required: true },
    { ref: 'DOC-01', kind: 'rag', title: 'Reglamento de préstamo', category: 'politicas', required: false },
  ]

  it('test_previous_budget_kept_without_estimate_when_sources_lack_tokens', async () => {
    /** Criterio 8: sin `tokens` (API anterior) no se estima; se ve el presupuesto anterior hasta la respuesta. */
    const gates: Array<() => void> = []
    mockServer.use(
      http.post(SOURCES_URL, async ({ request }) => {
        const { excluded_sources: excluded } = (await request.clone().json()) as SourcesIn
        if (excluded.length > 0) await new Promise<void>((resolve) => gates.push(resolve))
        return HttpResponse.json({
          sources: LEGACY_SOURCES,
          budget: { used: excluded.length > 0 ? 900 : 1350, limit: 6000, dropped_sources: 0, truncated_sources: 0 },
        })
      }),
    )
    login()
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.click(screen.getByRole('textbox'))
    await userEvent.paste('Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await within(panel()).findByText('Contexto · 1.350 de 6.000 tokens')

    await userEvent.click(checkbox(/Reglamento de préstamo/))
    expect(label()).toHaveTextContent(/^Contexto · 1\.350 de 6\.000 tokens$/)
    expect(box()).not.toHaveAttribute('data-estimate')
    await waitFor(() => expect(gates).toHaveLength(1))
    expect(label()).toHaveTextContent(/^Contexto · 1\.350 de 6\.000 tokens$/)
    gates.splice(0).forEach((resolve) => resolve())
    await waitFor(() => expect(label()).toHaveTextContent(/^Contexto · 900 de 6\.000 tokens$/))
    expect(within(panel()).queryByText(REFILL_NOTE)).toBeNull()
    expect(liveRegion().textContent).toBe('Presupuesto confirmado: 900 de 6.000 tokens.')
  })
})

describe('Origen · fallo de la confirmación (PA-330, criterio 9)', () => {
  const failure = () =>
    HttpResponse.json(
      { error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } },
      { status: 503 },
    )

  it('test_budget_hidden_when_confirmation_fails_after_estimate', async () => {
    /** Criterio 9: tras el fallo no se pinta ni la estimación ni el presupuesto viejo, y no se anuncia nada. */
    const held = holdExclusions(failure)
    await evolveDemo3()
    await userEvent.click(checkbox(/Reglamento de préstamo/))
    expect(label()).toHaveTextContent('≈ 2.350')
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await waitFor(() => expect(within(panel()).queryByText(/^Contexto ·/)).toBeNull())
    expect(within(panel()).queryByText(/2\.800|2\.350/)).toBeNull()
    expect(liveRegion().textContent).toBe('')
  })

  it('test_estimate_not_painted_when_budget_failed_and_another_box_changes', async () => {
    /** Criterio 9 (límite): sin presupuesto válido, otra casilla tampoco pinta una estimación. */
    const held = holdExclusions(failure)
    let answered = 0
    mockServer.events.on('response:mocked', ({ request }) => {
      if (new URL(request.url).pathname === SOURCES_URL) answered += 1
    })
    await evolveDemo3()
    const before = answered
    await userEvent.click(checkbox(/Reglamento de préstamo/))
    await waitFor(() => expect(held.bodies).toHaveLength(1))
    held.release()
    await waitFor(() => expect(within(panel()).queryByText(/^Contexto ·/)).toBeNull())
    await userEvent.click(checkbox(/Memoria validada de reservas/))
    expect(within(panel()).queryByText(/^Contexto ·/)).toBeNull()
    await waitFor(() => expect(held.bodies).toHaveLength(2))
    held.release()
    await waitFor(() => expect(answered).toBe(before + 2))
    expect(within(panel()).queryByText(/^Contexto ·/)).toBeNull()
    expect(liveRegion().textContent).toBe('')
  })
})

describe('Origen · necesidad nueva (PA-330, criterio 10)', () => {
  it('test_fixed_line_shows_when_origin_is_a_new_need', async () => {
    /** Criterio 10: con `origin.kind === 'need'`, la línea de `fixed` con el total. */
    const bodies: SourcesIn[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname === SOURCES_URL) bodies.push((await request.clone().json()) as SourcesIn)
    })
    login()
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.click(screen.getByRole('textbox'))
    await userEvent.paste('Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Crear HU nueva' }))
    const line = await within(panel()).findByText('El texto de la necesidad ocupa 300 tokens aparte del total de 6.300.')
    expect(line.parentElement).toBe(box())
    expect(bodies[0]?.origin.kind).toBe('need')
  })

  it('test_fixed_line_hidden_when_origin_is_a_story', async () => {
    /** Criterio 10 (negativo): al evolucionar una HU, `fixed` es 0 y no hay línea. */
    await evolveDemo3()
    expect(within(panel()).queryByText(/El texto de la necesidad ocupa/)).toBeNull()
  })
})

describe('API simulada · POST /start/sources (PA-330, criterio 11)', () => {
  const STORY: OriginIn = { kind: 'story', key: 'DEMO-3', project: 'DEMO' }
  const NEED: OriginIn = { kind: 'need', text: 'Necesidad ficticia de préstamo', project: 'DEMO' }

  function authenticate() {
    login()
    setCsrfToken('csrf-ficticio')
  }

  it('test_mock_returns_tokens_per_source_and_fixed_total_when_story', async () => {
    /** Criterio 11: `tokens` por fuente (por tipo) y `fixed` 0 / `total` = límite al evolucionar una HU. */
    authenticate()
    const { sources, budget } = await api.sources(STORY, [])
    expect(sources.map(({ ref, tokens }) => [ref, tokens])).toEqual([
      ['DEMO-3', 900],
      ['DOC-01', 450],
      ['DOC-08', 450],
      ['DOC-20', 450],
      ['memoria-DEMO-2', 550],
    ])
    expect(budget).toMatchObject({ used: 2800, limit: MOCK_BUDGET_LIMIT, fixed: 0, total: MOCK_BUDGET_LIMIT })
  })

  it('test_mock_returns_fixed_when_origin_is_a_need', async () => {
    /** Criterio 11: necesidad nueva, `fixed` = MOCK_NEED_FIXED_TOKENS y `total` = fixed + limit; `fixed` no entra en `used`. */
    authenticate()
    const { sources, budget } = await api.sources(NEED, [])
    expect(sources.every((source) => typeof source.tokens === 'number')).toBe(true)
    expect(budget).toMatchObject({ used: 1900, fixed: MOCK_NEED_FIXED_TOKENS, total: MOCK_NEED_FIXED_TOKENS + MOCK_BUDGET_LIMIT })
  })

  it('test_mock_used_includes_refill_when_rag_document_is_excluded', async () => {
    /** Criterio 11: excluir un documento del RAG suma MOCK_REFILL_TOKENS (una vez, aunque se excluyan varios). */
    authenticate()
    expect((await api.sources(STORY, ['DOC-01'])).budget.used).toBe(2800 - 450 + MOCK_REFILL_TOKENS)
    expect((await api.sources(STORY, ['DOC-01', 'DOC-08'])).budget.used).toBe(2800 - 900 + MOCK_REFILL_TOKENS)
  })

  it('test_mock_used_has_no_refill_when_only_memory_is_excluded', async () => {
    /** Criterio 11 (negativo): excluir la memoria no rellena; `used` es la suma exacta de lo que queda. */
    authenticate()
    const { sources, budget } = await api.sources(STORY, ['memoria-DEMO-2'])
    expect(sources.map((source) => source.ref)).not.toContain('memoria-DEMO-2')
    expect(budget.used).toBe(2800 - 550)
  })

  it('test_mock_keeps_required_source_when_excluded_by_mistake', async () => {
    /** Criterio 11 (límite): la HU de origen es obligatoria y sigue contando aunque llegue en las exclusiones. */
    authenticate()
    const { sources, budget } = await api.sources(STORY, ['DEMO-3'])
    expect(sources[0]).toMatchObject({ ref: 'DEMO-3', required: true, tokens: 900 })
    expect(budget.used).toBe(2800)
  })
})
