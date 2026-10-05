// Lista larga (más de 100 conversaciones): sin «Ver más» ni paginación, solo scroll dentro de su columna;
// «Nueva conversación», el buscador y la nota del pie no encogen. `?simular=muchas-conversaciones` en la API simulada.
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationSummary } from '../../api/types.ts'
import { manyConversations, manyConversationsFrom } from '../../mocks/db.ts'
import { ConversationList } from './ConversationList.tsx'
import css from './ConversationList.module.css?raw'

const [EXAMPLE] = examples['GET /api/v1/conversations 200'] as unknown as ConversationSummary[]
const NOW = new Date('2026-10-05T12:00:00Z')

describe('API simulada · muchas conversaciones', () => {
  it('?simular=muchas-conversaciones activa el caso; otro valor, no', () => {
    expect(manyConversationsFrom('?simular=muchas-conversaciones')).toBe(true)
    expect(manyConversationsFrom('?simular=parcial')).toBe(false)
    expect(manyConversationsFrom('')).toBe(false)
  })

  it('120 conversaciones sintéticas en 30 días, con ids únicos y claves DEMO', () => {
    const list = manyConversations(EXAMPLE as ConversationSummary, 120, NOW)
    expect(list).toHaveLength(120)
    expect(new Set(list.map((item) => item.thread_id)).size).toBe(120)
    expect(new Set(list.map((item) => item.updated_at.slice(0, 10))).size).toBe(30)
    expect(list.every((item) => item.origin_key?.startsWith('DEMO-'))).toBe(true)
  })
})

describe('Lista larga', () => {
  it('pinta las 120 conversaciones agrupadas por día, sin «Ver más» ni paginación', () => {
    const conversations = manyConversations(EXAMPLE as ConversationSummary, 120, NOW)
    render(<ConversationList conversations={conversations} onNew={vi.fn()} onSelect={vi.fn()} now={NOW} />)
    const list = screen.getByRole('complementary', { name: 'Conversaciones' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(120)
    expect(within(list).getAllByRole('heading', { level: 2 }).length).toBeGreaterThan(20)
    expect(within(list).queryByRole('button', { name: /Ver más|Cargar más|Siguiente/i })).toBeNull()
    expect(within(list).getByRole('button', { name: 'Nueva conversación' })).toBeInTheDocument()
    expect(within(list).getByRole('searchbox', { name: 'Buscar conversaciones' })).toBeInTheDocument()
  })

  it('solo se desplazan los grupos: el botón, el buscador y la nota no encogen', () => {
    const rule = (selector: string) => css.match(new RegExp(`${selector.replace('.', '\\.')}\\s*\\{([^}]*)\\}`))?.[1] ?? ''
    expect(rule('.groups')).toMatch(/overflow-y:\s*auto/)
    expect(rule('.groups')).toMatch(/min-height:\s*0/)
    expect(css).toMatch(/\.newButton,\s*\.search,\s*\.note\s*\{\s*flex-shrink:\s*0;/)
  })
})
