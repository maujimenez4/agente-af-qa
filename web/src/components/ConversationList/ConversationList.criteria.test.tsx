// Criterio 4 (DESIGN-DECISIONS.md §5, UI.md §2 y §7): textos «flujo · estado», grupos por día,
// buscador sin mayúsculas ni tildes, estado vacío, aria-current y texto de la API como texto.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DEMO_CONVERSATIONS, DEMO_NOW } from '../../fixtures/conversations.ts'
import { ConversationList, type ConversationListProps } from './ConversationList.tsx'
import {
  conversationTitle,
  flowLabel,
  groupByDay,
  matchesSearch,
  subtitle,
  type ConversationSummaryView,
} from './conversationLabels.ts'

const BASE: ConversationSummaryView = {
  thread_id: '00000000-0000-4000-8000-0000000000a1',
  project_key: 'DEMO',
  mode: 'functional',
  origin_kind: 'story',
  origin_key: 'DEMO-3',
  title: 'Reservar una sala ficticia',
  status: 'in_review',
  version: 2,
  updated_at: new Date(2026, 9, 2, 9, 0).toISOString(),
}

function conversation(overrides: Partial<ConversationSummaryView>): ConversationSummaryView {
  return { ...BASE, ...overrides }
}

function renderList(props: Partial<ConversationListProps> = {}) {
  const onNew = vi.fn()
  const onSelect = vi.fn()
  const result = render(
    <ConversationList conversations={DEMO_CONVERSATIONS} onNew={onNew} onSelect={onSelect} now={DEMO_NOW} {...props} />,
  )
  return { ...result, onNew, onSelect }
}

describe('«flujo · estado» (§5)', () => {
  it.each([
    [{ mode: 'qa', origin_kind: 'story', origin_key: 'DEMO-3', status: 'in_review', version: 1 }, 'Pruebas de DEMO-3 · Versión 1'],
    [{ mode: 'functional', origin_kind: 'story', origin_key: 'DEMO-3', status: 'published' }, 'Evolucionar DEMO-3 · Publicado'],
    [{ mode: 'functional', origin_kind: 'need', origin_key: null, status: 'simulated' }, 'Nueva necesidad · Simulado'],
    [{ mode: 'functional', origin_kind: 'epic', origin_key: 'DEMO-1', status: 'started' }, 'HU nueva en la épica DEMO-1 · En curso'],
    [{ mode: 'functional', origin_kind: 'story', origin_key: 'DEMO-3', status: 'approved' }, 'Evolucionar DEMO-3 · Aprobada'],
    [{ mode: 'qa', origin_kind: 'story', origin_key: 'DEMO-3', status: 'discarded' }, 'Pruebas de DEMO-3 · Descartada'],
  ] as const)('%j → «%s»', (overrides, text) => {
    expect(subtitle(conversation(overrides))).toBe(text)
  })

  it('una épica nunca se muestra como «Evolucionar»: «HU nueva en la épica DEMO-1»', () => {
    expect(flowLabel(conversation({ origin_kind: 'epic', origin_key: 'DEMO-1' }))).toBe('HU nueva en la épica DEMO-1')
    expect(flowLabel(conversation({ origin_kind: 'epic', origin_key: null }))).toBe('HU nueva en una épica')
  })

  it.each([
    ['Nueva HU en DEMO-1', 'HU nueva en la épica DEMO-1'],
    ['Evolucionar DEMO-3', 'Evolucionar DEMO-3'],
    ['Nueva necesidad · DEMO', 'Nueva necesidad · DEMO'],
    ['Nueva HU en DEMO-1 y más', 'Nueva HU en DEMO-1 y más'],
  ])('título de la API «%s» → «%s»', (title, shown) => {
    expect(conversationTitle(title)).toBe(shown)
  })

  it('la lista y el buscador usan el título que se muestra', async () => {
    render(<ConversationList conversations={[conversation({ title: 'Nueva HU en DEMO-1', origin_kind: 'epic', origin_key: 'DEMO-1' })]} onNew={() => {}} onSelect={() => {}} />)
    expect(screen.getByText('HU nueva en la épica DEMO-1')).toBeInTheDocument()
    expect(screen.queryByText('Nueva HU en DEMO-1')).toBeNull()
    expect(matchesSearch(conversation({ title: 'Nueva HU en DEMO-1', origin_kind: 'epic', origin_key: 'DEMO-1' }), 'la épica demo-1')).toBe(true)
  })

  it('una necesidad con clave sigue siendo «Nueva necesidad»', () => {
    expect(flowLabel(conversation({ origin_kind: 'need', origin_key: 'DEMO-9' }))).toBe('Nueva necesidad')
  })

  it('el separador es « · » con espacios', () => {
    expect(subtitle(BASE)).toMatch(/^Evolucionar DEMO-3 · Versión 2$/)
  })
})

