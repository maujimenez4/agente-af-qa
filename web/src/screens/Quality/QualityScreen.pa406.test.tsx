// PA-406: tope del sondeo de Revisar la calidad. Cada 2 s los dos primeros minutos y después cada 10 s; a los
// 30 min desde `created_at` (o desde que se abrió la pantalla), la tarjeta con «Volver a consultar» y
// «Revisar de nuevo». Reloj falso solo para `Date`; las esperas del sondeo las vence la prueba. Datos sintéticos.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { QualityReviewIn, QualityReviewOut } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { QualityScreen } from './QualityScreen.tsx'
import { QUALITY_POLL_MS, QUALITY_SLOW_POLL_MS, qualityPollDelay, reviewStartedAt } from './qualityText.ts'

const T0 = Date.parse('2026-10-06T10:00:00Z')
const MINUTE = 60_000
const STALE_TEXT = 'La revisión lleva más de 30 minutos en curso; puede que el servidor se haya reiniciado. Nada se ha escrito en Jira.'

// El ejemplo del contrato trae el informe; la prueba fija el estado y las fechas.
const base = (examples as unknown as Record<string, QualityReviewOut>)['POST /api/v1/quality-reviews 202']

/** Revisión ficticia de DEMO-4 con el estado y el `created_at` que decide la prueba. */
function reviewOf(state: QualityReviewOut['state'], createdAt: string): QualityReviewOut {
  return {
    ...(base as QualityReviewOut),
    id: 'rev-pa406',
    issue_key: 'DEMO-4',
    state,
    report: state === 'done' ? (base as QualityReviewOut).report : null,
    error: null,
    created_at: createdAt,
    updated_at: createdAt,
  }
}

/** Las esperas del sondeo (2 s y 10 s) se guardan; vencen cuando la prueba lo decide. El resto, reales. */
function capturePolls() {
  const pending: { ms: number; run: () => void; id: number }[] = []
  let next = 5_000_000
  const realSetTimeout = window.setTimeout.bind(window)
  const realClearTimeout = window.clearTimeout.bind(window)
  vi.spyOn(window, 'setTimeout').mockImplementation(((handler: () => void, ms?: number, ...args: unknown[]) => {
    if (ms === QUALITY_POLL_MS || ms === QUALITY_SLOW_POLL_MS) {
      next += 1
      pending.push({ ms, run: handler, id: next })
      return next
    }
    return realSetTimeout(handler, ms, ...args)
  }) as typeof window.setTimeout)
  vi.spyOn(window, 'clearTimeout').mockImplementation((id?: number) => {
    const index = pending.findIndex((timer) => timer.id === id)
    if (index >= 0) pending.splice(index, 1)
    else realClearTimeout(id)
  })
  return {
    armed: () => pending.map((timer) => timer.ms),
    /** Vence la única espera programada. */
    fire: () => {
      expect(pending).toHaveLength(1)
      const timer = pending.shift()
      act(() => timer?.run())
    },
  }
}

/** GET de la revisión: responde lo que diga `answer` y cuenta las consultas. */
function serveReview(answer: () => QualityReviewOut) {
  const calls = { gets: 0 }
  mockServer.use(
    http.get('/api/v1/quality-reviews/:id', () => {
      calls.gets += 1
      return HttpResponse.json(answer())
    }),
  )
  return calls
}

const noop = () => {}
const openReview = () => render(<QualityScreen reviewId="rev-pa406" onBack={noop} onChanged={noop} onEvolve={noop} />)
const at = (ms: number) => vi.setSystemTime(ms)

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  at(T0)
  mockDb.session = {
    username: 'af-demo',
    role: 'functional',
    csrf: 'csrf-ficticio',
  }
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  mockServer.events.removeAllListeners()
})

