import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { DISABLED_HINT, defaultFlow, FLOWS } from './flows.ts'

async function openHome(username: 'af-demo' | 'qa-demo' = 'af-demo') {
  mockDb.session = { username, role: username === 'qa-demo' ? 'qa' : 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })
}

function flowCard(label: string): HTMLElement {
  return within(screen.getByRole('group', { name: 'Qué quieres hacer' })).getByRole('button', { name: label })
}

describe('Inicio (Mixta 1, UI.md §4.1)', () => {
  it('la analista ve los flujos de HU y «Preparar pruebas» desactivada con su ayuda', async () => {
    await openHome('af-demo')
    expect(flowCard('Nueva necesidad')).toHaveAttribute('aria-pressed', 'true')
    for (const label of ['Evolucionar una HU', 'Revisar la calidad de una HU']) {
      expect(flowCard(label)).not.toHaveAttribute('aria-disabled')
    }
    expect(flowCard('Preparar pruebas')).toHaveAttribute('aria-disabled', 'true')
    expect(flowCard('Preparar pruebas')).toHaveAccessibleDescription('Disponible para el rol QA.')
  })

  it('QA tiene «Preparar pruebas» elegida y los flujos de HU desactivados', async () => {
    await openHome('qa-demo')
    expect(flowCard('Preparar pruebas')).toHaveAttribute('aria-pressed', 'true')
    expect(flowCard('Nueva necesidad')).toHaveAccessibleDescription('Disponible para el rol de analista funcional.')
  })

  it('la ayuda del compositor cambia con el flujo', async () => {
    await openHome()
    await userEvent.click(flowCard('Evolucionar una HU'))
    expect(screen.getByRole('textbox', { name: 'Escribe la clave de la HU, por ejemplo DEMO-3, y qué quieres cambiar. (Intro para enviar, Mayús+Intro para nueva línea)' })).toBeInTheDocument()
  })

  it('muestra el proyecto preseleccionado, el modelo de solo lectura y el aviso de simulación', async () => {
    await openHome()
    expect(await screen.findByRole('button', { name: 'Proyecto de Jira: DEMO, Biblioteca. Cambiar' })).toBeInTheDocument()
    expect(screen.getByText('Modelo automático')).toBeInTheDocument()
    expect(await screen.findByRole('note')).toHaveTextContent(
      'Modo de prueba: al aprobar verás lo que se haría en Jira, pero no se escribirá nada.',
    )
  })

  it('en modo real no hay aviso de simulación', async () => {
    mockDb.settings.publish_mode = 'live'
    await openHome()
    await screen.findByText('Modelo automático')
    expect(screen.queryByRole('note')).toBeNull()
  })

  it('los recientes del proyecto fijan el origen, que se puede quitar', async () => {
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    expect(within(recents).getByRole('button', { name: 'DEMO-1 Épica · Préstamo digital' })).toBeInTheDocument()
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    expect(screen.getByText(/Origen:/)).toHaveTextContent('Origen: DEMO-3 · Renovar un préstamo')
    await userEvent.click(screen.getByRole('button', { name: 'Quitar el origen DEMO-3' }))
    expect(screen.queryByText(/Origen:/)).toBeNull()
  })

  it('con un origen fijado se puede continuar sin escribir', async () => {
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    expect(await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })).toBeInTheDocument()
    expect(screen.getByRole('log')).toHaveTextContent('Operación fijada: evolucionar DEMO-3')
  })

  it('con texto pide el arranque guiado sin IA y pasa sus opciones', async () => {
    await openHome()
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3 para la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    expect(await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Crear HU nueva' })).toBeInTheDocument()
  })

  it('si el arranque guiado falla, muestra la tarjeta de error y se queda en Inicio', async () => {
    mockServer.use(
      http.post('/api/v1/start/propose', () =>
        HttpResponse.json(
          { error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' } },
          { status: 503 },
        ),
      ),
    )
    await openHome()
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('«Nueva conversación» vuelve a Inicio', async () => {
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })
    await userEvent.click(screen.getByRole('button', { name: 'Nueva conversación' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })
})

describe('flujos', () => {
  it('cada rol empieza por el primer flujo que puede usar', () => {
    expect(defaultFlow(['generate_story'])).toBe('need')
    expect(defaultFlow(['generate_tests'])).toBe('tests')
  })

  it('las ayudas de las tarjetas desactivadas son las de UI.md §3', () => {
    expect(DISABLED_HINT).toEqual({
      generate_story: 'Disponible para el rol de analista funcional.',
      generate_tests: 'Disponible para el rol QA.',
    })
    expect(FLOWS.map((flow) => flow.label)).toEqual([
      'Nueva necesidad',
      'Evolucionar una HU',
      'Revisar la calidad de una HU',
      'Preparar pruebas',
    ])
  })
})
