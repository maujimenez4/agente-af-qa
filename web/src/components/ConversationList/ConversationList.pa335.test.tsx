// PA-335: la lista de conversaciones en ventanas estrechas (DESIGN-DECISIONS.md §4 bis, «Lista de conversaciones en
// ventanas estrechas»; UI.md §2, «Ventanas estrechas»). Datos sintéticos (proyecto DEMO).
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEMO_CONVERSATIONS, DEMO_NOW } from '../../fixtures/conversations.ts'
import { ConversationList, NARROW_QUERY } from './ConversationList.tsx'

/** Doble de `matchMedia`: solo `NARROW_QUERY` responde a `narrow`; «change» se dispara como en el navegador. */
function fakeMatchMedia(initial: boolean) {
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
  return {
    change(next: boolean) {
      narrow = next
      act(() => {
        for (const listener of [...listeners]) listener()
      })
    },
  }
}

function renderList() {
  const onNew = vi.fn()
  const onSelect = vi.fn()
  render(<ConversationList id="convs" conversations={DEMO_CONVERSATIONS} onNew={onNew} onSelect={onSelect} now={DEMO_NOW} />)
  return { onNew, onSelect }
}

const toggle = () => screen.getByRole('button', { name: 'Conversaciones' })
const list = () => document.getElementById('convs') as HTMLElement