describe('PA-406 · plazos', () => {
  it('cada 2 s los dos primeros minutos y después cada 10 s', () => {
    expect(qualityPollDelay(0)).toBe(2000)
    expect(qualityPollDelay(2 * MINUTE - 1)).toBe(2000)
    expect(qualityPollDelay(2 * MINUTE)).toBe(10_000)
    expect(qualityPollDelay(29 * MINUTE)).toBe(10_000)
  })

  it('el tope cuenta desde created_at; si no se puede leer, desde que se abrió la pantalla', () => {
    expect(reviewStartedAt('2026-10-06T09:00:00Z', T0)).toBe(Date.parse('2026-10-06T09:00:00Z'))
    expect(reviewStartedAt('no-es-una-fecha', T0)).toBe(T0)
    expect(reviewStartedAt('', T0)).toBe(T0)
    expect(reviewStartedAt(undefined, T0)).toBe(T0)
  })

  it('un created_at posterior a la apertura (reloj del servidor adelantado) cuenta desde la apertura', () => {
    expect(reviewStartedAt(new Date(T0 + 45 * MINUTE).toISOString(), T0)).toBe(T0)
  })
})

describe('PA-406 · sondeo con tope', () => {
  it('una revisión creada hace 1 min se consulta cada 2 s; una de hace 5 min, cada 10 s', async () => {
    const polls = capturePolls()
    let createdAt = new Date(T0 - MINUTE).toISOString()
    const calls = serveReview(() => reviewOf('running', createdAt))
    openReview()
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    // Pasan 4 min: la siguiente consulta ya es la lenta.
    at(T0 + 4 * MINUTE)
    createdAt = new Date(T0 - MINUTE).toISOString()
    polls.fire()
    await waitFor(() => expect(calls.gets).toBe(2))
    await waitFor(() => expect(polls.armed()).toEqual([10_000]))
  })

  it('al pasar los 30 min desde created_at, la tarjeta y ninguna consulta más', async () => {
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', new Date(T0 - 29 * MINUTE - 55_000).toISOString()))
    openReview()
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    await waitFor(() => expect(polls.armed()).toEqual([10_000]))
    expect(screen.queryByText(STALE_TEXT)).toBeNull()

    at(T0 + 10_000)
    polls.fire()
    const card = await screen.findByRole('alert')
    expect(
      within(card).getByRole('heading', {
        name: 'El modelo no respondió a tiempo',
      }),
    ).toBeInTheDocument()
    expect(within(card).getByText(STALE_TEXT)).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', {
        name: 'Revisando la calidad de DEMO-4…',
      }),
    ).toBeNull()
    expect(screen.getByRole('button', { name: 'Volver a consultar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revisar de nuevo' })).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
    expect(calls.gets).toBe(2)
  })

  it('una huérfana de hace horas sale como tarjeta en la primera consulta', async () => {
    const polls = capturePolls()
    serveReview(() => reviewOf('running', new Date(T0 - 3 * 60 * MINUTE).toISOString()))
    openReview()
    expect(await screen.findByText(STALE_TEXT)).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
  })

  it('sin created_at legible, el tope cuenta desde que se abrió la pantalla', async () => {
    const polls = capturePolls()
    serveReview(() => reviewOf('running', 'no-es-una-fecha'))
    openReview()
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    at(T0 + 30 * MINUTE)
    polls.fire()
    expect(await screen.findByText(STALE_TEXT)).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
  })

  it('«Volver a consultar» consulta ya y abre otra ventana de 30 min, empezando por cada 2 s', async () => {
    const polls = capturePolls()
    let state: QualityReviewOut['state'] = 'running'
    const calls = serveReview(() => reviewOf(state, new Date(T0 - 40 * MINUTE).toISOString()))
    openReview()
    await screen.findByText(STALE_TEXT)
    expect(calls.gets).toBe(1)

    at(T0 + MINUTE)
    await userEvent.click(screen.getByRole('button', { name: 'Volver a consultar' }))
    await waitFor(() => expect(calls.gets).toBe(2))
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    // A los 29 min de la nueva ventana aún se consulta; termina con el informe.
    at(T0 + MINUTE + 29 * MINUTE)
    polls.fire()
    await waitFor(() => expect(polls.armed()).toEqual([10_000]))
    state = 'done'
    polls.fire()
    expect(await screen.findByRole('complementary', { name: 'Informe de calidad' })).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
  })

  it('la nueva ventana también tiene tope: a los 30 min del clic, otra vez la tarjeta', async () => {
    const polls = capturePolls()
    serveReview(() => reviewOf('running', new Date(T0 - 40 * MINUTE).toISOString()))
    openReview()
    await screen.findByText(STALE_TEXT)
    await userEvent.click(screen.getByRole('button', { name: 'Volver a consultar' }))
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    at(T0 + 30 * MINUTE)
    polls.fire()
    expect(await screen.findByText(STALE_TEXT)).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
  })

  it('«Revisar de nuevo» lanza otra revisión de la misma HU y vuelve a consultar', async () => {
    const polls = capturePolls()
    serveReview(() => reviewOf('running', new Date(T0 - 40 * MINUTE).toISOString()))
    const posts: QualityReviewIn[] = []
    mockServer.use(
      http.post('/api/v1/quality-reviews', async ({ request }) => {
        posts.push((await request.json()) as QualityReviewIn)
        return HttpResponse.json(
          {
            ...reviewOf('running', new Date(T0).toISOString()),
            id: 'rev-pa406-b',
          },
          { status: 202 },
        )
      }),
    )
    openReview()
    await screen.findByText(STALE_TEXT)

    await userEvent.click(screen.getByRole('button', { name: 'Revisar de nuevo' }))
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    expect(posts).toEqual([{ issue_key: 'DEMO-4', excluded_sources: [] }])
    expect(screen.queryByText(STALE_TEXT)).toBeNull()
    await waitFor(() => expect(polls.armed()).toEqual([2000]))
  })

  it('un doble clic en «Revisar de nuevo» envía un solo POST', async () => {
    capturePolls()
    serveReview(() => reviewOf('running', new Date(T0 - 40 * MINUTE).toISOString()))
    const posts: QualityReviewIn[] = []
    mockServer.use(
      http.post('/api/v1/quality-reviews', async ({ request }) => {
        posts.push((await request.json()) as QualityReviewIn)
        return HttpResponse.json({ ...reviewOf('running', new Date(T0).toISOString()), id: 'rev-pa406-b' }, { status: 202 })
      }),
    )
    openReview()
    await screen.findByText(STALE_TEXT)

    await userEvent.dblClick(screen.getByRole('button', { name: 'Revisar de nuevo' }))
    await screen.findByRole('heading', { name: 'Revisando la calidad de DEMO-4…' })
    expect(posts).toHaveLength(1)
  })

  it('al cambiar de pantalla no queda ninguna consulta programada', async () => {
    const polls = capturePolls()
    serveReview(() => reviewOf('running', new Date(T0 - MINUTE).toISOString()))
    const { unmount } = openReview()
    await waitFor(() => expect(polls.armed()).toEqual([2000]))
    unmount()
    expect(polls.armed()).toEqual([])
  })
})

