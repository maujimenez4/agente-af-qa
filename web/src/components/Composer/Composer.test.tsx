import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Composer, ModelTag, ProjectButton, ToolButton, type ComposerProps } from './Composer.tsx'

const PLACEHOLDER = 'Escribe la clave de la HU, por ejemplo DEMO-3, y qué quieres cambiar.'

function Controlled(props: Partial<ComposerProps> & { onSubmit: () => void }) {
  const [value, setValue] = useState('')
  return (
    <Composer
      placeholder={PLACEHOLDER}
      value={value}
      onChange={setValue}
      canSubmit={value.trim().length > 0}
      {...props}
    />
  )
}

describe('Composer', () => {
  it('el cuadro de texto se etiqueta con su ayuda', () => {
    render(<Controlled onSubmit={vi.fn()} />)
    expect(screen.getByRole('textbox', { name: PLACEHOLDER })).toHaveAttribute('placeholder', PLACEHOLDER)
  })

  it('sin texto no se puede enviar; con texto, sí', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    const send = screen.getByRole('button', { name: 'Continuar' })
    expect(send).toBeDisabled()
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3')
    expect(send).toBeEnabled()
    await userEvent.click(send)
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('Intro hace un salto de línea y Ctrl + Intro envía', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    const box = screen.getByRole('textbox')
    await userEvent.type(box, 'Línea uno{Enter}línea dos')
    expect(box).toHaveValue('Línea uno\nlínea dos')
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('desactivado no deja escribir ni enviar', async () => {
    const onSubmit = vi.fn()
    render(
      <Composer placeholder="Espera a la propuesta para pedir cambios" value="x" onChange={vi.fn()} onSubmit={onSubmit} canSubmit disabled />,
    )
    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Continuar' })).toBeDisabled()
  })

  it('pinta las herramientas y el adjunto que le dan', () => {
    render(
      <Controlled onSubmit={vi.fn()} attachment={<p>Origen: DEMO-3</p>} tools={<ToolButton icon="work" onClick={vi.fn()}>Elegir en Jira</ToolButton>} />,
    )
    expect(screen.getByText('Origen: DEMO-3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Elegir en Jira' })).toBeInTheDocument()
  })

  it('el texto se muestra tal cual, nunca como HTML', async () => {
    render(<Controlled onSubmit={vi.fn()} />)
    await userEvent.type(screen.getByRole('textbox'), '<b>x</b>')
    expect(screen.getByRole('textbox')).toHaveValue('<b>x</b>')
    expect(document.querySelector('form b')).toBeNull()
  })
})

describe('ProjectButton', () => {
  it('anuncia el proyecto y que sirve para cambiarlo', async () => {
    const onClick = vi.fn()
    render(<ProjectButton projectKey="DEMO" projectName="Biblioteca" onClick={onClick} />)
    const button = screen.getByRole('button', { name: 'Proyecto de Jira: DEMO, Biblioteca. Cambiar' })
    await userEvent.click(button)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('sin proyecto invita a elegirlo', () => {
    render(<ProjectButton onClick={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Elegir proyecto de Jira' })).toBeInTheDocument()
  })
})

describe('ModelTag', () => {
  it('es texto de solo lectura, no un control', () => {
    render(<ModelTag label="Modelo automático" />)
    expect(screen.getByText('Modelo automático')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })
})
