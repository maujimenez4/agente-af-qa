// Revisión general del pulido (axe `scrollable-region-focusable`): el cuerpo del informe de calidad, que no tiene
// controles, es una región con nombre que se alcanza con Tab. Datos sintéticos (DEMO-3, af-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb } from '../../mocks/node.ts'

describe('Revisar la calidad · cuerpo del informe enfocable', () => {
  it('test_report_body_is_named_region_with_tab_stop', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Revisar la calidad de DEMO-3/ }))
    const panel = await screen.findByRole('complementary', { name: 'Informe de calidad' })
    const body = within(panel).getByRole('region', { name: 'Contenido del informe de calidad' })
    expect(body).toHaveAttribute('tabindex', '0')
    expect(within(body).getByText('INVEST', { exact: false })).toBeInTheDocument()
  })
})