/** Puerta para retener una respuesta de MSW hasta que la prueba la suelte. */
function gate() {
  let open: () => void = () => {}
  const opened = new Promise<void>((resolve) => {
    open = resolve
  })
  return { opened, open: () => open() }
}

/** GET de la revisión que anota qué id se consulta y, si `hold` devuelve una promesa, retiene la respuesta. */
function serveReviewById(answer: (id: string) => QualityReviewOut, hold?: () => Promise<void> | undefined) {
  const ids: string[] = []
  mockServer.use(
    http.get('/api/v1/quality-reviews/:id', async ({ params }) => {
      const id = String(params.id)
      ids.push(id)
      const wait = hold?.()
      if (wait) await wait
      return HttpResponse.json({ ...answer(id), id })
    }),
  )
  return ids
}

/** Deja correr las promesas y las esperas reales de 0 ms (las respuestas de MSW ya soltadas). */
const settle = () =>
  act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0))
  })

describe('PA-406 · límites del tope y del respaldo', () => {
  it('test_keeps_polling_one_ms_before_cap', async () => {
    // Tope desde created_at: a 30 min menos 1 ms sigue consultando (cada 10 s); a los 30 min justos, la tarjeta.
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', new Date(T0 - 30 * MINUTE + 1).toISOString()))
    openReview()
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    await waitFor(() => expect(polls.armed()).toEqual([10_000]))
    expect(screen.queryByText(STALE_TEXT)).toBeNull()

    at(T0 + 1)
    polls.fire()
    expect(await screen.findByText(STALE_TEXT)).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
    expect(calls.gets).toBe(2)
  })

  it('test_switches_to_slow_poll_at_two_minutes_boundary', async () => {
    // Plazos: con 1 min 59 s en curso, 2 s; con 2 min justos, 10 s.
    const polls = capturePolls()
    serveReview(() => reviewOf('running', new Date(T0 - 2 * MINUTE + 1000).toISOString()))
    openReview()
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    at(T0 + 1000)
    polls.fire()
    await waitFor(() => expect(polls.armed()).toEqual([10_000]))
  })

  it('test_fallback_counts_from_opening_when_created_at_empty', async () => {
    // Respaldo: sin created_at (cadena vacía) los plazos y el tope cuentan desde que se abrió la pantalla.
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', ''))
    openReview()
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    // A los 3 min de abrir: ya cada 10 s, sin tarjeta.
    at(T0 + 3 * MINUTE)
    polls.fire()
    await waitFor(() => expect(polls.armed()).toEqual([10_000]))

    // A los 29 min 59 s: aún consulta.
    at(T0 + 30 * MINUTE - 1000)
    polls.fire()
    await waitFor(() => expect(calls.gets).toBe(3))
    await waitFor(() => expect(polls.armed()).toEqual([10_000]))
    expect(screen.queryByText(STALE_TEXT)).toBeNull()

    // A los 30 min de abrir: la tarjeta y ninguna consulta más.
    at(T0 + 30 * MINUTE)
    polls.fire()
    expect(await screen.findByText(STALE_TEXT)).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
    expect(calls.gets).toBe(4)
  })

  it('test_created_at_wins_over_opening_when_readable', async () => {
    // Tope desde created_at: una revisión de hace 31 min es tarjeta al abrir, aunque la pantalla acabe de abrirse.
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', new Date(T0 - 31 * MINUTE).toISOString()))
    openReview()
    expect(await screen.findByText(STALE_TEXT)).toBeInTheDocument()
    expect(polls.armed()).toEqual([])
    expect(calls.gets).toBe(1)
  })
})

