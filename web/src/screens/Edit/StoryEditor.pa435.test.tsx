// Editar a mano, pulido final (T-56, PA-435): con solo la nota (la HU sin cambios), el pie explica que hay que cambiar
// algún campo y *Guardar* sigue desactivado. Datos del ejemplo del contrato (DEMO-3, sintéticos).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { example } from '../../mocks/examples.ts'
import { NOTE_ONLY_HINT } from './editText.ts'
import type { UserStory } from './storyDraft.ts'
import { StoryEditorActions, StoryEditorFields } from './StoryEditor.tsx'
import { useStoryEditor } from './useStoryEditor.ts'

const story = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

const UNCHANGED_HINT = 'Aún no has cambiado nada.'

function Harness({ onSave = () => {} }: { onSave?: (content: UserStory, note: string | null) => void }) {
  const editor = useStoryEditor(story())
  return (
    <>
      <StoryEditorFields editor={editor} />
      <StoryEditorActions editor={editor} version={2} onSave={onSave} onCancel={() => {}} />
    </>
  )
}

const saveButton = () => screen.getByRole('button', { name: 'Guardar la versión 3' })
const noteBox = () => screen.getByLabelText('Nota de la edición (opcional)')

describe('StoryEditorActions · solo nota (PA-435)', () => {
  it('test_footer_says_nothing_changed_when_no_note', () => {
    /** PA-435 (negativa): sin cambios ni nota, el pie dice «Aún no has cambiado nada.» y *Guardar* lo cita. */
    render(<Harness />)
    expect(screen.getByText(UNCHANGED_HINT)).toBeInTheDocument()
    expect(screen.queryByText(NOTE_ONLY_HINT)).toBeNull()
    expect(saveButton()).toBeDisabled()
    expect(saveButton()).toHaveAccessibleDescription(expect.stringContaining(UNCHANGED_HINT))
  })

  it('test_footer_explains_note_needs_change_when_only_note', async () => {
    /** PA-435: con nota y la HU sin cambios, la frase nueva describe *Guardar*, que sigue desactivado. */
    const onSave = vi.fn()
    render(<Harness onSave={onSave} />)
    await userEvent.type(noteBox(), 'Nota ficticia sin cambios')
    expect(screen.getByText(NOTE_ONLY_HINT)).toBeInTheDocument()
    expect(screen.queryByText(UNCHANGED_HINT)).toBeNull()
    expect(saveButton()).toBeDisabled()
    expect(saveButton()).toHaveAccessibleDescription(expect.stringContaining(NOTE_ONLY_HINT))
    await userEvent.click(saveButton())
    expect(onSave).not.toHaveBeenCalled()
  })

  it('test_footer_back_to_nothing_changed_when_note_only_whitespace', async () => {
    /** PA-435 (límite): una nota de solo espacios no cuenta como nota: vuelve «Aún no has cambiado nada.». */
    render(<Harness />)
    await userEvent.type(noteBox(), '   ')
    expect(screen.getByText(UNCHANGED_HINT)).toBeInTheDocument()
    expect(screen.queryByText(NOTE_ONLY_HINT)).toBeNull()
    expect(saveButton()).toBeDisabled()
  })

  it('test_hint_gone_and_save_enabled_when_field_changed_with_note', async () => {
    /** PA-435: al cambiar un campo con la nota escrita, la frase desaparece y *Guardar* se activa. */
    render(<Harness />)
    await userEvent.type(noteBox(), 'Nota ficticia')
    await userEvent.type(screen.getByLabelText('Título'), ' ficticio')
    expect(screen.queryByText(NOTE_ONLY_HINT)).toBeNull()
    expect(screen.queryByText(UNCHANGED_HINT)).toBeNull()
    expect(saveButton()).toBeEnabled()
  })
})
