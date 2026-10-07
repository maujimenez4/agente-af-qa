// Editar a mano, parte A (T-56, RF-32, PA-340): formulario y pie del editor con el hook real. Datos del ejemplo del
// contrato (DEMO-3, sintéticos). Todo texto, nunca HTML.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { example } from '../../mocks/examples.ts'
import type { UserStory } from './storyDraft.ts'
import { StoryEditorActions, StoryEditorFields } from './StoryEditor.tsx'
import { useStoryEditor } from './useStoryEditor.ts'

const story = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

interface HarnessProps {
  original: UserStory
  busy?: boolean
  reviewError?: string | null
  onSave: (content: UserStory, note: string | null) => void
  onCancel: () => void
}

function Harness({ original, busy, reviewError, onSave, onCancel }: HarnessProps) {
  const editor = useStoryEditor(original)
  return (
    <>
      <StoryEditorFields editor={editor} reviewError={reviewError} />
      <StoryEditorActions editor={editor} version={2} busy={busy} onSave={onSave} onCancel={onCancel} />
    </>
  )
}

function setup(props: Partial<HarnessProps> = {}) {
  const onSave = vi.fn<(content: UserStory, note: string | null) => void>()
  const onCancel = vi.fn<() => void>()
  const user = userEvent.setup()
  const original = props.original ?? story()
  render(<Harness original={original} onSave={onSave} onCancel={onCancel} {...props} />)
  return { user, onSave, onCancel, original }
}

const saveButton = () => screen.getByRole('button', { name: /Guardar la versión 3|Guardando…/ })
const titleInput = () => screen.getByLabelText('Título')
const criterion = (id: string) => screen.getByRole('listitem', { name: id })
const criterionIds = () =>
  within(screen.getByRole('region', { name: 'Criterios de aceptación' }))
    .getAllByRole('listitem')
    .map((item) => item.getAttribute('aria-label'))

describe('StoryEditor · guardar', () => {
  it('editar el título y guardar llama a onSave con el contenido nuevo y null sin nota', async () => {
    /** onSave(content, null) sin nota. */
    const { user, onSave, original } = setup()
    await user.clear(titleInput())
    await user.type(titleInput(), 'Renovar un préstamo ficticio')
    await user.click(saveButton())
    expect(onSave).toHaveBeenCalledTimes(1)
    const [content, note] = onSave.mock.calls[0]!
    expect(note).toBeNull()
    expect(content).toEqual({ ...original, title: 'Renovar un préstamo ficticio' })
  })

  it('con nota, onSave recibe la nota recortada', async () => {
    /** onSave(content, nota recortada). */
    const { user, onSave } = setup()
    await user.type(titleInput(), ' bis')
    await user.type(screen.getByLabelText('Nota de la edición (opcional)'), '   nota ficticia   ')
    expect(screen.getByText('13 de 1000')).toBeInTheDocument()
    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[1]).toBe('nota ficticia')
  })

  it('una nota solo con espacios se envía como null', async () => {
    /** Nota vacía tras recortar → null. */
    const { user, onSave } = setup()
    await user.type(titleInput(), ' bis')
    await user.type(screen.getByLabelText('Nota de la edición (opcional)'), '    ')
    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[1]).toBeNull()
  })

  it('cambiar la prioridad habilita guardar y la envía', async () => {
    /** Campo Prioridad editable. */
    const { user, onSave } = setup()
    await user.selectOptions(screen.getByLabelText('Prioridad'), 'Could')
    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[0].priority).toBe('Could')
  })
})