describe('PA-406 · tarjeta y botones', () => {
  it('test_stale_card_stops_polling_even_as_time_passes', async () => {
    // Tarjeta: con la tarjeta a la vista no se programa ni se lanza ninguna consulta más, pase el tiempo que pase.
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', new Date(T0 - 40 * MINUTE).toISOString()))
    const changed = vi.fn()
    render(<QualityScreen reviewId="rev-pa406" onBack={noop} onChanged={changed} onEvolve={noop} />)
    await screen.findByText(STALE_TEXT)

    at(T0 + 5 * 60 * MINUTE)
    await settle()
    expect(polls.armed()).toEqual([])
    expect(calls.gets).toBe(1)
    expect(changed).not.toHaveBeenCalled()
  })

  it('test_recheck_shows_report_when_review_finished_meanwhile', async () => {
    // «Volver a consultar»: si entretanto terminó, sale el informe y no se programa nada.
    const polls = capturePolls()
    let state: QualityReviewOut['state'] = 'running'
    const calls = serveReview(() => reviewOf(state, new Date(T0 - 40 * MINUTE).toISOString()))
    openReview()
    await screen.findByText(STALE_TEXT)

    state = 'done'
    await userEvent.click(screen.getByRole('button', { name: 'Volver a consultar' }))
    expect(await screen.findByRole('complementary', { name: 'Informe de calidad' })).toBeInTheDocument()
    expect(screen.queryByText(STALE_TEXT)).toBeNull()
    expect(calls.gets).toBe(2)
    expect(polls.armed()).toEqual([])
  })

  it('test_recheck_double_click_queries_once', async () => {
    // Sin duplicados: un doble clic en «Volver a consultar» hace una consulta y deja una sola espera.
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', new Date(T0 - 40 * MINUTE).toISOString()))
    openReview()
    await screen.findByText(STALE_TEXT)

    await userEvent.dblClick(screen.getByRole('button', { name: 'Volver a consultar' }))
    await waitFor(() => expect(polls.armed()).toEqual([2000]))
    await settle()
    expect(polls.armed()).toEqual([2000])
    expect(calls.gets).toBe(2)
  })

  it('test_review_again_polls_the_new_review_id', async () => {
    // «Revisar de nuevo»: la siguiente consulta es la de la revisión nueva, no la huérfana.
    const polls = capturePolls()
    let createdAt = new Date(T0 - 40 * MINUTE).toISOString()
    const ids = serveReviewById(() => reviewOf('running', createdAt))
    mockServer.use(
      http.post('/api/v1/quality-reviews', () =>
        HttpResponse.json(
          {
            ...reviewOf('running', new Date(T0).toISOString()),
            id: 'rev-pa406-b',
          },
          { status: 202 },
        ),
      ),
    )
    openReview()
    await screen.findByText(STALE_TEXT)
    await userEvent.click(screen.getByRole('button', { name: 'Revisar de nuevo' }))
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    createdAt = new Date(T0).toISOString()
    at(T0 + 2000)
    polls.fire()
    await waitFor(() => expect(ids).toEqual(['rev-pa406', 'rev-pa406-b']))
    await waitFor(() => expect(polls.armed()).toEqual([2000]))
    expect(screen.queryByText(STALE_TEXT)).toBeNull()
  })

  it('test_review_again_failure_keeps_card_without_polling', async () => {
    // «Revisar de nuevo» con error de la API: la tarjeta sigue, con el error, y no se consulta nada.
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', new Date(T0 - 40 * MINUTE).toISOString()))
    mockServer.use(
      http.post('/api/v1/quality-reviews', () =>
        HttpResponse.json(
          {
            error: {
              code: 'service_unavailable',
              message: 'Servicio ficticio caído.',
            },
          },
          { status: 503 },
        ),
      ),
    )
    openReview()
    await screen.findByText(STALE_TEXT)
    await userEvent.click(screen.getByRole('button', { name: 'Revisar de nuevo' }))

    expect(await screen.findByText('Servicio ficticio caído.')).toBeInTheDocument()
    expect(screen.getByText(STALE_TEXT)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revisar de nuevo' })).toBeEnabled()
    expect(polls.armed()).toEqual([])
    expect(calls.gets).toBe(1)
  })
})

describe('PA-406 · sin temporizadores ni sondeos duplicados', () => {
  it('test_no_timer_after_unmount_with_request_in_flight', async () => {
    // Al desmontar con una consulta en curso, su respuesta tardía no programa ninguna espera.
    const polls = capturePolls()
    const held = gate()
    let holding = false
    const ids = serveReviewById(
      () => reviewOf('running', new Date(T0 - MINUTE).toISOString()),
      () => (holding ? held.opened : undefined),
    )
    const { unmount } = openReview()
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    holding = true
    polls.fire()
    await waitFor(() => expect(ids).toHaveLength(2))
    unmount()
    held.open()
    await settle()
    expect(polls.armed()).toEqual([])
  })

  it('test_no_timer_after_unmount_on_stale_card', async () => {
    // Al desmontar con la tarjeta a la vista no queda nada programado.
    const polls = capturePolls()
    serveReview(() => reviewOf('running', new Date(T0 - 40 * MINUTE).toISOString()))
    const { unmount } = openReview()
    await screen.findByText(STALE_TEXT)
    unmount()
    expect(polls.armed()).toEqual([])
  })

  it('test_late_response_after_rerender_leaves_single_wait', async () => {
    // Sin duplicados: si la pantalla se repinta con una consulta en curso, su respuesta tardía no añade otra espera.
    const polls = capturePolls()
    let held: ReturnType<typeof gate> | undefined
    const ids = serveReviewById(
      () => reviewOf('running', new Date(T0 - MINUTE).toISOString()),
      () => held?.opened,
    )
    const { rerender } = openReview()
    await waitFor(() => expect(polls.armed()).toEqual([2000]))

    const late = gate()
    held = late
    polls.fire()
    await waitFor(() => expect(ids).toHaveLength(2))
    // El padre se repinta con otro `onChanged`: el efecto se rehace mientras la consulta sigue en curso.
    rerender(<QualityScreen reviewId="rev-pa406" onBack={noop} onChanged={() => {}} onEvolve={noop} />)
    held = undefined
    late.open()
    await settle()
    expect(polls.armed()).toHaveLength(1)

    polls.fire()
    await waitFor(() => expect(ids).toHaveLength(3))
    await waitFor(() => expect(polls.armed()).toHaveLength(1))
  })

  it('test_recheck_during_review_again_leaves_single_wait_on_new_review', async () => {
    // Sin duplicados: «Revisar de nuevo» (POST retenido) y, mientras, «Volver a consultar» (GET retenido). Al
    // llegar el POST y después la respuesta tardía del GET, queda una sola espera y es la de la revisión nueva.
    const polls = capturePolls()
    let held: ReturnType<typeof gate> | undefined
    let createdAt = new Date(T0 - 40 * MINUTE).toISOString()
    const ids = serveReviewById(
      () => reviewOf('running', createdAt),
      () => held?.opened,
    )
    const post = gate()
    mockServer.use(
      http.post('/api/v1/quality-reviews', async () => {
        await post.opened
        return HttpResponse.json(
          {
            ...reviewOf('running', new Date(T0).toISOString()),
            id: 'rev-pa406-b',
          },
          { status: 202 },
        )
      }),
    )
    openReview()
    await screen.findByText(STALE_TEXT)

    const late = gate()
    held = late
    await userEvent.click(screen.getByRole('button', { name: 'Revisar de nuevo' }))
    await userEvent.click(screen.getByRole('button', { name: 'Volver a consultar' }))
    await waitFor(() => expect(ids).toEqual(['rev-pa406', 'rev-pa406']))

    held = undefined
    post.open()
    await waitFor(() => expect(polls.armed()).toEqual([2000]))
    late.open()
    await settle()
    expect(polls.armed()).toEqual([2000])
    expect(screen.queryByText(STALE_TEXT)).toBeNull()

    createdAt = new Date(T0).toISOString()
    at(T0 + 2000)
    polls.fire()
    await waitFor(() => expect(ids).toEqual(['rev-pa406', 'rev-pa406', 'rev-pa406-b']))
    await waitFor(() => expect(polls.armed()).toEqual([2000]))
  })

  // Regresión: `start()` dejaba el respaldo en `openedAt` y la revisión nueva heredaba los 40 min de la pantalla.
  it('test_review_again_without_created_at_gets_its_own_window', async () => {
    // «Revisar de nuevo» con created_at ilegible: la revisión nueva debería empezar su propia ventana (cada 2 s,
    // sin tarjeta) y no heredar el respaldo de la apertura de la pantalla (hace 40 min).
    const polls = capturePolls()
    const calls = serveReview(() => reviewOf('running', 'no-es-una-fecha'))
    mockServer.use(
      http.post('/api/v1/quality-reviews', () =>
        HttpResponse.json({ ...reviewOf('running', 'no-es-una-fecha'), id: 'rev-pa406-b' }, { status: 202 }),
      ),
    )
    openReview()
    await waitFor(() => expect(polls.armed()).toEqual([2000]))
    at(T0 + 40 * MINUTE)
    polls.fire()
    await screen.findByText(STALE_TEXT)

    await userEvent.click(screen.getByRole('button', { name: 'Revisar de nuevo' }))
    await screen.findByRole('heading', {
      name: 'Revisando la calidad de DEMO-4…',
    })
    expect(polls.armed()).toEqual([2000])

    at(T0 + 40 * MINUTE + 2000)
    polls.fire()
    await waitFor(() => expect(calls.gets).toBe(3))
    await settle()
    expect(screen.queryByText(STALE_TEXT)).toBeNull()
  })
})
