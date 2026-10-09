// Criterio 10 (T-56, días 2-4): pintado de la tarjeta de error para códigos de la generación con su acción
// (DESIGN-DECISIONS.md §6, UI.md §7). Los títulos de los 25 códigos ya los prueba errorCodes.test.ts.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ApiError } from '../../api/types.ts'
import { ErrorCard } from './ErrorCard.tsx'

// Mensajes de UI.md §7 y docs/api/README.md (sintéticos, del código del proyecto).
const GENERATION_CASES = [
  {
    code: 'citation_failed',
    title: 'FAQ no ha podido citar sus fuentes',
    message: 'La propuesta cita fuentes que no están en el contexto recibido. Vuelve a generarla.',
    action: 'Volver a generar',
    tone: 'error',
  },
  {
    code: 'coverage_failed',
    title: 'FAQ no ha podido cubrir todos los criterios',
    message:
      'La suite de pruebas no cubre la HU: algún criterio no tiene casos, faltan casos positivos o negativos, se referencian CA/RN inexistentes o hay datos que parecen personales. Vuelve a generarla.',
    action: 'Volver a generar',
    tone: 'error',
  },
  {
    code: 'invalid_model_output',
    title: 'FAQ no ha podido terminar la propuesta',
    message: 'El modelo devolvió una salida que no cumple el esquema (ficticio).',
    action: 'Volver a generar',
    tone: 'error',
  },
  {
    code: 'provider_timeout',
    title: 'El modelo no respondió a tiempo',
    message: 'El modelo local no respondió a tiempo (ficticio).',
    action: 'Volver a generar',
    tone: 'warning',
  },
  {
    code: 'quality_failed',
    title: 'FAQ no ha podido revisar la calidad',
    message: 'No se pudo completar la revisión de calidad (ficticio).',
    action: 'Reintentar',
    tone: 'error',
  },
  {
    code: 'publish_failed',
    title: 'No se puede publicar',
    message: 'No consta una aprobación humana vigente para esta versión exacta del artefacto.',
    action: 'Volver al recibo',
    tone: 'error',
  },
] as const

describe('ErrorCard: códigos de la generación con acción', () => {
  it.each(GENERATION_CASES)('test_generation_error_$code_renders_title_message_and_action', async ({ code, title, message, action, tone }) => {
    /** Criterio 10: título por código, mensaje tal cual, tono y botón de la acción que llama al manejador. */
    const onAction = vi.fn()
    render(<ErrorCard error={{ code, message, retry_after: null }} onAction={onAction} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveAttribute('data-tone', tone)
    expect(within(alert).getByRole('heading', { level: 2, name: title })).toBeInTheDocument()
    expect(within(alert).getByText(message)).toBeInTheDocument()
    const button = within(alert).getByRole('button', { name: action })
    expect(button).toBeEnabled()
    await userEvent.click(button)
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it.each(GENERATION_CASES)('test_generation_error_$code_without_handler_has_no_button', ({ code, message }) => {
    /** Criterio 10 (negativo): sin manejador no se pinta la acción. */
    render(<ErrorCard error={{ code, message }} />)
    expect(within(screen.getByRole('alert')).queryByRole('button')).toBeNull()
  })

  it('test_rate_limited_from_generation_waits_retry_after', () => {
    /** Criterio 10: rate_limited con retry_after (UI.md §7) desactiva «Reintentar» y muestra la espera. */
    const error: ApiError = {
      code: 'rate_limited',
      message: 'Todos los proveedores de la tarea «generate_story» han alcanzado su límite de uso. Espera unos minutos o elige otro modelo.',
      retry_after: 12,
    }
    render(<ErrorCard error={error} onAction={vi.fn()} />)
    const alert = screen.getByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Límite de uso alcanzado' })).toBeInTheDocument()
    expect(alert).toHaveAttribute('data-tone', 'warning')
    expect(within(alert).getByRole('button', { name: 'Reintentar' })).toBeDisabled()
    expect(alert).toHaveTextContent('Reintento disponible en 12 s')
    expect(alert).toHaveTextContent('Podrás reintentar dentro de 12 segundos.')
  })

  it('test_regenerate_ignores_retry_after_no_countdown', () => {
    /** Criterio 10 (límite): «Volver a generar» no espera aunque llegue retry_after (solo «Reintentar» cuenta atrás). */
    render(<ErrorCard error={{ code: 'provider_timeout', message: 'x', retry_after: 30 }} onAction={vi.fn()} />)
    const alert = screen.getByRole('alert')
    expect(within(alert).getByRole('button', { name: 'Volver a generar' })).toBeEnabled()
    expect(alert).not.toHaveTextContent('Reintento disponible')
  })

  it('test_error_button_variants_by_tone', () => {
    /** Criterio 10: la acción de un error usa la variante de peligro y la de un aviso, la secundaria. */
    const { rerender } = render(<ErrorCard error={{ code: 'citation_failed', message: 'x' }} onAction={vi.fn()} />)
    const danger = screen.getByRole('button', { name: 'Volver a generar' }).className
    rerender(<ErrorCard key="otro" error={{ code: 'provider_timeout', message: 'x' }} onAction={vi.fn()} />)
    const secondary = screen.getByRole('button', { name: 'Volver a generar' }).className
    expect(danger).not.toBe(secondary)
  })

  it('test_generation_message_with_quotes_and_markup_is_text', () => {
    /** Criterio 10 (seguridad): el mensaje con «comillas» y etiquetas se muestra literal. */
    const message = 'La propuesta cita «DOC-1» y <script>alert(1)</script> (ficticio).'
    const { container } = render(<ErrorCard error={{ code: 'citation_failed', message }} onAction={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent(message)
    expect(container.querySelector('script')).toBeNull()
  })
})