describe('StoryEditor · Guardar desactivado', () => {
  it('sin cambios: desactivado y «Aún no has cambiado nada.» sin la lista de errores', () => {
    /** Sin cambios → unchanged, no se lista en «Antes de guardar:». */
    setup()
    expect(saveButton()).toBeDisabled()
    expect(screen.getByText('Aún no has cambiado nada.')).toBeInTheDocument()
    expect(screen.queryByText('Antes de guardar:')).not.toBeInTheDocument()
  })

  it('con un error: desactivado y el error en «Antes de guardar:»', async () => {
    /** Errores bloquean Guardar y se listan. */
    const { user } = setup()
    await user.clear(titleInput())
    expect(saveButton()).toBeDisabled()
    const summary = screen.getByText('Antes de guardar:').parentElement!
    expect(within(summary).getByText('La HU necesita un título.')).toBeInTheDocument()
    expect(screen.queryByText('Aún no has cambiado nada.')).not.toBeInTheDocument()
  })

  it('el error marca el campo con aria-invalid y lo describe con su mensaje', async () => {
    /** Error en un campo → aria-invalid y aria-describedby al mensaje. */
    const { user } = setup()
    expect(titleInput()).not.toHaveAttribute('aria-invalid')
    await user.clear(titleInput())
    expect(titleInput()).toHaveAttribute('aria-invalid', 'true')
    expect(titleInput()).toHaveAccessibleDescription('La HU necesita un título.')
  })

  it('una nota de más de 1000 caracteres bloquea guardar y marca la nota', async () => {
    /** Nota > 1000 → error. */
    const { user } = setup()
    await user.type(titleInput(), ' bis')
    const note = screen.getByLabelText('Nota de la edición (opcional)')
    await user.click(note)
    await user.paste('n'.repeat(1001))
    expect(screen.getByText('1001 de 1000')).toBeInTheDocument()
    expect(note).toHaveAttribute('aria-invalid', 'true')
    expect(saveButton()).toBeDisabled()
    expect(screen.getByText('La nota no puede pasar de 1000 caracteres.')).toBeInTheDocument()
  })

  it('una nota de exactamente 1000 caracteres permite guardar', async () => {
    /** Límite: 1000 sí. */
    const { user } = setup()
    await user.type(titleInput(), ' bis')
    await user.click(screen.getByLabelText('Nota de la edición (opcional)'))
    await user.paste('n'.repeat(1000))
    expect(saveButton()).toBeEnabled()
  })
})

describe('StoryEditor · avisos', () => {
  it('un aviso no desactiva Guardar y el campo no tiene aria-invalid', async () => {
    /** Avisos no bloquean; un aviso NO pone aria-invalid. */
    const { user } = setup()
    await user.clear(screen.getByLabelText('Como'))
    const role = screen.getByLabelText('Como')
    expect(role).not.toHaveAttribute('aria-invalid')
    expect(role).toHaveAccessibleDescription('«Como» está vacío.')
    expect(saveButton()).toBeEnabled()
    expect(screen.getByText('Revisa también')).toBeInTheDocument()
    expect(screen.queryByText('Antes de guardar:')).not.toBeInTheDocument()
  })

  it('título con espacios al final: aviso sin aria-invalid', async () => {
    /** Aviso de título con espacios. */
    const { user } = setup()
    await user.type(titleInput(), '  ')
    expect(titleInput()).not.toHaveAttribute('aria-invalid')
    expect(screen.getAllByText('El título empieza o acaba con espacios.').length).toBeGreaterThan(0)
    expect(saveButton()).toBeEnabled()
  })
})

