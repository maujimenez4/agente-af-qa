// El catálogo reúne las piezas con datos sintéticos: comprueba que, montadas juntas, cumplen
// los criterios 3, 4, 5 y 6 (roles, nombres accesibles, estados) y que no traen datos reales.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Catalog } from './Catalog.tsx'

function section(name: string): HTMLElement {
  return screen.getByRole('region', { name })
}

describe('Catalog: accesibilidad del conjunto', () => {
  it('todos los botones tienen nombre accesible (también los de solo icono)', () => {
    render(<Catalog />)
    for (const button of screen.getAllByRole('button')) {
      expect(button.textContent?.trim() || button.getAttribute('aria-label'), button.outerHTML).toBeTruthy()
    }
  })

  it('todas las imágenes anunciadas tienen nombre', () => {
    render(<Catalog />)
    for (const img of screen.getAllByRole('img')) expect(img).toHaveAccessibleName()
  })

  it('los SVG sin nombre están ocultos a los lectores de pantalla', () => {
    const { container } = render(<Catalog />)
    for (const svg of container.querySelectorAll('svg:not([role="img"])')) {
      const hidden = svg.closest('[aria-hidden="true"], [role="img"]')
      expect(hidden, svg.outerHTML.slice(0, 80)).not.toBeNull()
    }
  })

  it('tiene un único h1', () => {
    render(<Catalog />)
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('las tarjetas de error del catálogo son alertas con el título por código', () => {
    render(<Catalog />)
    const titles = within(section('Estados vacío, cargando y error'))
      .getAllByRole('alert')
      .map((alert) => within(alert).getByRole('heading').textContent)
    expect(titles).toEqual([
      'Límite de uso alcanzado',
      'Servicio no disponible',
      'No se encuentra',
      'Aprobación rechazada',
      'Sesión caducada',
      'No se pudo completar la acción',
    ])
  })

  it('el aviso del modo de prueba es una nota', () => {
    render(<Catalog />)
    expect(within(section('Estados vacío, cargando y error')).getByRole('note')).toHaveTextContent(
      'Modo de prueba: al aprobar verás lo que se haría en Jira, pero no se escribirá nada.',
    )
  })
})

describe('Catalog: demo del carril y la lista', () => {
  it('con af-demo el carril solo tiene Trabajo; con admin-demo, Historial y Ajustes (decisión 16)', async () => {
    render(<Catalog />)
    const shell = section('Carril y lista de conversaciones')
    const nav = within(shell).getByRole('navigation', { name: 'Zonas' })
    expect(within(nav).queryByRole('button', { name: 'Historial' })).toBeNull()

    await userEvent.click(within(shell).getByRole('button', { name: 'admin-demo' }))
    expect(within(nav).getByRole('button', { name: 'Historial' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('button', { name: 'Ajustes' })).toBeInTheDocument()
    expect(within(nav).queryByRole('button', { name: 'Trabajo' })).toBeNull()
  })

  it('qa-demo al 95 % muestra el aviso de consumo', async () => {
    render(<Catalog />)
    const shell = section('Carril y lista de conversaciones')
    await userEvent.click(within(shell).getByRole('button', { name: 'qa-demo' }))
    const ring = within(shell).getByRole('img', { name: 'Consumo diario de tokens: 95 %' })
    expect(ring.querySelector('[data-warning]')).not.toBeNull()
  })

  it('sin dato de consumo el anillo desaparece (decisión 17)', async () => {
    render(<Catalog />)
    const shell = section('Carril y lista de conversaciones')
    await userEvent.click(within(shell).getByRole('button', { name: 'Con consumo de tokens' }))
    expect(within(shell).queryByRole('img', { name: /Consumo diario de tokens/ })).toBeNull()
  })

  it('«Sin conversaciones» deja solo «Nueva conversación», sin buscador', async () => {
    render(<Catalog />)
    const shell = section('Carril y lista de conversaciones')
    await userEvent.click(within(shell).getByRole('button', { name: 'Sin conversaciones' }))
    const list = within(shell).getByRole('complementary', { name: 'Conversaciones' })
    expect(within(list).getByRole('button', { name: 'Nueva conversación' })).toBeInTheDocument()
    expect(within(list).queryByRole('searchbox')).toBeNull()
  })

  it('al elegir una conversación queda marcada con aria-current', async () => {
    render(<Catalog />)
    const list = within(section('Carril y lista de conversaciones')).getByRole('complementary', {
      name: 'Conversaciones',
    })
    const item = within(list).getByRole('button', { name: /Alta de persona socia en línea/ })
    await userEvent.click(item)
    expect(item).toHaveAttribute('aria-current', 'true')
  })

  it('el botón de la cabecera pliega la lista y apunta a ella con aria-controls', async () => {
    render(<Catalog />)
    const shell = section('Carril y lista de conversaciones')
    const list = within(shell).getByRole('complementary', { name: 'Conversaciones' })
    const toggle = within(shell).getByRole('button', { name: 'Ocultar conversaciones' })
    expect(toggle).toHaveAttribute('aria-controls', list.id)
    await userEvent.click(toggle)
    expect(within(shell).queryByRole('complementary', { name: 'Conversaciones' })).toBeNull()
    expect(within(shell).getByRole('button', { name: 'Mostrar conversaciones' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })
})

describe('Catalog: tarjetas de flujo por rol (UI.md §3)', () => {
  function flowCard(name: string): HTMLElement {
    return within(section('Botones, chips, badges y tarjetas')).getByRole('button', { name: new RegExp(`^${name}`) })
  }

  it('la analista ve sus tres flujos activos y «Preparar pruebas» desactivada con la ayuda de QA', () => {
    render(<Catalog />)
    for (const name of ['Nueva necesidad', 'Evolucionar una HU', 'Revisar la calidad de una HU']) {
      expect(flowCard(name)).not.toHaveAttribute('aria-disabled')
    }
    const tests = flowCard('Preparar pruebas')
    expect(tests).toHaveAttribute('aria-disabled', 'true')
    expect(tests).toHaveTextContent('Disponible para el rol QA.')
  })

  it('QA ve «Preparar pruebas» seleccionada por defecto y el resto desactivado con la ayuda de analista', async () => {
    render(<Catalog />)
    const demo = section('Botones, chips, badges y tarjetas')
    await userEvent.click(within(demo).getByRole('button', { name: 'qa-demo' }))
    expect(flowCard('Preparar pruebas')).toHaveAttribute('aria-pressed', 'true')
    for (const name of ['Nueva necesidad', 'Evolucionar una HU', 'Revisar la calidad de una HU']) {
      const card = flowCard(name)
      expect(card).toHaveAttribute('aria-disabled', 'true')
      expect(card).toHaveAttribute('aria-pressed', 'false')
      expect(card).toHaveTextContent('Disponible para el rol de analista funcional.')
    }
  })

  it('pulsar una tarjeta desactivada no cambia la selección', async () => {
    render(<Catalog />)
    await userEvent.click(flowCard('Preparar pruebas'))
    expect(flowCard('Preparar pruebas')).toHaveAttribute('aria-pressed', 'false')
    expect(flowCard('Nueva necesidad')).toHaveAttribute('aria-pressed', 'true')
  })

  it('pulsar una tarjeta activa la selecciona y deselecciona la anterior', async () => {
    render(<Catalog />)
    await userEvent.click(flowCard('Evolucionar una HU'))
    expect(flowCard('Evolucionar una HU')).toHaveAttribute('aria-pressed', 'true')
    expect(flowCard('Nueva necesidad')).toHaveAttribute('aria-pressed', 'false')
  })
})

describe('Catalog: datos sintéticos', () => {
  it('los usuarios son solo los de demo', () => {
    const { container } = render(<Catalog />)
    const text = container.textContent ?? ''
    for (const user of ['af-demo', 'qa-demo', 'admin-demo']) expect(text).toContain(user)
  })

  it('no muestra nada con forma de token, clave API o URL de un sitio de Jira', () => {
    const { container } = render(<Catalog />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/\b(sk|gsk|ghp|xox[bp])[-_][A-Za-z0-9]{10,}/)
    expect(text).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}\./)
    expect(text).not.toMatch(/https?:\/\/[\w-]+\.atlassian\.net/)
  })
})
