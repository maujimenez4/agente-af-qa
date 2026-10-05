// T-56: huecos de Workspace.test.tsx sobre DESIGN-DECISIONS.md §4 bis («Plegar el panel derecho»).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SidePanel, Workspace } from './Workspace.tsx'

function renderWorkspace() {
  return render(
    <Workspace title="Evolucionar DEMO-3" phase={2} panel={<SidePanel title="Propuesta de HU">Contenido ficticio</SidePanel>}>
      <p>Mensajes</p>
    </Workspace>,
  )
}

describe('Plegar el panel derecho: huecos (DESIGN-DECISIONS.md §4 bis)', () => {
  it('el botón cambia de texto y no lleva aria-pressed ni aria-expanded', async () => {
    renderWorkspace()
    const toggle = screen.getByRole('button', { name: 'Ocultar el panel' })
    expect(toggle).not.toHaveAttribute('aria-pressed')
    expect(toggle).not.toHaveAttribute('aria-expanded')
    await userEvent.click(toggle)
    expect(toggle).toHaveAccessibleName('Mostrar el panel')
    expect(toggle).not.toHaveAttribute('aria-pressed')
    expect(toggle).not.toHaveAttribute('aria-expanded')
  })

  it('el botón va en la cabecera a la derecha de la Q de fase, y no hay otro en la cabecera del panel', () => {
    renderWorkspace()
    const toggle = screen.getByRole('button', { name: 'Ocultar el panel' })
    const phase = screen.getByRole('img', { name: /Avance: fase 2 de 4/ })
    expect(phase.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(toggle.closest('header')).toBe(phase.closest('header'))
    expect(screen.getAllByRole('button', { name: /panel/ })).toHaveLength(1)
  })

  it('plegado, el panel se oculta con hidden sin desmontarse y aria-controls sigue apuntando a él', async () => {
    const { container } = renderWorkspace()
    const toggle = screen.getByRole('button', { name: 'Ocultar el panel' })
    await userEvent.click(toggle)
    const aside = container.querySelector('aside')
    expect(aside).not.toBeNull()
    expect(aside).toHaveAttribute('hidden')
    expect(aside).toHaveTextContent('Contenido ficticio')
    expect(toggle.getAttribute('aria-controls')).toBe(aside?.id)
  })
})