describe('StoryEditor · criterios de aceptación', () => {
  it('añadir un CA crea CA-03 vacío que bloquea hasta rellenarlo', async () => {
    /** Añadir CA-03 y rellenarlo habilita guardar. */
    const { user, onSave } = setup()
    await user.click(screen.getByRole('button', { name: 'Añadir un criterio' }))
    expect(criterionIds()).toEqual(['CA-01', 'CA-02', 'CA-03'])
    expect(saveButton()).toBeDisabled()
    const added = within(criterion('CA-03'))
    expect(added.getByLabelText('Título de CA-03')).toHaveAttribute('aria-invalid', 'true')

    await user.type(added.getByLabelText('Título de CA-03'), 'Renovación ficticia')
    await user.type(added.getByLabelText('Dado'), 'un préstamo ficticio{Enter}{Enter}otro paso')
    await user.type(added.getByLabelText('Cuando'), 'se pulsa «Renovar»')
    expect(saveButton()).toBeDisabled()
    await user.type(added.getByLabelText('Entonces'), 'se amplía el plazo')
    expect(saveButton()).toBeEnabled()

    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[0].acceptance_criteria[2]).toEqual({
      id: 'CA-03',
      title: 'Renovación ficticia',
      given: ['un préstamo ficticio', 'otro paso'],
      when: ['se pulsa «Renovar»'],
      then: ['se amplía el plazo'],
    })
  })

  it('los botones por CA tienen nombre accesible con su id', () => {
    /** Nombres accesibles «Subir CA-01»… */
    setup()
    for (const id of ['CA-01', 'CA-02']) {
      for (const action of ['Subir', 'Bajar', 'Quitar']) {
        expect(screen.getByRole('button', { name: `${action} ${id}` })).toBeInTheDocument()
      }
    }
  })

  it('Subir desactivado en el primero y Bajar en el último', () => {
    /** Límites del reordenado. */
    setup()
    expect(screen.getByRole('button', { name: 'Subir CA-01' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Bajar CA-01' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Subir CA-02' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Bajar CA-02' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Subir RN-01' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Bajar RN-02' })).toBeDisabled()
  })

  it('Bajar y Subir con el teclado reordenan los CA', async () => {
    /** Subir/Bajar por teclado. */
    const { user, onSave } = setup()
    screen.getByRole('button', { name: 'Bajar CA-01' }).focus()
    await user.keyboard('{Enter}')
    expect(criterionIds()).toEqual(['CA-02', 'CA-01'])
    screen.getByRole('button', { name: 'Subir CA-01' }).focus()
    await user.keyboard(' ')
    expect(criterionIds()).toEqual(['CA-01', 'CA-02'])
    screen.getByRole('button', { name: 'Subir CA-02' }).focus()
    await user.keyboard('{Enter}')
    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[0].acceptance_criteria.map((item) => item.id)).toEqual(['CA-02', 'CA-01'])
  })

  it('Quitar por teclado elimina el CA y quitar todos bloquea guardar', async () => {
    /** Quitar CA; sin CA es error. */
    const { user } = setup()
    screen.getByRole('button', { name: 'Quitar CA-02' }).focus()
    await user.keyboard('{Enter}')
    expect(criterionIds()).toEqual(['CA-01'])
    expect(saveButton()).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Quitar CA-01' }))
    expect(saveButton()).toBeDisabled()
    expect(screen.getAllByText('La HU necesita al menos un criterio de aceptación.').length).toBeGreaterThan(0)
  })

  it('vaciar un paso marca ese campo como inválido', async () => {
    /** CA sin then → error en el campo Entonces. */
    const { user } = setup()
    const then = within(criterion('CA-02')).getByLabelText('Entonces')
    await user.clear(then)
    expect(then).toHaveAttribute('aria-invalid', 'true')
    expect(then).toHaveAccessibleDescription(/CA-02 necesita al menos un «Entonces»/)
  })
})

describe('StoryEditor · reglas de negocio', () => {
  it('añadir una regla crea RN-03 que necesita descripción', async () => {
    /** Añadir RN; RN sin descripción es error. */
    const { user, onSave } = setup()
    await user.click(screen.getByRole('button', { name: 'Añadir una regla' }))
    const field = screen.getByLabelText('Descripción de RN-03')
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(saveButton()).toBeDisabled()
    await user.type(field, 'Regla ficticia.')
    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[0].business_rules.at(-1)).toEqual({ id: 'RN-03', description: 'Regla ficticia.' })
  })

  it('quitar todas las reglas muestra «Sin reglas de negocio.» y se puede guardar', async () => {
    /** business_rules vacía es válida. */
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: 'Quitar RN-01' }))
    await user.click(screen.getByRole('button', { name: 'Quitar RN-02' }))
    expect(screen.getByText('Sin reglas de negocio.')).toBeInTheDocument()
    expect(saveButton()).toBeEnabled()
  })
})

describe('StoryEditor · Más campos', () => {
  it('está plegado al abrir y sus 8 listas se pueden editar', async () => {
    /** «Más campos» plegado con las 8 listas, editable. */
    const { user, onSave } = setup()
    const details = screen.getByText(/^Más campos/).closest('details')!
    expect(details).not.toHaveAttribute('open')
    for (const label of ['Alcance incluido', 'Fuera del alcance', 'Supuestos', 'Restricciones', 'Dependencias', 'Flujos alternativos', 'Excepciones', 'Funcionalidades relacionadas']) {
      expect(within(details).getByLabelText(label)).toBeInTheDocument()
    }
    await user.click(screen.getByText(/^Más campos/))
    expect(details).toHaveAttribute('open')
    const assumptions = within(details).getByLabelText('Supuestos')
    expect(assumptions).toHaveValue('La persona socia ha iniciado sesión.')
    await user.type(assumptions, '{Enter}Supuesto ficticio{Enter}   ')
    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[0].assumptions).toEqual(['La persona socia ha iniciado sesión.', 'Supuesto ficticio'])
  })
})

