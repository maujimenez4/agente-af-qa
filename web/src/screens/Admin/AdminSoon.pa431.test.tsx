// PA-431: en Ajustes, «Añadir documentos» y «Usuarios y roles» salían desactivados sin explicación visible.
// Cada bloque lleva ahora el distintivo «Disponible pronto» y una frase breve. Datos sintéticos (admin-demo).
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb } from '../../mocks/node.ts'

async function openAdmin() {
  mockDb.session = { username: 'admin-demo', role: 'admin', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('heading', { level: 1, name: 'Ajustes' })
  return screen.getByRole('region', { name: /Añadir documentos/ })
}

describe('Administración · lo que aún no está lo dice (PA-431)', () => {
  it('documentos: distintivo «Disponible pronto» visible y su motivo', async () => {
    const card = await openAdmin()
    const title = within(card).getByRole('heading', { level: 2, name: /Añadir documentos/ })
    expect(within(title).getByText('Disponible pronto')).toBeVisible()
    expect(within(card).getByText('La carga de documentos llegará en una versión posterior.')).toBeVisible()
    const choose = within(card).getByRole('button', { name: 'Elegir archivos' })
    expect(choose).toHaveAttribute('aria-disabled', 'true')
    expect(choose).toHaveAccessibleDescription('Disponible pronto: La carga de documentos llegará en una versión posterior.')
  })

  it('usuarios: distintivo «Disponible pronto» visible y su motivo', async () => {
    const card = await openAdmin()
    const title = within(card).getByRole('heading', { level: 3, name: /Usuarios y roles/ })
    expect(within(title).getByText('Disponible pronto')).toBeVisible()
    expect(within(card).getByText('Los usuarios se gestionan hoy desde el servidor.')).toBeVisible()
    const manage = within(card).getByRole('button', { name: 'Gestionar usuarios' })
    expect(manage).toHaveAttribute('aria-disabled', 'true')
    expect(manage).toHaveAccessibleDescription('Disponible pronto: Los usuarios se gestionan hoy desde el servidor.')
  })
})
