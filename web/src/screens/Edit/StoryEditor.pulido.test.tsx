// Editar a mano, pulido final (T-56, PA-344): «¿Descartar los cambios?» sustituye al pie y a *Cancelar*, que tenía el
// foco; el foco pasa a «Seguir editando», la opción que no pierde nada. Datos del ejemplo del contrato (DEMO-3).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { example } from '../../mocks/examples.ts'
import type { UserStory } from './storyDraft.ts'
import { StoryEditorActions, StoryEditorFields } from './StoryEditor.tsx'
import { useStoryEditor } from './useStoryEditor.ts'

const story = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

function Harness({ onCancel = () => {}, controlled = false }: { onCancel?: () => void; controlled?: boolean }) {
  const editor = useStoryEditor(story())
  const [confirming, setConfirming] = useState(false)
  return (
    <>
      <StoryEditorFields editor={editor} />
      <StoryEditorActions
        editor={editor}
        version={2}
        onSave={() => {}}
        onCancel={onCancel}
        {...(controlled ? { confirming, onConfirmingChange: setConfirming } : {})}
      />
    </>
  )
}

const cancelButton = () => screen.getByRole('button', { name: 'Cancelar' })
const keepEditing = () => screen.getByRole('button', { name: 'Seguir editando' })

describe('StoryEditorActions · foco en «Seguir editando» (PA-344)', () => {
  it('test_focus_goes_to_keep_editing_when_cancel_clicked_with_changes', async () => {
    /** PA-344: *Cancelar* con cambios abre la pregunta y el foco va a «Seguir editando» (no se queda en el vacío). */
    render(<Harness />)
    await userEvent.type(screen.getByLabelText('Título'), ' ficticio')
    await userEvent.click(cancelButton())
    expect(screen.getByRole('group', { name: 'Descartar los cambios' })).toBeInTheDocument()
    await waitFor(() => expect(keepEditing()).toHaveFocus())
    expect(screen.getByRole('button', { name: 'Sí, descartar' })).not.toHaveFocus()
  })

  it('test_focus_goes_to_keep_editing_when_cancel_pressed_with_keyboard', async () => {
    /** PA-344: con el teclado (Enter sobre *Cancelar*), el foco también acaba en «Seguir editando»; Enter otra vez no descarta. */
    const onCancel = vi.fn()
    render(<Harness onCancel={onCancel} />)
    await userEvent.type(screen.getByLabelText('Nota de la edición (opcional)'), 'Nota ficticia')
    cancelButton().focus()
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(keepEditing()).toHaveFocus())
    await userEvent.keyboard('{Enter}')
    expect(screen.queryByRole('group', { name: 'Descartar los cambios' })).toBeNull()
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('test_focus_goes_to_keep_editing_when_confirmation_controlled_by_parent', async () => {
    /** PA-344: con la pregunta controlada por quien lo usa (EditPanel), *Cancelar* con cambios también enfoca «Seguir editando». */
    render(<Harness controlled />)
    await userEvent.type(screen.getByLabelText('Título'), ' ficticio')
    await userEvent.click(cancelButton())
    await waitFor(() => expect(keepEditing()).toHaveFocus())
  })

  it('test_no_confirmation_and_cancel_called_when_no_changes', async () => {
    /** PA-344 (negativa): sin cambios, *Cancelar* sale sin pregunta (no hay «Seguir editando» que enfocar). */
    const onCancel = vi.fn()
    render(<Harness onCancel={onCancel} />)
    await userEvent.click(cancelButton())
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: 'Seguir editando' })).toBeNull()
  })
})
