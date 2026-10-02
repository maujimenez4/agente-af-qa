import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Catalog } from './Catalog.tsx'
import { CATALOG_SECTIONS } from './catalogTokens.ts'

describe('Catalog', () => {
  it('tiene un índice con un enlace por sección', () => {
    render(<Catalog />)
    const nav = screen.getByRole('navigation', { name: 'Secciones del catálogo' })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(CATALOG_SECTIONS.map((section) => section.title))
  })

  it.each(CATALOG_SECTIONS)('el enlace «$title» lleva a su sección', ({ id, title }) => {
    render(<Catalog />)
    const heading = screen.getByRole('heading', { level: 2, name: title })
    expect(heading).toHaveAttribute('id', id)
    expect(screen.getByRole('link', { name: title })).toHaveAttribute('href', `#${id}`)
  })

  it('cada sección es una región con el nombre de su título', () => {
    render(<Catalog />)
    for (const { title } of CATALOG_SECTIONS) {
      expect(screen.getByRole('region', { name: title })).toBeInTheDocument()
    }
  })

  it('solo usa datos ficticios: ni emails ni nombres fuera de los usuarios demo', () => {
    const { container } = render(<Catalog />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/[\w.+-]+@[\w-]+\.[\w.]+/)
    expect(text).toContain('af-demo')
  })

  it('las demos usan el Button del sistema, no botones provisionales', () => {
    const { container } = render(<Catalog />)
    expect(container.querySelector('[class*="demoButton"]')).toBeNull()
  })
})