async function openList() {
  await userEvent.click(toggle())
  return screen.getByRole('dialog', { name: 'Conversaciones' })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PA-335: lista de conversaciones por debajo de 1024 px', () => {
  it('test_toggle_visible_and_list_hidden_when_narrow: botón «Conversaciones» plegado y lista oculta', () => {
    fakeMatchMedia(true)
    renderList()
    const button = toggle()
    expect(button).toHaveAccessibleName('Conversaciones')
    expect(button).toHaveAttribute('title', 'Conversaciones')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(button).toHaveAttribute('aria-controls', 'convs')
    expect(list()).toHaveAttribute('hidden')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('test_list_opens_as_dialog_with_focus_when_toggle_clicked: diálogo modal con el foco dentro', async () => {
    fakeMatchMedia(true)
    renderList()
    const dialog = await openList()
    expect(toggle()).toHaveAttribute('aria-expanded', 'true')
    expect(dialog).toBe(list())
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).not.toHaveAttribute('hidden')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    expect(screen.getByRole('button', { name: 'Nueva conversación' })).toHaveFocus()
  })

  it('test_list_closes_and_focus_returns_when_escape: Esc la cierra y el foco vuelve al botón', async () => {
    fakeMatchMedia(true)
    renderList()
    await openList()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(list()).toHaveAttribute('hidden')
    expect(toggle()).toHaveAttribute('aria-expanded', 'false')
    expect(toggle()).toHaveFocus()
  })

  it('test_list_closes_when_backdrop_clicked: un clic en el velo la cierra', async () => {
    fakeMatchMedia(true)
    renderList()
    const dialog = await openList()
    const backdrop = dialog.previousElementSibling as HTMLElement
    expect(backdrop).toHaveAttribute('aria-hidden', 'true')
    await userEvent.click(backdrop)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(toggle()).toHaveAttribute('aria-expanded', 'false')
    expect(toggle()).toHaveFocus()
  })

  it('test_list_closes_when_toggle_clicked_again: el mismo botón la cierra', async () => {
    fakeMatchMedia(true)
    renderList()
    await openList()
    await userEvent.click(toggle())
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(toggle()).toHaveAttribute('aria-expanded', 'false')
  })

  it('test_focus_stays_inside_when_tab_and_shift_tab: Tab y Mayús+Tab dan la vuelta dentro de la lista', async () => {
    fakeMatchMedia(true)
    renderList()
    const dialog = await openList()
    const first = screen.getByRole('button', { name: 'Nueva conversación' })
    const threads = screen.getAllByRole('listitem')
    const last = threads.at(-1)?.querySelector('button') as HTMLElement
    expect(first).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(last).toHaveFocus()
    await userEvent.tab()
    expect(first).toHaveFocus()
    // Una vuelta completa hacia delante no sale nunca de la lista.
    for (let step = 0; step < threads.length + 3; step += 1) {
      await userEvent.tab()
      expect(dialog).toContainElement(document.activeElement as HTMLElement)
    }
  })

  it('test_list_closes_and_calls_select_when_conversation_chosen: elegir una conversación cierra la capa', async () => {
    fakeMatchMedia(true)
    const { onSelect } = renderList()
    await openList()
    await userEvent.click(screen.getByRole('button', { name: /Alta de persona socia en línea/ }))
    expect(onSelect).toHaveBeenCalledWith(DEMO_CONVERSATIONS[2]?.thread_id)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(toggle()).toHaveAttribute('aria-expanded', 'false')
    expect(toggle()).toHaveFocus()
  })

  it('test_list_closes_and_calls_new_when_new_conversation: «Nueva conversación» cierra la capa', async () => {
    fakeMatchMedia(true)
    const { onNew } = renderList()
    await openList()
    await userEvent.click(screen.getByRole('button', { name: 'Nueva conversación' }))
    expect(onNew).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(toggle()).toHaveFocus()
  })

  it('test_list_back_in_place_when_window_widens: al ensancharse vuelve a su sitio sin botón ni diálogo', async () => {
    const media = fakeMatchMedia(true)
    renderList()
    await openList()
    media.change(false)
    expect(screen.queryByRole('button', { name: 'Conversaciones' })).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(list()).not.toHaveAttribute('hidden')
    expect(list()).not.toHaveAttribute('aria-modal')
    expect(list()).not.toHaveAttribute('tabindex')
    expect(list()).not.toHaveAttribute('data-layer')
    expect(screen.getByRole('complementary', { name: 'Conversaciones' })).toBe(list())
  })

  it('test_list_starts_folded_when_narrowed_again: si se estrecha otra vez, empieza plegada', async () => {
    const media = fakeMatchMedia(true)
    renderList()
    await openList()
    media.change(false)
    media.change(true)
    expect(toggle()).toHaveAttribute('aria-expanded', 'false')
    expect(list()).toHaveAttribute('hidden')
  })

  it('test_list_unchanged_when_match_media_false: con matchMedia falso, lista en su sitio y sin botón', async () => {
    fakeMatchMedia(false)
    const { onSelect } = renderList()
    expect(screen.queryByRole('button', { name: 'Conversaciones' })).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(list()).not.toHaveAttribute('hidden')
    expect(list()).not.toHaveAttribute('data-layer')
    await userEvent.click(screen.getByRole('button', { name: /Alta de persona socia en línea/ }))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(list()).not.toHaveAttribute('hidden')
  })

  it('test_list_unchanged_when_match_media_missing: sin matchMedia (jsdom) todo sigue como antes', async () => {
    vi.stubGlobal('matchMedia', undefined)
    renderList()
    expect(screen.queryByRole('button', { name: 'Conversaciones' })).toBeNull()
    expect(list()).not.toHaveAttribute('hidden')
    // Esc fuera de la capa no hace nada.
    screen.getByRole('button', { name: 'Nueva conversación' }).focus()
    await userEvent.keyboard('{Escape}')
    expect(list()).not.toHaveAttribute('hidden')
    expect(screen.getByRole('button', { name: 'Nueva conversación' })).toHaveFocus()
  })

  it('test_focus_kept_in_search_when_typing_in_open_layer: escribir en el buscador no devuelve el foco al primer control', async () => {
    fakeMatchMedia(true)
    renderList()
    await openList()
    const search = screen.getByRole('searchbox', { name: 'Buscar conversaciones' })
    await userEvent.click(search)
    await userEvent.type(search, 'socia')
    expect(search).toHaveValue('socia')
    expect(search).toHaveFocus()
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
  })
})
