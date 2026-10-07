// Editar a mano, parte B (T-56, RF-32): el pie del editor (`StoryEditorActions`) con la nota plegada en ventanas
// estrechas y la confirmación controlada. `matchMedia` simulado. Datos del ejemplo del contrato (DEMO-3, sintéticos).
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { NARROW_QUERY } from '../../components/ConversationList/ConversationList.tsx'
import { example } from '../../mocks/examples.ts'
import type { UserStory } from './storyDraft.ts'
import { StoryEditorActions, StoryEditorFields } from './StoryEditor.tsx'
import { useStoryEditor } from './useStoryEditor.ts'

const story = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

/** Doble de `matchMedia`: `NARROW_QUERY` se cumple según `narrow`; `setNarrow` avisa a quien escucha («change»). */
function fakeMatchMedia(initial: boolean) {
  let narrow = initial
  const listeners = new Set<() => void>()
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() {
      return query === NARROW_QUERY && narrow
    },
    media: query,
    onchange: null,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }))
  return {
    setNarrow(next: boolean) {
      narrow = next
      act(() => {
        for (const listener of [...listeners]) listener()
      })
    },
  }
}

interface HarnessProps {
  onSave?: (content: UserStory, note: string | null) => void
  onCancel?: () => void
}

function Harness({ onSave = () => {}, onCancel = () => {} }: HarnessProps) {
  const editor = useStoryEditor(story())
  return (
    <>
      <StoryEditorFields editor={editor} />
      <StoryEditorActions editor={editor} version={2} onSave={onSave} onCancel={onCancel} />
    </>
  )
}

const noteBox = () => screen.queryByLabelText('Nota de la edición (opcional)')
const addNote = () => screen.queryByRole('button', { name: 'Añadir una nota' })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('StoryEditorActions · nota plegada en ventanas estrechas (parte B)', () => {
  it('test_note_folded_behind_button_when_narrow', () => {
    /** CA 8: con `(max-width: 1023.98px)` cierto, la nota está tras «Añadir una nota». */
    fakeMatchMedia(true)
    render(<Harness />)
    expect(addNote()).toBeInTheDocument()
    expect(noteBox()).toBeNull()
  })

  it('test_note_appears_with_focus_when_add_note_clicked', async () => {
    /** CA 8: al pulsar «Añadir una nota» aparece la nota con el foco. */
    fakeMatchMedia(true)
    render(<Harness />)
    await userEvent.click(addNote() as HTMLElement)
    expect(addNote()).toBeNull()
    expect(noteBox()).toHaveFocus()
    expect(screen.getByText('0 de 1000')).toBeInTheDocument()
  })

  it('test_note_with_text_not_folded_when_window_narrows', async () => {
    /** CA 8: con texto en la nota, no se pliega aunque la ventana pase a estrecha. */
    const media = fakeMatchMedia(false)
    render(<Harness />)
    await userEvent.type(noteBox() as HTMLElement, 'Nota ficticia')
    media.setNarrow(true)
    expect(addNote()).toBeNull()
    expect(noteBox()).toHaveValue('Nota ficticia')
  })

  it('test_note_stays_open_when_emptied_after_opening', async () => {
    /** CA 8 (límite): abierta con el botón, vaciarla no la vuelve a plegar (no desaparece bajo el cursor). */
    fakeMatchMedia(true)
    render(<Harness />)
    await userEvent.click(addNote() as HTMLElement)
    await userEvent.type(noteBox() as HTMLElement, 'x')
    await userEvent.clear(noteBox() as HTMLElement)
    expect(noteBox()).toBeInTheDocument()
    expect(addNote()).toBeNull()
  })

  it('test_note_folds_when_window_narrows_and_note_empty', () => {
    /** CA 8: ancha, la nota se ve; al estrecharse sin texto, se pliega tras «Añadir una nota». */
    const media = fakeMatchMedia(false)
    render(<Harness />)
    expect(noteBox()).toBeInTheDocument()
    media.setNarrow(true)
    expect(addNote()).toBeInTheDocument()
    expect(noteBox()).toBeNull()
  })

  it('test_note_never_folded_when_wide', () => {
    /** CA 8: en ventana ancha (la consulta no se cumple), la nota nunca se pliega. */
    fakeMatchMedia(false)
    render(<Harness />)
    expect(noteBox()).toBeInTheDocument()
    expect(addNote()).toBeNull()
  })

  it('test_note_never_folded_when_match_media_missing', () => {
    /** CA 8 (límite): sin `matchMedia` (jsdom), ventana ancha: la nota se ve. */
    vi.stubGlobal('matchMedia', undefined)
    render(<Harness />)
    expect(noteBox()).toBeInTheDocument()
    expect(addNote()).toBeNull()
  })

  it('test_folded_note_saved_as_null_when_never_opened', async () => {
    /** CA 8 + CA 1: plegada y sin abrir, guardar envía la nota como null. */
    fakeMatchMedia(true)
    const onSave = vi.fn<(content: UserStory, note: string | null) => void>()
    render(<Harness onSave={onSave} />)
    await userEvent.type(screen.getByLabelText('Título'), ' bis')
    await userEvent.click(screen.getByRole('button', { name: 'Guardar la versión 3' }))
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave.mock.calls[0]?.[1]).toBeNull()
  })
})

describe('StoryEditorActions · confirmación controlada (parte B)', () => {
  function Controlled({ onCancel, onConfirmingChange }: { onCancel: () => void; onConfirmingChange: (next: boolean) => void }) {
    const editor = useStoryEditor(story())
    const [confirming, setConfirming] = useState(true)
    return (
      <StoryEditorActions
        editor={editor}
        version={2}
        onSave={() => {}}
        onCancel={onCancel}
        confirming={confirming}
        onConfirmingChange={(next) => {
          onConfirmingChange(next)
          setConfirming(next)
        }}
      />
    )
  }

  it('test_controlled_confirmation_shown_when_parent_says_so', async () => {
    /** CA 7: quien lo usa abre «¿Descartar los cambios?»; «Seguir editando» avisa con false. */
    const onConfirmingChange = vi.fn<(next: boolean) => void>()
    const onCancel = vi.fn<() => void>()
    render(<Controlled onCancel={onCancel} onConfirmingChange={onConfirmingChange} />)
    expect(screen.getByRole('group', { name: 'Descartar los cambios' })).toHaveTextContent('La versión 2 se queda como está.')
    await userEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(onConfirmingChange).toHaveBeenCalledWith(false)
    expect(screen.queryByRole('group', { name: 'Descartar los cambios' })).toBeNull()
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('test_controlled_confirmation_cancels_when_discard_confirmed', async () => {
    /** CA 7: «Sí, descartar» llama a onCancel. */
    const onCancel = vi.fn<() => void>()
    render(<Controlled onCancel={onCancel} onConfirmingChange={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