describe('grupos por día (§5)', () => {
  it('ordena por updated_at aunque lleguen desordenadas, también dentro del mismo día', () => {
    const early = conversation({ thread_id: 'a', updated_at: new Date(2026, 9, 2, 8, 0).toISOString() })
    const late = conversation({ thread_id: 'b', updated_at: new Date(2026, 9, 2, 15, 0).toISOString() })
    const old = conversation({ thread_id: 'c', updated_at: new Date(2026, 8, 20, 12, 0).toISOString() })
    const groups = groupByDay([old, early, late], DEMO_NOW)
    expect(groups.map((group) => group.label)).toEqual(['Hoy', '20 de septiembre'])
    expect(groups[0]?.items.map((item) => item.thread_id)).toEqual(['b', 'a'])
  })

  it('justo después de medianoche, lo de las 23:59 es «Ayer»', () => {
    const now = new Date(2026, 9, 2, 0, 1)
    const groups = groupByDay([conversation({ updated_at: new Date(2026, 9, 1, 23, 59).toISOString() })], now)
    expect(groups.map((group) => group.label)).toEqual(['Ayer'])
  })

  it('«Ayer» funciona al cambiar de mes', () => {
    const now = new Date(2026, 9, 1, 10, 0)
    const groups = groupByDay([conversation({ updated_at: new Date(2026, 8, 30, 18, 0).toISOString() })], now)
    expect(groups[0]?.label).toBe('Ayer')
  })

  it('«Ayer» funciona al cambiar de año', () => {
    const now = new Date(2027, 0, 1, 10, 0)
    const groups = groupByDay([conversation({ updated_at: new Date(2026, 11, 31, 18, 0).toISOString() })], now)
    expect(groups[0]?.label).toBe('Ayer')
  })

  it('anteayer se muestra con su fecha en español («30 de septiembre»)', () => {
    const groups = groupByDay([conversation({ updated_at: new Date(2026, 8, 30, 10, 0).toISOString() })], DEMO_NOW)
    expect(groups[0]?.label).toBe('30 de septiembre')
  })

  it('el mismo día del mes anterior no es «Hoy»', () => {
    const groups = groupByDay([conversation({ updated_at: new Date(2026, 8, 2, 10, 0).toISOString() })], DEMO_NOW)
    expect(groups[0]?.label).toBe('2 de septiembre')
  })

  it('sin conversaciones no hay grupos', () => {
    expect(groupByDay([], DEMO_NOW)).toEqual([])
  })

  it('no modifica la lista recibida', () => {
    const input = [...DEMO_CONVERSATIONS].reverse()
    const copy = [...input]
    groupByDay(input, DEMO_NOW)
    expect(input).toEqual(copy)
  })

  it('no mezcla en un grupo el mismo día de años distintos', () => {
    const groups = groupByDay(
      [
        conversation({ thread_id: 'x', updated_at: new Date(2025, 8, 30, 10, 0).toISOString() }),
        conversation({ thread_id: 'y', updated_at: new Date(2024, 8, 30, 10, 0).toISOString() }),
      ],
      DEMO_NOW,
    )
    expect(groups).toHaveLength(2)
  })

  it('un updated_at no válido no rompe la lista', () => {
    expect(() => groupByDay([conversation({ updated_at: 'no-es-una-fecha' })], DEMO_NOW)).not.toThrow()
  })
})

