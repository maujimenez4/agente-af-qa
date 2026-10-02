import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DEMO_CONVERSATIONS, DEMO_NOW } from '../../fixtures/conversations.ts'
import { ConversationList, ConversationsToggle } from './ConversationList.tsx'
import { flowLabel, groupByDay, matchesSearch, statusLabel, type ConversationSummaryView } from './conversationLabels.ts'

const [published, qaReview, newNeed, epicSimulated] = DEMO_CONVERSATIONS as [
  ConversationSummaryView,
  ConversationSummaryView,
  ConversationSummaryView,
  ConversationSummaryView,
]

function renderList(props: Partial<Parameters<typeof ConversationList>[0]> = {}) {
  const onNew = vi.fn()
  const onSelect = vi.fn()
  render(
    <ConversationList conversations={DEMO_CONVERSATIONS} onNew={onNew} onSelect={onSelect} now={DEMO_NOW} {...props} />,
  )
  return { onNew, onSelect }
}

describe('textos de la lista', () => {
  it.each([
    [published, 'Evolucionar DEMO-3'],
    [qaReview, 'Pruebas de DEMO-3'],
    [newNeed, 'Nueva necesidad'],
    [epicSimulated, 'HU nueva en la épica DEMO-1'],
  ])('flujo de %#: «%s»', (conversation, label) => {
    expect(flowLabel(conversation)).toBe(label)
  })

  it.each([
    ['started', null, 'En curso'],
    ['in_review', 2, 'Versión 2'],
    ['in_review', null, 'En revisión'],
    ['approved', 1, 'Aprobada'],
    ['simulated', 1, 'Simulado'],
    ['published', 2, 'Publicado'],
    ['discarded', 1, 'Descartada'],
  ] as const)('estado %s (versión %s) → «%s»', (status, version, label) => {
    expect(statusLabel({ ...published, status, version })).toBe(label)
  })

  it('agrupa por día: Hoy, Ayer y la fecha, de lo más reciente a lo más antiguo', () => {
    const groups = groupByDay(DEMO_CONVERSATIONS, DEMO_NOW)
    expect(groups.map((group) => group.label)).toEqual(['Hoy', 'Ayer', '30 de septiembre'])
    expect(groups[0]?.items.map((item) => item.thread_id)).toEqual([published.thread_id, qaReview.thread_id])
  })

  it('busca sin distinguir mayúsculas ni tildes, también por proyecto y flujo', () => {
    expect(matchesSearch(published, 'PRESTAMO')).toBe(true)
    expect(matchesSearch(newNeed, 'soci')).toBe(true)
    expect(matchesSearch(qaReview, 'pruebas de demo-3')).toBe(true)
    expect(matchesSearch(published, 'socia')).toBe(false)
    expect(matchesSearch(published, '   ')).toBe(true)
  })
})

describe('ConversationList', () => {
  it('es una región «Conversaciones» con los grupos por día', () => {
    renderList()
    const aside = screen.getByRole('complementary', { name: 'Conversaciones' })
    expect(within(aside).getByRole('heading', { name: 'Hoy' })).toBeInTheDocument()
    expect(within(aside).getByRole('heading', { name: 'Ayer' })).toBeInTheDocument()
  })

  it('cada conversación muestra proyecto, título y «flujo · estado»', () => {
    renderList()
    const item = screen.getByRole('button', { name: /Renovar un préstamo desde la app/ })
    expect(item).toHaveTextContent('DEMO')
    expect(item).toHaveTextContent('Evolucionar DEMO-3 · Publicado')
  })

  it('retoma una conversación al pulsarla', async () => {
    const { onSelect } = renderList()
    await userEvent.click(screen.getByRole('button', { name: /Alta de persona socia en línea/ }))
    expect(onSelect).toHaveBeenCalledWith(newNeed.thread_id)
  })

  it('marca la conversación abierta', () => {
    renderList({ currentId: qaReview.thread_id })
    expect(screen.getByRole('button', { name: /Suite de pruebas de DEMO-3/ })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: /Renovar un préstamo/ })).not.toHaveAttribute('aria-current')
  })

  it('«Nueva conversación» avisa', async () => {
    const { onNew } = renderList()
    await userEvent.click(screen.getByRole('button', { name: 'Nueva conversación' }))
    expect(onNew).toHaveBeenCalledTimes(1)
  })

  it('filtra con el buscador y avisa si no hay coincidencias', async () => {
    renderList()
    const search = screen.getByRole('searchbox', { name: 'Buscar conversaciones' })
    await userEvent.type(search, 'socia')
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    await userEvent.clear(search)
    await userEvent.type(search, 'no existe')
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    expect(screen.getByRole('status')).toHaveTextContent('No hay conversaciones que coincidan con la búsqueda.')
  })

  it('vacía: solo «Nueva conversación», sin buscador (UI.md §7)', () => {
    renderList({ conversations: [] })
    expect(screen.getByRole('button', { name: 'Nueva conversación' })).toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).toBeNull()
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  })

  it('muestra los títulos como texto, nunca como HTML', () => {
    renderList({ conversations: [{ ...published, title: '<img src=x onerror=alert(1)>' }] })
    expect(screen.getByRole('button', { name: /<img src=x onerror=alert\(1\)>/ })).toBeInTheDocument()
    expect(document.querySelector('aside img')).toBeNull()
  })
})

describe('ConversationsToggle', () => {
  it('muestra u oculta la lista con aria-expanded y aria-controls', async () => {
    const onToggle = vi.fn()
    const { rerender } = render(<ConversationsToggle expanded={false} controls="convs" onToggle={onToggle} />)
    const button = screen.getByRole('button', { name: 'Mostrar conversaciones' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveAttribute('aria-controls', 'convs')
    await userEvent.click(button)
    expect(onToggle).toHaveBeenCalledTimes(1)
    rerender(<ConversationsToggle expanded controls="convs" onToggle={onToggle} />)
    expect(screen.getByRole('button', { name: 'Ocultar conversaciones' })).toHaveAttribute('aria-expanded', 'true')
  })
})
