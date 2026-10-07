// PA-427: mientras la revisión de calidad está `running`, la Q de carga late como en Generando (la API no
// tiene SSE para la calidad: no hay pasos). Con «reducir movimiento», la Q está pero quieta. Datos sintéticos.
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { QualityReviewOut } from '../../api/types.ts'
import { LoadingState } from '../../components/States/index.ts'
import { mockServer } from '../../mocks/node.ts'
import { QualityScreen } from './QualityScreen.tsx'

function stubReducedMotion(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches,
      media: '(prefers-reduced-motion: reduce)',
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  )
}

/** El rectángulo de la Q: lleva las variables del pulso solo si late. */
function qRect(container: HTMLElement): SVGRectElement {
  const rect = container.querySelector('svg rect[style]')
  if (!rect) throw new Error('Sin la Q de carga')
  return rect as SVGRectElement
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Revisar la calidad · la Q mientras revisa (PA-427)', () => {
  it('una revisión en curso (sin pasos) anima la Q como en Generando', () => {
    stubReducedMotion(false)
    const { container } = render(<LoadingState title="Revisando la calidad de DEMO-4…" events={[]} running />)
    expect(screen.getByRole('heading', { name: 'Revisando la calidad de DEMO-4…' })).toBeInTheDocument()
    expect(qRect(container).style.getPropertyValue('--q-pulse-to')).not.toBe('')
  })

  it('sin `running` (como antes de PA-427) la Q no late', () => {
    stubReducedMotion(false)
    const { container } = render(<LoadingState title="Revisando la calidad de DEMO-4…" events={[]} />)
    expect(qRect(container).style.getPropertyValue('--q-pulse-to')).toBe('')
  })

  it('con «reducir movimiento», la Q está pero quieta', () => {
    stubReducedMotion(true)
    const { container } = render(<LoadingState title="Revisando la calidad de DEMO-4…" events={[]} running />)
    expect(container.querySelector('svg')).not.toBeNull()
    expect(qRect(container).style.getPropertyValue('--q-pulse-to')).toBe('')
  })
})

describe('Revisar la calidad · pantalla con una revisión en curso (PA-427)', () => {
  it('QualityScreen pinta «Revisando la calidad…» con la Q latiendo', async () => {
    stubReducedMotion(false)
    const done = examples['GET /api/v1/quality-reviews/{review_id} 200'] as unknown as QualityReviewOut
    // Recién lanzada: con fechas antiguas pasaría el tope de PA-406 y se daría por estancada.
    const now = new Date().toISOString()
    const running: QualityReviewOut = { ...done, id: 'r-en-curso', state: 'running', report: null, report_markdown: null, created_at: now, updated_at: now }
    mockServer.use(http.get('/api/v1/quality-reviews/:id', () => HttpResponse.json(running)))
    const { container } = render(<QualityScreen reviewId="r-en-curso" onBack={() => undefined} onChanged={() => undefined} onEvolve={() => undefined} />)
    expect(await screen.findByRole('heading', { name: /^Revisando la calidad de / })).toBeInTheDocument()
    expect(qRect(container).style.getPropertyValue('--q-pulse-to')).not.toBe('')
  })
})
