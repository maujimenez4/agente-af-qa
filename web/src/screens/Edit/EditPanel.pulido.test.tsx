// Editar a mano, pulido final (T-56, PA-344): `EditPanel` aislado. `saveRef` (lo que usa *Reintentar*) guarda lo que hay
// ahora en el editor y devuelve `false` sin guardar si no se puede (errores, sin cambios o guardando); `closeGuardRef`
// acepta qué hacer tras «Sí, descartar» y lo olvida con «Seguir editando». Datos del ejemplo del contrato (DEMO-3).
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { example } from '../../mocks/examples.ts'
import { EditPanel, type EditCloseGuard } from './EditPanel.tsx'
import type { UserStory } from './storyDraft.ts'

const story = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

const NEW_TITLE = 'Renovar un préstamo ficticio'

function setup({ busy = false }: { busy?: boolean } = {}) {
  const onSave = vi.fn<(content: UserStory, note: string | null) => void>()
  const onCancel = vi.fn()
  const onClosePanel = vi.fn()
  const closeGuardRef = createRef<EditCloseGuard | null>()
  const saveRef = createRef<(() => boolean) | null>()
  const props = { title: 'Evolucionar DEMO-3', story: story(), version: 2, onSave, onCancel, closeGuardRef, saveRef, onClosePanel }
  const view = render(<EditPanel {...props} busy={busy} />)
  return { ...props, rerender: (next: { busy: boolean }) => view.rerender(<EditPanel {...props} busy={next.busy} />), unmount: view.unmount }
}

const titleInput = () => screen.getByLabelText('Título')
const noteBox = () => screen.getByLabelText('Nota de la edición (opcional)')
const confirmGroup = () => screen.queryByRole('group', { name: 'Descartar los cambios' })

async function changeTitle(value: string) {
  await userEvent.clear(titleInput())
  if (value) await userEvent.type(titleInput(), value)
}

/** Llama a `saveRef` como lo hace *Reintentar* en Iterar. */
const callSave = (ref: { current: (() => boolean) | null }) => {
  let result: boolean | undefined
  act(() => {
    result = ref.current?.()
  })
  return result
}

describe('EditPanel · saveRef para Reintentar (PA-344)', () => {
  it('test_save_ref_returns_false_and_does_not_save_when_required_field_empty', async () => {
    /** PA-344 (negativa): con el título vaciado (error «La HU necesita un título.»), `saveRef` devuelve false y no llama a onSave. */
    const { saveRef, onSave } = setup()
    await changeTitle('')
    expect(screen.getAllByText('La HU necesita un título.').length).toBeGreaterThan(0)
    expect(callSave(saveRef)).toBe(false)
    expect(onSave).not.toHaveBeenCalled()
  })

  it('test_save_ref_returns_false_when_nothing_changed', () => {
    /** PA-344 (límite): sin cambios (error `unchanged`), `saveRef` no guarda. */
    const { saveRef, onSave } = setup()
    expect(callSave(saveRef)).toBe(false)
    expect(onSave).not.toHaveBeenCalled()
  })

  it('test_save_ref_returns_false_when_only_note', async () => {
    /** PA-344 + PA-435 (límite): solo con nota (HU sin cambios), `saveRef` tampoco guarda. */
    const { saveRef, onSave } = setup()
    await userEvent.type(noteBox(), 'Nota ficticia')
    expect(callSave(saveRef)).toBe(false)
    expect(onSave).not.toHaveBeenCalled()
  })

  it('test_save_ref_saves_current_content_and_trimmed_note_when_valid', async () => {
    /** PA-344: con cambios válidos, `saveRef` devuelve true y guarda el contenido actual con la nota recortada. */
    const { saveRef, onSave } = setup()
    await changeTitle(NEW_TITLE)
    await userEvent.type(noteBox(), '  Nota ficticia  ')
    expect(callSave(saveRef)).toBe(true)
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave.mock.calls[0]?.[0].title).toBe(NEW_TITLE)
    expect(onSave.mock.calls[0]?.[1]).toBe('Nota ficticia')
  })

  it('test_save_ref_sends_null_note_when_note_blank', async () => {
    /** PA-344: sin nota (o solo espacios), la nota se envía como null. */
    const { saveRef, onSave } = setup()
    await changeTitle(NEW_TITLE)
    await userEvent.type(noteBox(), '   ')
    expect(callSave(saveRef)).toBe(true)
    expect(onSave.mock.calls[0]?.[1]).toBeNull()
  })

  it('test_save_ref_uses_latest_edit_not_first_value', async () => {
    /** PA-344: si el campo cambia otra vez, `saveRef` envía el último valor, no el del primer intento. */
    const { saveRef, onSave } = setup()
    await changeTitle(NEW_TITLE)
    await changeTitle(`${NEW_TITLE} corregido`)
    callSave(saveRef)
    expect(onSave.mock.calls[0]?.[0].title).toBe(`${NEW_TITLE} corregido`)
  })

  it('test_save_ref_returns_false_when_busy', async () => {
    /** PA-344 (negativa): guardando (`busy`), `saveRef` no envía otra vez. */
    const view = setup()
    await changeTitle(NEW_TITLE)
    view.rerender({ busy: true })
    expect(callSave(view.saveRef)).toBe(false)
    expect(view.onSave).not.toHaveBeenCalled()
  })

  it('test_save_ref_cleared_when_editor_unmounted', () => {
    /** PA-344: al cerrar el editor, `saveRef` vuelve a null (Iterar solo cierra la tarjeta al reintentar). */
    const { saveRef, closeGuardRef, unmount } = setup()
    expect(saveRef.current).toBeTypeOf('function')
    unmount()
    expect(saveRef.current).toBeNull()
    expect(closeGuardRef.current).toBeNull()
  })
})

