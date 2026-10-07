// PA-343 · huecos del `inert` bajo la lista en capa (pulido 2 de T-56): al ensancharse la ventana con la lista
// abierta, al elegir una conversación o «Nueva conversación», si la lista se desmonta abierta y si el área de
// trabajo ya era `inert`. La media query se cambia a mano (sin reloj). Datos sintéticos (DEMO).
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEMO_CONVERSATIONS, DEMO_NOW } from '../../fixtures/conversations.ts'
import { ConversationList, NARROW_QUERY } from './ConversationList.tsx'

/** `matchMedia` con avisos de cambio: `setNarrow` simula estrechar o ensanchar la ventana. */
function controllableMatchMedia(initial: boolean) {
  let narrow = initial
  const listeners = new Set<() => void>()
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      get matches() {
        return query === NARROW_QUERY && narrow
      },
      media: query,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    })),
  )
  return (next: boolean) =>
    act(() => {
      narrow = next
      for (const listener of [...listeners]) listener()
    })
}

function Frame({ showList = true, onSelect = vi.fn(), onNew = vi.fn(), workInert = false }) {
  return (
    <div>
      {showList && <ConversationList id="convs" conversations={DEMO_CONVERSATIONS} onNew={onNew} onSelect={onSelect} now={DEMO_NOW} />}
      <main data-testid="trabajo" inert={workInert || undefined}>
        <button type="button">Acción ficticia del área de trabajo</button>
      </main>
    </div>
  )
}

const toggle = () => screen.getByRole('button', { name: 'Conversaciones' })
const work = () => screen.getByTestId('trabajo')

async function openList() {
  await userEvent.click(toggle())
  expect(screen.getByRole('dialog', { name: 'Conversaciones' })).toBeInTheDocument()
  expect(work()).toHaveAttribute('inert')
}

afterEach(() => vi.unstubAllGlobals())

describe('ConversationList · inert bajo la lista en capa (PA-343, pulido 2)', () => {
  it('test_inert_removed_when_window_widens_with_list_open', async () => {
    /** PA-343 + PA-335: al ensancharse la ventana con la lista abierta, deja de ser capa y se quita `inert`. */
    const setNarrow = controllableMatchMedia(true)
    render(<Frame />)
    await openList()
    setNarrow(false)
    expect(screen.queryByRole('dialog', { name: 'Conversaciones' })).not.toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Conversaciones' })).toBeInTheDocument()
    expect(work()).not.toHaveAttribute('inert')
  })

  it('test_list_folded_and_no_inert_when_window_narrows_again', async () => {
    /** PA-335 + PA-343: tras ensanchar y volver a estrechar, la lista empieza plegada y no se marca nada. */
    const setNarrow = controllableMatchMedia(true)
    render(<Frame />)
    await openList()
    setNarrow(false)
    setNarrow(true)
    expect(screen.queryByRole('dialog', { name: 'Conversaciones' })).not.toBeInTheDocument()
    expect(toggle()).toHaveAttribute('aria-expanded', 'false')
    expect(work()).not.toHaveAttribute('inert')
  })

  it('test_inert_removed_when_conversation_selected_from_layer', async () => {
    /** PA-343: elegir una conversación desde la capa la cierra, quita `inert` y avisa con su id. */
    controllableMatchMedia(true)
    const onSelect = vi.fn()
    render(<Frame onSelect={onSelect} />)
    await openList()
    const dialog = screen.getByRole('dialog', { name: 'Conversaciones' })
    const item = within(dialog).getAllByRole('button').find((button) => button.textContent !== 'Nueva conversación')
    if (!item) throw new Error('No hay conversaciones en la capa')
    await userEvent.click(item)
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog', { name: 'Conversaciones' })).not.toBeInTheDocument()
    expect(work()).not.toHaveAttribute('inert')
  })

  it('test_inert_removed_when_new_conversation_clicked_from_layer', async () => {
    /** PA-343: «Nueva conversación» desde la capa la cierra y quita `inert`. */
    controllableMatchMedia(true)
    const onNew = vi.fn()
    render(<Frame onNew={onNew} />)
    await openList()
    await userEvent.click(screen.getByRole('button', { name: 'Nueva conversación' }))
    expect(onNew).toHaveBeenCalledTimes(1)
    expect(work()).not.toHaveAttribute('inert')
  })

  it('test_inert_removed_when_list_unmounted_open', async () => {
    /** PA-343: si la lista se desmonta con la capa abierta, el área de trabajo no se queda `inert`. */
    controllableMatchMedia(true)
    const { rerender } = render(<Frame />)
    await openList()
    rerender(<Frame showList={false} />)
    expect(work()).not.toHaveAttribute('inert')
  })

  it('test_foreign_inert_on_work_area_kept_after_close', async () => {
    /** PA-343: si el área de trabajo ya era `inert` (ajeno a la lista), cerrar la capa no se lo quita. */
    controllableMatchMedia(true)
    render(<Frame workInert />)
    await userEvent.click(toggle())
    expect(screen.getByRole('dialog', { name: 'Conversaciones' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Conversaciones' })).not.toBeInTheDocument()
    expect(work()).toHaveAttribute('inert')
  })

  it('test_strip_and_backdrop_never_inert_while_open', async () => {
    /** PA-343: la franja (botón) y el velo, que van antes de la lista, no se marcan. */
    controllableMatchMedia(true)
    render(<Frame />)
    await openList()
    expect(toggle().closest('[inert]')).toBeNull()
    const backdrop = document.querySelector('[aria-hidden="true"][class*="backdrop"]')
    expect(backdrop).not.toBeNull()
    expect(backdrop?.closest('[inert]')).toBeNull()
  })
})
