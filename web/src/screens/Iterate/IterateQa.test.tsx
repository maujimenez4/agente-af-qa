// QA 3 · Iterar la suite (UI.md §6.3): la conversación de Iterar con el panel de la suite (Casos, Cobertura, Datos y
// riesgos, Estrategia), sugerencias de QA y la versión siguiente con su caso nuevo. Datos sintéticos (DEMO-3, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb } from '../../mocks/node.ts'

const panel = () => screen.getByRole('complementary', { name: 'Suite de pruebas' })

async function openSuite() {
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
  render(<App />)
  const pending = await screen.findByRole('region', { name: 'Pendientes de pruebas' })
  await userEvent.click(await within(pending).findByRole('button', { name: 'Recoger DEMO-3' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Ver la suite' }))
  await screen.findByRole('complementary', { name: 'Suite de pruebas' })
}

describe('QA 3 · Iterar la suite', () => {
  it('cabecera, panel ancho con el distintivo de cobertura y las cuatro pestañas', async () => {
    await openSuite()
    expect(screen.getByRole('heading', { level: 1, name: 'Pruebas de DEMO-3' })).toBeInTheDocument()
    expect(panel()).toHaveAttribute('data-size', 'lg')
    expect(within(panel()).getByText('Preparar pruebas de DEMO-3 · en revisión')).toBeInTheDocument()
    expect(within(panel()).getByText('Todos los CA cubiertos')).toBeInTheDocument()
    expect(within(panel()).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Casos (4)', 'Cobertura', 'Datos y riesgos', 'Estrategia'])
    expect(within(panel()).getByRole('tab', { name: 'Casos (4)' })).toHaveAttribute('aria-selected', 'true')
    expect(within(panel()).queryByRole('button', { name: 'Versión de Jira' })).toBeNull()
  })

  it('las pestañas muestran la cobertura, los datos y la estrategia', async () => {
    await openSuite()
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Cobertura' }))
    expect(within(panel()).getByRole('table', { name: 'Qué casos verifican cada CA y cada RN' })).toBeInTheDocument()
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Datos y riesgos' }))
    expect(within(panel()).getByRole('table', { name: 'Datos sintéticos de la suite' })).toBeInTheDocument()
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Estrategia' }))
    expect(within(panel()).getByRole('heading', { name: 'Alcance' })).toBeInTheDocument()
  })

  it('el asistente resume la suite sin LLM, con su tarjeta y las sugerencias de QA', async () => {
    await openSuite()
    expect(screen.getByText(/^Suite lista: 4 casos y todos los CA cubiertos\. Riesgo:/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Suite de pruebas, versión 1.*4 casos/ })).toHaveAttribute('aria-pressed', 'true')
    const suggestions = screen.getByRole('list', { name: 'Cambios sugeridos' })
    expect(within(suggestions).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'Añade un caso negativo con datos no válidos',
      'Cubre también las reglas de negocio',
      'Añade un caso de excepción',
    ])
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la suite/ })).toBeEnabled()
  })

  it('pedir un cambio crea la v2 con el caso nuevo marcado y el resumen de lo añadido', async () => {
    await openSuite()
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(await screen.findByText(/^Versión 2: añadí el CP-05 \(excepción\)\. 5 casos; la cobertura sigue completa\.$/)).toBeInTheDocument()
    expect(within(panel()).getByRole('tab', { name: 'Casos (5)' })).toHaveAttribute('aria-selected', 'true')
    expect(within(panel()).getByText('Nuevo en v2').closest('li')).toHaveTextContent('CP-05')
    const versions = within(panel()).getByRole('group', { name: 'Versiones' })
    expect(within(versions).getAllByRole('button').map((button) => button.textContent)).toEqual(['v1', 'v2'])
    const run = [...mockDb.runs.values()].find((item) => item.conversation.mode === 'qa')
    expect(run?.conversation.review?.plan).toEqual([{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '5' }])
  })

  it('*Descartar* habla de la suite', async () => {
    await openSuite()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Descartar' }))
    expect(within(panel()).getByRole('group', { name: 'Confirmar el descarte' })).toHaveTextContent(
      '¿Descartar la suite? No se publicará nada en Jira y la conversación terminará.',
    )
  })
})