describe('StoryEditor · error de la revisión', () => {
  it('reviewError sale arriba en role="alert" con «No se guardó la edición.»', () => {
    /** review.error en role="alert". */
    setup({ reviewError: 'El campo jira_key no se puede cambiar al editar.' })
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('No se guardó la edición.')
    expect(alert).toHaveTextContent('El campo jira_key no se puede cambiar al editar.')
  })

  it('sin reviewError no hay alerta', () => {
    /** Sin error, sin alerta. */
    setup({ reviewError: null })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('StoryEditor · cancelar', () => {
  it('sin cambios, Cancelar llama a onCancel directamente', async () => {
    /** Cancelar sin cambios. */
    const { user, onCancel } = setup()
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/¿Descartar los cambios\?/)).not.toBeInTheDocument()
  })

  it('con cambios pide confirmación; «Seguir editando» vuelve con el borrador intacto', async () => {
    /** Cancelar con cambios → ¿Descartar los cambios? / Seguir editando. */
    const { user, onCancel } = setup()
    await user.type(titleInput(), ' bis')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('group', { name: 'Descartar los cambios' })).toHaveTextContent('¿Descartar los cambios?')
    await user.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(onCancel).not.toHaveBeenCalled()
    expect(saveButton()).toBeEnabled()
    expect(titleInput()).toHaveValue('Renovar un préstamo bis')
  })

  it('con cambios, «Sí, descartar» llama a onCancel', async () => {
    /** Confirmar descarte. */
    const { user, onCancel, onSave } = setup()
    await user.type(titleInput(), ' bis')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    await user.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onSave).not.toHaveBeenCalled()
  })

  it('solo con una nota también pide confirmación', async () => {
    /** dirty: cambió algo o hay nota. */
    const { user, onCancel } = setup()
    await user.type(screen.getByLabelText('Nota de la edición (opcional)'), 'nota ficticia')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(onCancel).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Sí, descartar' })).toBeInTheDocument()
  })

  it('deshacer el cambio a mano deja de pedir confirmación', async () => {
    /** dirty es estructural: volver al original no cuenta como cambio. */
    const { user, onCancel } = setup()
    await user.type(titleInput(), 'x')
    await user.type(titleInput(), '{Backspace}')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})

describe('StoryEditor · guardando', () => {
  it('busy → «Guardando…» y Guardar y Cancelar desactivados', async () => {
    /** busy desactiva los botones. */
    setup({ busy: true })
    const button = screen.getByRole('button', { name: 'Guardando…' })
    expect(button).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Guardar la versión/ })).not.toBeInTheDocument()
  })
})

describe('StoryEditor · solo texto', () => {
  it('un título con <script> y <b> se queda como texto en el campo y en lo que se envía', async () => {
    /** Nunca HTML: el valor del campo es el texto literal. */
    const { user, onSave } = setup()
    const hostile = '<script>alert(1)</script><b>negrita</b>'
    await user.clear(titleInput())
    await user.type(titleInput(), hostile)
    expect(titleInput()).toHaveValue(hostile)
    expect(document.querySelector('script')).toBeNull()
    expect(screen.queryByText('negrita', { selector: 'b' })).not.toBeInTheDocument()
    await user.click(saveButton())
    expect(onSave.mock.calls[0]?.[0].title).toBe(hostile)
  })

  it('un reviewError con etiquetas se pinta como texto', () => {
    /** review.error nunca como HTML. */
    setup({ reviewError: '<img src=x onerror=alert(1)><b>falso</b>' })
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('<img src=x onerror=alert(1)><b>falso</b>')
    expect(alert.querySelector('img')).toBeNull()
    expect(within(alert).queryByText('falso', { selector: 'b' })).not.toBeInTheDocument()
  })

  it('los ids de los CA se pintan como texto aunque traigan etiquetas', () => {
    /** Datos de la API como texto. */
    const original = story()
    original.acceptance_criteria[0]!.title = '<i>cursiva</i>'
    setup({ original })
    expect(within(criterion('CA-01')).getByLabelText('Título de CA-01')).toHaveValue('<i>cursiva</i>')
    expect(document.querySelector('i')).toBeNull()
  })
})
