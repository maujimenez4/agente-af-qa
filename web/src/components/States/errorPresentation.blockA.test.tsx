// Bloque A (T-56): los códigos nuevos cancelled, not_cancellable y not_in_error, tal como los fija la tabla de
// DESIGN-DECISIONS.md §6, y su tarjeta en pantalla. Mensajes ficticios.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import designDecisions from '../../../DESIGN-DECISIONS.md?raw'
import type { ErrorCode } from '../../api/types.ts'
import { ErrorCard } from './ErrorCard.tsx'
import { ACTION_LABELS, presentError } from './errorPresentation.ts'

const TONES: Record<string, string> = { Aviso: 'warning', Error: 'error', Neutro: 'neutral' }

/** Fila de la tabla §6 de un código: título, tono y la primera palabra(s) de la acción. */
function row(code: string): { title: string; tone: string; action: string } {
  const line = designDecisions.split('\n').find((item) => item.includes(`| \`${code}\` |`))
  if (!line) throw new Error(`Falta ${code} en la tabla de §6`)
  const [, , , title = '', tone = '', action = ''] = line.split('|').map((cell) => cell.trim())
  return { title, tone: TONES[tone] ?? tone, action }
}

const NEW_CODES: ErrorCode[] = ['cancelled', 'not_cancellable', 'not_in_error']

describe('§6: códigos nuevos del bloque A (bloque A)', () => {
  it.each(NEW_CODES)('%s: título, tono y acción como en la tabla de §6', (code) => {
    /** DESIGN-DECISIONS.md §6 (tabla de códigos). */
    const expected = row(code)
    const presentation = presentError({ code, message: 'Mensaje ficticio.' })
    expect(presentation.title).toBe(expected.title)
    expect(presentation.tone).toBe(expected.tone)
    expect(presentation.action).toBeDefined()
    expect(expected.action.startsWith(ACTION_LABELS[presentation.action ?? 'retry'])).toBe(true)
  })

  it.each([
    ['cancelled', 'Generación detenida', 'Reintentar'],
    ['not_cancellable', 'No se puede detener', 'Actualizar'],
    ['not_in_error', 'No hay nada que reintentar', 'Actualizar'],
  ] as const)('la tarjeta de %s muestra «%s», el mensaje tal cual y «%s»', async (code, title, action) => {
    /** §6 y UI.md §7: título por código y mensaje de la API sin tocar. */
    const onAction = vi.fn()
    render(<ErrorCard error={{ code, message: `Mensaje ficticio de ${code}.`, retry_after: null }} onAction={onAction} />)
    const alert = screen.getByRole('alert')
    expect(within(alert).getByRole('heading', { name: title })).toBeInTheDocument()
    expect(alert).toHaveTextContent(`Mensaje ficticio de ${code}.`)
    await userEvent.click(within(alert).getByRole('button', { name: action }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('cancelled con retry_after no espera: «Reintentar» está activo enseguida', () => {
    /** Límite: la cuenta atrás de §6 es de too_many_attempts y rate_limited, no de cancelled. */
    render(<ErrorCard error={{ code: 'cancelled', message: 'Detenida (ficticio).', retry_after: 0 }} onAction={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled()
  })
})
