// Criterio 7 (T-56, días 2-4): huecos de Composer.test.tsx. Ctrl/Cmd + Intro, estado desactivado y etiquetas.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Composer, ModelTag, ProjectButton, ToolButton, type ComposerProps } from './Composer.tsx'

const PLACEHOLDER = 'Describe la necesidad. Si escribes una clave de Jira, por ejemplo DEMO-3, la reconozco.'

function Controlled(props: Partial<ComposerProps> & { onSubmit: () => void; initial?: string }) {
  const { initial = '', ...rest } = props
  const [value, setValue] = useState(initial)
  return <Composer placeholder={PLACEHOLDER} value={value} onChange={setValue} canSubmit={value.trim().length > 0} {...rest} />
}

describe('Composer: atajo de envío', () => {
  it('test_meta_enter_submits', async () => {
    /** Criterio 7: Cmd + Intro (macOS) también envía. */
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3')
    await userEvent.keyboard('{Meta>}{Enter}{/Meta}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('textbox')).toHaveValue('Cambiar DEMO-3')
  })

  it('test_ctrl_enter_does_not_insert_newline', async () => {
    /** Criterio 7: Ctrl + Intro envía sin añadir un salto de línea. */
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox'), 'Una línea{Control>}{Enter}{/Control}')
    expect(screen.getByRole('textbox')).toHaveValue('Una línea')
  })

  it('test_ctrl_enter_without_content_does_nothing', async () => {
    /** Criterio 7 (negativo): sin nada que enviar, Ctrl + Intro no envía. */
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox'), '   ')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('test_shift_enter_inserts_newline', async () => {
    /** Criterio 7 (límite): Mayús + Intro hace salto de línea, no envía. */
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox'), 'a{Shift>}{Enter}{/Shift}b')
    expect(screen.getByRole('textbox')).toHaveValue('a\nb')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('test_ctrl_enter_while_disabled_does_nothing', () => {
    /** Criterio 7 (negativo): desactivado, el atajo tampoco envía aunque haya texto. */
    const onSubmit = vi.fn()
    render(<Composer placeholder={PLACEHOLDER} value="DEMO-3" onChange={vi.fn()} onSubmit={onSubmit} canSubmit disabled />)
    const box = screen.getByRole('textbox')
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('test_submit_button_when_cannot_submit_does_nothing', async () => {
    /** Criterio 7 (negativo): con canSubmit=false el envío del formulario no llama a onSubmit. */
    const onSubmit = vi.fn()
    render(<Composer placeholder={PLACEHOLDER} value="x" onChange={vi.fn()} onSubmit={onSubmit} canSubmit={false} />)
    const form = screen.getByRole('textbox').closest('form')
    form?.requestSubmit()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})

describe('Composer: desactivado y etiquetas', () => {
  it('test_disabled_marks_form_and_keeps_tools_rendered', () => {
    /** Criterio 7: desactivado se marca el formulario y se siguen viendo las herramientas. */
    render(
      <Composer
        placeholder="Espera a la propuesta para pedir cambios"
        value=""
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        canSubmit={false}
        disabled
        tools={<ModelTag label="Modelo automático" />}
      />,
    )
    expect(screen.getByRole('textbox', { name: 'Espera a la propuesta para pedir cambios' })).toBeDisabled()
    expect(screen.getByRole('textbox').closest('form')).toHaveAttribute('data-disabled')
    expect(screen.getByText('Modelo automático')).toBeInTheDocument()
  })

  it('test_enabled_form_has_no_disabled_mark', () => {
    /** Criterio 7 (límite): activo, el formulario no lleva la marca de desactivado. */
    render(<Controlled onSubmit={vi.fn()} />)
    expect(screen.getByRole('textbox').closest('form')).not.toHaveAttribute('data-disabled')
  })

  it('test_custom_submit_label_names_icon_button', () => {
    /** Criterio 7: el botón de enviar es un icono con nombre accesible propio. */
    render(<Controlled onSubmit={vi.fn()} submitLabel="Enviar mensaje" initial="hola" />)
    const send = screen.getByRole('button', { name: 'Enviar mensaje' })
    expect(send).toHaveAttribute('type', 'submit')
    expect(send).toBeEnabled()
  })

  it('test_label_is_hidden_but_linked_to_textarea', () => {
    /** Criterio 7: la etiqueta (ayuda) está asociada al cuadro y oculta visualmente. */
    render(<Controlled onSubmit={vi.fn()} />)
    const label = screen.getByText(`${PLACEHOLDER} (Intro para enviar, Mayús+Intro para nueva línea)`, { selector: 'label' })
    expect(label).toHaveClass('visually-hidden')
    expect(label).toHaveAttribute('for', screen.getByRole('textbox').id)
  })

  it('test_two_composers_have_distinct_ids', () => {
    /** Criterio 7 (límite): dos compositores en la página no comparten id de etiqueta. */
    render(
      <>
        <Controlled onSubmit={vi.fn()} placeholder="Uno" />
        <Controlled onSubmit={vi.fn()} placeholder="Dos" />
      </>,
    )
    expect(screen.getByRole('textbox', { name: 'Uno (Intro para enviar, Mayús+Intro para nueva línea)' }).id).not.toBe(screen.getByRole('textbox', { name: 'Dos (Intro para enviar, Mayús+Intro para nueva línea)' }).id)
  })

  it('test_attachment_appears_before_textbox', () => {
    /** Criterio 7: el adjunto (origen fijado) va encima del cuadro de texto. */
    render(<Controlled onSubmit={vi.fn()} attachment={<p>Origen: DEMO-3 · Renovar un préstamo</p>} />)
    const attachment = screen.getByText(/Origen: DEMO-3/)
    expect(attachment.compareDocumentPosition(screen.getByRole('textbox')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('herramientas del compositor', () => {
  it('test_tool_button_disabled_does_not_fire', async () => {
    /** Criterio 7 (negativo): una herramienta desactivada no responde. */
    const onClick = vi.fn()
    render(
      <ToolButton icon="work" onClick={onClick} disabled>
        Elegir en Jira
      </ToolButton>,
    )
    const tool = screen.getByRole('button', { name: 'Elegir en Jira' })
    expect(tool).toBeDisabled()
    await userEvent.click(tool)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('test_tool_buttons_do_not_submit_form', async () => {
    /** Criterio 7: pulsar una herramienta dentro del compositor no envía el formulario. */
    const onSubmit = vi.fn()
    const onTool = vi.fn()
    render(
      <Controlled
        onSubmit={onSubmit}
        initial="DEMO-3"
        tools={
          <ToolButton icon="work" onClick={onTool}>
            Elegir en Jira
          </ToolButton>
        }
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Elegir en Jira' }))
    expect(onTool).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('test_project_button_without_name_label', () => {
    /** Criterio 7 (límite): proyecto sin nombre se anuncia solo con la clave. */
    render(<ProjectButton projectKey="DEMO" onClick={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Proyecto de Jira: DEMO. Cambiar' })).toBeInTheDocument()
  })

  it('test_project_button_disabled_and_icons_decorative', () => {
    /** Criterio 7: el selector de proyecto desactivado no se puede usar y sus iconos son decorativos. */
    const { container } = render(<ProjectButton projectKey="DEMO" projectName="Biblioteca" onClick={vi.fn()} disabled />)
    expect(screen.getByRole('button', { name: /Proyecto de Jira: DEMO/ })).toBeDisabled()
    for (const icon of container.querySelectorAll('svg')) expect(icon).toHaveAttribute('aria-hidden', 'true')
  })
})
