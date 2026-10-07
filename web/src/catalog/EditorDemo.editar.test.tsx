// Editar a mano, parte A (T-56, PA-340): `/?catalogo&editor` abre solo el editor, a tamaño real, con la HU del
// ejemplo del contrato (DEMO-3). Sin API: «Guardar» crea la versión siguiente simulada y `&rechazo` simula `review.error`.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../App.tsx'
import { Catalog } from './Catalog.tsx'

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('Catálogo · /?catalogo&editor', () => {
  it('monta solo el editor, sin el resto del catálogo', async () => {
    /** `/?catalogo&editor` abre solo el editor. */
    window.history.replaceState(null, '', '/?catalogo&editor')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Editar a mano' })).toBeInTheDocument()
    expect(screen.getByText('Evolucionar DEMO-3 · versión 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Título')).toHaveValue('Renovar un préstamo')
    expect(screen.queryByRole('heading', { level: 1, name: 'Sistema de diseño · Propuesta mixta' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Secciones del catálogo' })).not.toBeInTheDocument()
  })

  it('sin &editor, el catálogo sigue como siempre', () => {
    /** La línea añadida no cambia `/?catalogo`. */
    window.history.replaceState(null, '', '/?catalogo')
    render(<Catalog />)
    expect(screen.getByRole('navigation', { name: 'Secciones del catálogo' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Editar a mano' })).not.toBeInTheDocument()
  })

  it('guardar crea la «versión 3» simulada y el editor vuelve a empezar desde ella', async () => {
    /** Guardar crea la versión 3 simulada. */
    window.history.replaceState(null, '', '/?catalogo&editor')
    const user = userEvent.setup()
    render(<Catalog />)
    await user.type(screen.getByLabelText('Título'), ' bis')
    await user.click(screen.getByRole('button', { name: 'Guardar la versión 3' }))
    expect(screen.getByText(/Versión 3 guardada \(simulado, sin API\)\./)).toBeInTheDocument()
    expect(screen.getByText('Evolucionar DEMO-3 · versión 3')).toBeInTheDocument()
    expect(screen.getByLabelText('Título')).toHaveValue('Renovar un préstamo bis')
    expect(screen.getByRole('button', { name: 'Guardar la versión 4' })).toBeDisabled()
    expect(screen.getByText('Aún no has cambiado nada.')).toBeInTheDocument()
  })

  it('cancelar sin cambios deja la versión como estaba', async () => {
    /** Cancelar en la demo. */
    window.history.replaceState(null, '', '/?catalogo&editor')
    const user = userEvent.setup()
    render(<Catalog />)
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.getByText(/Edición cancelada: la versión sigue como estaba\./)).toBeInTheDocument()
    expect(screen.getByText('Evolucionar DEMO-3 · versión 2')).toBeInTheDocument()
  })

  it('con &rechazo, guardar muestra «No se guardó la edición.» y no crea versión', async () => {
    /** `&rechazo` simula un review.error. */
    window.history.replaceState(null, '', '/?catalogo&editor&rechazo')
    const user = userEvent.setup()
    render(<Catalog />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Título'), ' bis')
    await user.click(screen.getByRole('button', { name: 'Guardar la versión 3' }))
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('No se guardó la edición.')
    expect(screen.getByText('Evolucionar DEMO-3 · versión 2')).toBeInTheDocument()
    expect(screen.getByLabelText('Título')).toHaveValue('Renovar un préstamo bis')
  })

  it('solo usa datos ficticios', () => {
    /** Datos sintéticos: sin emails. */
    window.history.replaceState(null, '', '/?catalogo&editor')
    const { container } = render(<Catalog />)
    expect(container.textContent ?? '').not.toMatch(/[\w.+-]+@[\w-]+\.[\w.]+/)
  })
})
