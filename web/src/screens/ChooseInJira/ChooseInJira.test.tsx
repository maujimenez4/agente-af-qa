import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb } from '../../mocks/node.ts'

async function openDialog() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const opener = await screen.findByRole('button', { name: 'Elegir en Jira' })
  await waitFor(() => expect(opener).toBeEnabled())
  await userEvent.click(opener)
  return screen.getByRole('dialog', { name: 'Elegir en Jira' })
}

describe('Elegir en Jira (Mixta 1b, UI.md §4.2)', () => {
  it('muestra los proyectos que ve la conexión, con el de Inicio elegido, y sus épicas', async () => {
    const dialog = await openDialog()
    const projects = await within(dialog).findByRole('listbox', { name: 'Proyectos' })
    expect(within(projects).getByRole('option', { name: 'DEMO Biblioteca' })).toHaveAttribute('aria-selected', 'true')
    const epics = await within(dialog).findByRole('listbox', { name: 'Épicas de DEMO' })
    expect(within(epics).getByRole('option', { name: 'DEMO-1 Préstamo digital' })).toBeInTheDocument()
    expect(within(dialog).getByText('Elegir la épica sirve para crear una HU nueva dentro de ella.')).toBeInTheDocument()
    expect(within(dialog).getByText('Elige una épica para ver sus HU.')).toBeInTheDocument()
  })

  it('el buscador recibe el foco y su ayuda nombra el proyecto', async () => {
    const dialog = await openDialog()
    const search = within(dialog).getByRole('searchbox', { name: 'Buscar en Jira' })
    expect(search).toHaveFocus()
    expect(search).toHaveAttribute('placeholder', 'Buscar por texto o clave en el proyecto DEMO')
  })

  it('al elegir una épica salen sus HU; al elegir una HU se puede usar y vuelve a Inicio como origen', async () => {
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    const stories = await within(dialog).findByRole('listbox', { name: 'HU de DEMO-1' })
    await userEvent.click(within(stories).getByRole('option', { name: 'DEMO-3 Renovar un préstamo' }))
    expect(within(dialog).getByText(/Seleccionada:/)).toHaveTextContent(
      'Seleccionada: DEMO-3 · Renovar un préstamo (proyecto DEMO, épica DEMO-1)',
    )
    expect(within(dialog).getByRole('button', { name: 'Usar la épica DEMO-1' })).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar DEMO-3' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByText(/Origen:/)).toHaveTextContent('Origen: DEMO-3 · Renovar un préstamo')
  })

  it('«Usar la épica» fija la épica como origen (HU nueva dentro de ella)', async () => {
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar la épica DEMO-1' }))
    expect(screen.getByText(/Origen:/)).toHaveTextContent('Origen: DEMO-1 · Préstamo digital')
  })

  it('buscar por texto filtra épicas y HU del proyecto', async () => {
    const dialog = await openDialog()
    await userEvent.type(within(dialog).getByRole('searchbox'), 'renovar')
    const found = await within(dialog).findByRole('listbox', { name: 'HU encontradas en DEMO' }, { timeout: 2000 })
    expect(within(found).getByRole('option', { name: 'DEMO-3 Renovar un préstamo' })).toBeInTheDocument()
    expect(within(dialog).getByText('Ninguna épica coincide.')).toBeInTheDocument()
  })

  it('cambiar de proyecto lo fija (POST /projects/choose) y lo lleva a Inicio con sus recientes', async () => {
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('option', { name: 'SOCI Gestión de personas socias' }))
    await userEvent.click(await within(dialog).findByRole('option', { name: 'SOCI-1 Alta de personas socias en línea' }))
    await userEvent.click(await within(dialog).findByRole('option', { name: 'SOCI-2 Alta de persona socia en línea' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar SOCI-2' }))
    await waitFor(() => expect(mockDb.projects.preselected).toBe('SOCI'))
    expect(await screen.findByRole('button', { name: 'Proyecto de Jira: SOCI, Gestión de personas socias. Cambiar' })).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Recientes en SOCI' })).toBeInTheDocument()
  })

  it('cambiar solo de proyecto, sin origen, también se puede', async () => {
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('option', { name: 'SOCI Gestión de personas socias' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar el proyecto SOCI' }))
    expect(await screen.findByRole('button', { name: /Proyecto de Jira: SOCI/ })).toBeInTheDocument()
    expect(screen.queryByText(/Origen:/)).toBeNull()
  })

  it('Cancelar y Esc cierran sin cambiar nada', async () => {
    let dialog = await openDialog()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Elegir en Jira' }))
    dialog = screen.getByRole('dialog')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: 'Elegir en Jira' })).toHaveFocus()
    expect(mockDb.projects.preselected).toBe('DEMO')
  })

  it('el selector de proyecto del compositor también abre el diálogo', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Proyecto de Jira: DEMO, Biblioteca. Cambiar' }))
    expect(screen.getByRole('dialog', { name: 'Elegir en Jira' })).toBeInTheDocument()
  })

  it('se recorre con el teclado: lista de proyectos con flechas', async () => {
    const dialog = await openDialog()
    const projects = await within(dialog).findByRole('listbox', { name: 'Proyectos' })
    projects.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(within(projects).getByRole('option', { name: 'SOCI Gestión de personas socias' })).toHaveAttribute('aria-selected', 'true')
    expect(await within(dialog).findByRole('listbox', { name: 'Épicas de SOCI' })).toBeInTheDocument()
  })
})