describe('buscador (§5)', () => {
  it.each([
    ['PRÉSTAMO', true],
    ['préstamo', true],
    ['prestamo', true],
    ['PrEsTaMo', true],
    ['  préstamo  ', true],
    ['demo-3', true],
    ['publicado', true],
    ['evolucionar', true],
    ['reserva', false],
  ])('«%s» en «Renovar un préstamo…» → %s', (query, expected) => {
    const [published] = DEMO_CONVERSATIONS as [ConversationSummaryView]
    expect(matchesSearch(published, query)).toBe(expected)
  })

  it('encuentra por el estado con tilde escrito sin ella («version 2»)', () => {
    expect(matchesSearch(BASE, 'version 2')).toBe(true)
  })

  it('una tilde en la búsqueda también casa con un título sin tilde', () => {
    expect(matchesSearch(conversation({ title: 'Renovacion ficticia' }), 'renovación')).toBe(true)
  })

  it('la ñ se trata como n sin tilde (búsqueda sin diacríticos)', () => {
    expect(matchesSearch(conversation({ title: 'Año de prueba' }), 'ano')).toBe(true)
  })

  it('es local: filtrar no avisa de ninguna selección ni de nueva conversación', async () => {
    const { onSelect, onNew } = renderList()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Buscar conversaciones' }), 'demo')
    expect(onSelect).not.toHaveBeenCalled()
    expect(onNew).not.toHaveBeenCalled()
  })

  it('oculta los grupos que se quedan sin conversaciones', async () => {
    renderList()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Buscar conversaciones' }), 'socia')
    expect(screen.queryByRole('heading', { name: 'Hoy' })).toBeNull()
    expect(screen.getByRole('heading', { name: 'Ayer' })).toBeInTheDocument()
  })

  it('al borrar la búsqueda vuelven todas las conversaciones', async () => {
    renderList()
    const search = screen.getByRole('searchbox', { name: 'Buscar conversaciones' })
    await userEvent.type(search, 'socia')
    await userEvent.clear(search)
    expect(screen.getAllByRole('listitem')).toHaveLength(DEMO_CONVERSATIONS.length)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('el buscador tiene una etiqueta asociada (no solo placeholder)', () => {
    renderList()
    const search = screen.getByRole('searchbox')
    expect(search).toHaveAccessibleName('Buscar conversaciones')
    expect(search.id).not.toBe('')
  })
})

describe('ConversationList: estado vacío, aria-current y texto de la API', () => {
  it('vacía: no muestra el aviso de «sin coincidencias» ni ningún grupo (UI.md §7)', () => {
    renderList({ conversations: [] })
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryAllByRole('heading')).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'Nueva conversación' })).toBeEnabled()
  })

  it('sin currentId ninguna conversación lleva aria-current', () => {
    const { container } = renderList()
    expect(container.querySelectorAll('[aria-current]')).toHaveLength(0)
  })

  it('con un currentId que no está en la lista, ninguna lleva aria-current', () => {
    const { container } = renderList({ currentId: 'no-existe' })
    expect(container.querySelectorAll('[aria-current]')).toHaveLength(0)
  })

  it('cada grupo es una región con el nombre de su día', () => {
    renderList()
    const today = screen.getByRole('region', { name: 'Hoy' })
    expect(within(today).getAllByRole('listitem')).toHaveLength(2)
  })

  it('se retoma una conversación con el teclado', async () => {
    const { onSelect } = renderList()
    const [first] = DEMO_CONVERSATIONS as [ConversationSummaryView]
    screen.getByRole('button', { name: new RegExp(first.title) }).focus()
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith(first.thread_id)
  })

  it('la clave de proyecto, la clave de origen y el título se muestran como texto, nunca como HTML', () => {
    const hostile = conversation({
      project_key: '<b>PRJ</b>',
      origin_key: '<i>DEMO-3</i>',
      title: '<script>alert(1)</script>Título ficticio',
    })
    const { container } = renderList({ conversations: [hostile] })
    const item = screen.getByRole('button', { name: /Título ficticio/ })
    expect(item).toHaveTextContent('<b>PRJ</b>')
    expect(item).toHaveTextContent('Evolucionar <i>DEMO-3</i> · Versión 2')
    expect(item).toHaveTextContent('<script>alert(1)</script>Título ficticio')
    expect(container.querySelector('aside b, aside i, aside script')).toBeNull()
  })

  it('pasa el id para enlazarla con el botón de mostrar u ocultar', () => {
    renderList({ id: 'lista-demo' })
    expect(screen.getByRole('complementary', { name: 'Conversaciones' })).toHaveAttribute('id', 'lista-demo')
  })
})

describe('grupos por día: fechas de otros años y fechas no válidas', () => {
  it('un día de otro año lleva el año en la etiqueta', () => {
    const groups = groupByDay([conversation({ updated_at: new Date(2025, 8, 30, 10, 0).toISOString() })], DEMO_NOW)
    expect(groups.map((group) => group.label)).toEqual(['30 de septiembre de 2025'])
  })

  it('las fechas no válidas van al final, en «Sin fecha», y el resto se pinta', () => {
    const groups = groupByDay(
      [conversation({ thread_id: 'mala', updated_at: 'no-es-una-fecha' }), conversation({ thread_id: 'buena' })],
      DEMO_NOW,
    )
    expect(groups.at(-1)?.label).toBe('Sin fecha')
    expect(groups.at(-1)?.items.map((item) => item.thread_id)).toEqual(['mala'])
    expect(groups.flatMap((group) => group.items)).toHaveLength(2)
  })
})