describe('EditPanel · closeGuardRef con «después» (PA-344)', () => {
  const guard = (ref: { current: EditCloseGuard | null }, after?: () => void) => {
    let result: boolean | undefined
    act(() => {
      result = ref.current?.(after)
    })
    return result
  }

  it('test_guard_returns_true_without_asking_when_clean', () => {
    /** PA-344: sin cambios, el guardián devuelve true y no pregunta. */
    const { closeGuardRef } = setup()
    const after = vi.fn()
    expect(guard(closeGuardRef, after)).toBe(true)
    expect(confirmGroup()).toBeNull()
    expect(after).not.toHaveBeenCalled()
  })

  it('test_discard_runs_after_instead_of_folding_when_guard_given_after', async () => {
    /** PA-344: con cambios y `after`, «Sí, descartar» sale del editor y hace `after`; no pliega el panel. */
    const { closeGuardRef, onCancel, onClosePanel } = setup()
    await changeTitle(NEW_TITLE)
    const after = vi.fn()
    expect(guard(closeGuardRef, after)).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(after).toHaveBeenCalledTimes(1)
    expect(onClosePanel).not.toHaveBeenCalled()
  })

  it('test_discard_folds_panel_when_guard_called_without_after', async () => {
    /** PA-335 + PA-344: sin `after` (Esc, velo, *Cerrar*), «Sí, descartar» pliega el panel. */
    const { closeGuardRef, onCancel, onClosePanel } = setup()
    await changeTitle(NEW_TITLE)
    guard(closeGuardRef)
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onClosePanel).toHaveBeenCalledTimes(1)
  })

  it('test_keep_editing_forgets_after_so_later_cancel_does_not_run_it', async () => {
    /** PA-344 (negativa): tras «Seguir editando», *Cancelar* + «Sí, descartar» del pie no ejecuta el `after` olvidado. */
    const { closeGuardRef, onCancel, onClosePanel } = setup()
    await changeTitle(NEW_TITLE)
    const after = vi.fn()
    guard(closeGuardRef, after)
    await userEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(after).not.toHaveBeenCalled()
    expect(onClosePanel).not.toHaveBeenCalled()
  })

  it('test_guard_returns_false_without_asking_when_busy', async () => {
    /** PA-344: guardando, el guardián devuelve false y no abre la pregunta. */
    const view = setup()
    await changeTitle(NEW_TITLE)
    view.rerender({ busy: true })
    const after = vi.fn()
    expect(guard(view.closeGuardRef, after)).toBe(false)
    expect(confirmGroup()).toBeNull()
    expect(after).not.toHaveBeenCalled()
  })

  it('test_guard_moves_focus_to_keep_editing_when_dirty', async () => {
    /** PA-344: la pregunta abierta desde fuera del pie lleva el foco a «Seguir editando». */
    const { closeGuardRef } = setup()
    await changeTitle(NEW_TITLE)
    guard(closeGuardRef, () => {})
    await waitFor(() => expect(screen.getByRole('button', { name: 'Seguir editando' })).toHaveFocus())
  })
})
