// PA-428: los extractos del RAG (fragmentos de documentos en Markdown) salían con `**`, `#`, `-` y tablas en
// bruto en las fuentes de la propuesta y del informe de calidad. Subconjunto seguro: títulos, párrafos,
// listas y tablas sencillas como elementos de React; nunca HTML. Datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import examples from '../../api/examples.json'
import type { QualityReviewOut, SourceRef } from '../../api/types.ts'
import { mockServer } from '../../mocks/node.ts'
import { QualityScreen } from '../../screens/Quality/QualityScreen.tsx'
import { SourcesView } from '../Proposal/ProposalViews.tsx'
import { MarkdownBlocks } from './MarkdownBlocks.tsx'
import { markdownBlocks } from './markdownBlocks.ts'

// Como DOC-12 del corpus ficticio: una tabla.
const TABLE = '| Plazo | Renovaciones |\n|---|:---:|\n| 21 días | **2** |\n| 14 días | 1 |'

describe('markdownBlocks: bloques de un extracto (PA-428)', () => {
  it('títulos, párrafos, listas con viñetas y numeradas', () => {
    expect(markdownBlocks('## Préstamos\nCada préstamo\nse renueva.\n\n- Web\n* App\n1. Primero\n2) Segundo\n> Nota ficticia')).toEqual([
      { kind: 'heading', text: 'Préstamos' },
      { kind: 'paragraph', text: 'Cada préstamo se renueva.' },
      { kind: 'list', ordered: false, items: ['Web', 'App'] },
      { kind: 'list', ordered: true, items: ['Primero', 'Segundo'] },
      { kind: 'paragraph', text: 'Nota ficticia' },
    ])
  })

  it('una tabla sencilla: cabecera y filas (celdas que faltan, vacías)', () => {
    expect(markdownBlocks(`${TABLE}\n| 7 días |`)).toEqual([
      {
        kind: 'table',
        header: ['Plazo', 'Renovaciones'],
        rows: [
          ['21 días', '**2**'],
          ['14 días', '1'],
          ['7 días', ''],
        ],
      },
    ])
  })

  it('un extracto cortado a mitad de una tabla: filas sueltas como texto, sin romper nada', () => {
    expect(markdownBlocks('| 21 días | 2 |\n| 14 días | 1 |')).toEqual([
      { kind: 'paragraph', text: '21 días · 2' },
      { kind: 'paragraph', text: '14 días · 1' },
    ])
    expect(markdownBlocks('|---|---|\n| 14 días | 1')).toEqual([{ kind: 'paragraph', text: '14 días · 1' }])
    expect(markdownBlocks('')).toEqual([])
  })

  it('\\r y los separadores de línea Unicode parten líneas (sin títulos que crucen líneas)', () => {
    expect(markdownBlocks('# Plazos\r\nTexto\u2028- uno')).toEqual([
      { kind: 'heading', text: 'Plazos' },
      { kind: 'paragraph', text: 'Texto' },
      { kind: 'list', ordered: false, items: ['uno'] },
    ])
  })

  it('una cabecera sin filas sigue siendo una tabla (el extracto se cortó tras el separador)', () => {
    expect(markdownBlocks('| Plazo | Renovaciones |\n|---|---|')).toEqual([{ kind: 'table', header: ['Plazo', 'Renovaciones'], rows: [] }])
  })
})

describe('MarkdownBlocks: pintado seguro (PA-428)', () => {
  it('negritas, títulos, listas y tablas como elementos, sin marcas en bruto', () => {
    const { container } = render(<MarkdownBlocks text={`# Normativa\nEl **plazo** es *fijo*.\n- uno\n1. dos\n\n${TABLE}`} />)
    expect(container.textContent).not.toMatch(/\*\*|^#|\|/)
    expect(screen.getByText('Normativa').tagName).toBe('STRONG')
    expect(screen.queryByRole('heading')).toBeNull() // un título del extracto no es un título de la página
    expect(screen.getByText('plazo').tagName).toBe('STRONG')
    expect(screen.getByText('fijo').tagName).toBe('EM')
    expect(container.querySelector('ul li')?.textContent).toBe('uno')
    expect(container.querySelector('ol li')?.textContent).toBe('dos')
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['Plazo', 'Renovaciones'])
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(within(table).getByText('2').tagName).toBe('STRONG')
  })

  it('el HTML del documento sale como texto: ni <script> ni <img onerror>', () => {
    const { container } = render(
      <MarkdownBlocks text={'<script>alert(1)</script>\n| <img src=x onerror=alert(1)> | b |\n|---|---|\n| [x](javascript:alert(1)) | c |'} />,
    )
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('<script>alert(1)</script>')
    expect(screen.getByRole('columnheader', { name: '<img src=x onerror=alert(1)>' })).toBeInTheDocument()
    expect(container.textContent).not.toContain('javascript:')
  })

  it('una marca sin cerrar se queda como texto', () => {
    const { container } = render(<MarkdownBlocks text={'Extracto **cortado a mitad'} />)
    expect(container.textContent).toBe('Extracto **cortado a mitad')
  })
})

describe('Fuentes de la propuesta con extractos en Markdown (PA-428)', () => {
  it('una fuente cuyo extracto es una tabla se pinta como tabla', () => {
    const sources = [{ kind: 'rag', ref: 'DOC-12', excerpt: TABLE }] as unknown as SourceRef[]
    render(<SourcesView sources={sources} />)
    const list = screen.getByRole('list', { name: 'Fuentes citadas' })
    expect(within(list).getByText('DOC-12')).toBeInTheDocument()
    expect(within(list).getByRole('table')).toBeInTheDocument()
    expect(list.textContent).not.toContain('|---|')
  })
})

describe('Fuentes del informe de calidad con extractos en Markdown (PA-428)', () => {
  it('el extracto de una fuente del informe se pinta como tabla, sin marcas en bruto', async () => {
    const done = examples['GET /api/v1/quality-reviews/{review_id} 200'] as unknown as QualityReviewOut
    const report = done.report
    if (!report) throw new Error('El ejemplo del contrato trae el informe')
    const review: QualityReviewOut = {
      ...done,
      id: 'r-con-tabla',
      report: { ...report, sources: [{ kind: 'rag', ref: 'DOC-12', excerpt: TABLE }] },
    }
    mockServer.use(http.get('/api/v1/quality-reviews/:id', () => HttpResponse.json(review)))
    render(<QualityScreen reviewId="r-con-tabla" onBack={() => undefined} onChanged={() => undefined} onEvolve={() => undefined} />)
    const panel = await screen.findByRole('complementary', { name: 'Informe de calidad' })
    const sources = within(panel).getByRole('region', { name: 'Fuentes' })
    expect(within(sources).getByRole('table')).toBeInTheDocument()
    expect(sources.textContent).not.toContain('|---|')
    expect(sources.textContent).not.toContain('**')
  })
})
