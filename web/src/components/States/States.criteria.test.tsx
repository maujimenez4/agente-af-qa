// Criterio 6 (UI.md §7, DESIGN-DECISIONS.md §6): EmptyState, ErrorCard por code, mensaje tal cual,
// cuenta atrás de retry_after acotada a 0–600, código desconocido, role="alert", LoadingState con
// aria-busy y Notice con role="note". Casos que no cubre States.test.tsx.
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EmptyState } from './EmptyState.tsx'
import { ErrorCard } from './ErrorCard.tsx'
import { ACTION_LABELS, presentError, retryDelay, type ApiError } from './errorPresentation.ts'
import { LoadingState } from './LoadingState.tsx'
import { Notice } from './Notice.tsx'
import { ProcessSteps } from './ProcessSteps.tsx'
import { latestSteps, type ProgressEvent } from './progressSteps.ts'
import { Skeleton } from './Skeleton.tsx'
import { SIMULATION_NOTICE } from './texts.ts'

const MESSAGE = 'Mensaje ficticio de la API para la prueba.'

function apiError(code: string, extra: Partial<ApiError> = {}): ApiError {
  return { code, message: MESSAGE, ...extra }
}

describe('EmptyState (UI.md §7)', () => {
  it('admite el estado vacío de otra pantalla con su título y texto', () => {
    render(<EmptyState title="Sin conversaciones" text="Empieza una nueva conversación." />)
    expect(screen.getByRole('heading', { name: 'Sin conversaciones' })).toBeInTheDocument()
    expect(screen.getByText('Empieza una nueva conversación.')).toBeInTheDocument()
    expect(screen.queryByText('Aún no hay propuesta')).toBeNull()
  })

  it('admite otro texto de acción', async () => {
    const onAction = vi.fn()
    render(<EmptyState actionLabel="Ir a Mixta 1" onAction={onAction} />)
    await userEvent.click(screen.getByRole('button', { name: 'Ir a Mixta 1' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('no usa el texto del lienzo que remite a la pestaña Contexto', () => {
    const { container } = render(<EmptyState onAction={vi.fn()} />)
    expect(container.textContent).not.toMatch(/pestaña/i)
  })

  it('muestra textos como texto, nunca como HTML', () => {
    const { container } = render(<EmptyState title="<b>T</b>" text="<img src=x>" />)
    expect(container.querySelector('b, img')).toBeNull()
  })
})

describe('presentError: tabla completa de DESIGN-DECISIONS.md §6', () => {
  it.each([
    ['rate_limited', 'Límite de uso alcanzado', 'warning', 'retry'],
    ['too_many_attempts', 'Demasiados intentos', 'warning', 'retry'],
    ['service_unavailable', 'Servicio no disponible', 'error', 'retry'],
    ['unauthenticated', 'Sesión caducada', 'neutral', 'login'],
    ['invalid_credentials', 'No se pudo iniciar sesión', 'error', undefined],
    ['forbidden', 'Sin permiso', 'neutral', undefined],
    ['not_found', 'No se encuentra', 'neutral', undefined],
    ['project_not_found', 'No se encuentra el proyecto', 'neutral', undefined],
    ['approval_rejected', 'Aprobación rechazada', 'error', 'restart'],
    ['not_in_review', 'La revisión ya no está abierta', 'warning', 'refresh'],
    ['invalid_request', 'Petición no válida', 'error', undefined],
  ])('%s → «%s», tono %s, acción %s', (code, title, tone, action) => {
    const presentation = presentError(apiError(code))
    expect(presentation.title).toBe(title)
    expect(presentation.tone).toBe(tone)
    expect(presentation.action).toBe(action)
  })

  it.each(['', 'RATE_LIMITED', 'rate_limited ', 'citation_error', 'coverage_error'])(
    'el código «%s» no es conocido: título genérico, tono error y sin acción',
    (code) => {
      expect(presentError(apiError(code))).toEqual({ title: 'No se pudo completar la acción', tone: 'error' })
    },
  )

  it.each(['toString', 'constructor', '__proto__', 'hasOwnProperty'])(
    'el código «%s» usa el título genérico',
    (code) => {
      expect(presentError(apiError(code)).title).toBe('No se pudo completar la acción')
    },
  )

  it('las acciones tienen sus textos en español', () => {
    expect(ACTION_LABELS).toEqual({
      retry: 'Reintentar',
      login: 'Iniciar sesión',
      restart: 'Empezar de nuevo',
      refresh: 'Actualizar',
      regenerate: 'Volver a generar',
      backToReceipt: 'Volver al recibo',
    })
  })
})

describe('retryDelay: acotado a 0–600 s', () => {
  it.each([
    [0, 0],
    [0.1, 1],
    [1, 1],
    [599.5, 600],
    [600, 600],
    [600.0001, 600],
    [601, 600],
    [-0.5, 0],
    [-600, 0],
    [Number.NaN, 0],
    [undefined, 0],
  ])('retry_after %s → %i s', (retryAfter, expected) => {
    expect(retryDelay(apiError('rate_limited', { retry_after: retryAfter }))).toBe(expected)
  })

  it('nunca devuelve -0', () => {
    expect(Object.is(retryDelay(apiError('rate_limited', { retry_after: -0.4 })), -0)).toBe(false)
  })
})

describe('ErrorCard', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it.each([
    ['too_many_attempts', 'Demasiados intentos'],
    ['invalid_credentials', 'No se pudo iniciar sesión'],
    ['forbidden', 'Sin permiso'],
    ['not_found', 'No se encuentra'],
    ['project_not_found', 'No se encuentra el proyecto'],
    ['not_in_review', 'La revisión ya no está abierta'],
    ['invalid_request', 'Petición no válida'],
    ['unauthenticated', 'Sesión caducada'],
  ])('%s: alerta con el título «%s»', (code, title) => {
    render(<ErrorCard error={apiError(code)} />)
    const alert = screen.getByRole('alert')
    expect(within(alert).getByRole('heading', { name: title })).toBeInTheDocument()
  })

  it('un código desconocido: título genérico, el mismo mensaje y tono error', () => {
    render(<ErrorCard error={apiError('citation_error')} onAction={vi.fn()} />)
    const alert = screen.getByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No se pudo completar la acción' })).toBeInTheDocument()
    expect(alert).toHaveTextContent(MESSAGE)
    expect(alert).toHaveAttribute('data-tone', 'error')
    // Sin acción en la tabla: no hay botón aunque la pantalla dé un manejador.
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('el mensaje se muestra literalmente, sin traducir ni recortar', () => {
    const message =
      'Todos los proveedores de la tarea «generate_story» han alcanzado su límite de uso. Espera unos minutos o elige otro modelo.'
    const { container } = render(<ErrorCard error={apiError('rate_limited', { message })} />)
    const paragraphs = [...container.querySelectorAll('p')].map((p) => p.textContent)
    expect(paragraphs).toContain(message)
  })

  it('el mensaje con etiquetas, entidades y comillas se muestra como texto', () => {
    const message = '<a href="javascript:alert(1)">pulsa</a> &amp; «DEMO-99» <svg onload=alert(1)>'
    const { container } = render(<ErrorCard error={apiError('not_found', { message })} />)
    expect(container.querySelector('a, svg[onload]')).toBeNull()
    const paragraphs = [...container.querySelectorAll('p')].map((p) => p.textContent)
    expect(paragraphs).toContain(message)
  })

  it.each([
    ['service_unavailable', 'Reintentar'],
    ['unauthenticated', 'Iniciar sesión'],
    ['not_in_review', 'Actualizar'],
    ['too_many_attempts', 'Reintentar'],
  ])('%s con manejador ofrece «%s»', async (code, label) => {
    const onAction = vi.fn()
    render(<ErrorCard error={apiError(code)} onAction={onAction} />)
    await userEvent.click(screen.getByRole('button', { name: label }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it.each(['invalid_credentials', 'forbidden', 'not_found', 'project_not_found', 'invalid_request'])(
    '%s no tiene acción: sin botón aunque haya manejador',
    (code) => {
      render(<ErrorCard error={apiError(code)} onAction={vi.fn()} />)
      expect(screen.queryByRole('button')).toBeNull()
    },
  )

  it('el botón de un error usa la variante de peligro; el de un aviso, la secundaria', () => {
    const { rerender } = render(<ErrorCard error={apiError('service_unavailable')} onAction={vi.fn()} />)
    const dangerClass = screen.getByRole('button').className
    rerender(<ErrorCard key="otro" error={apiError('not_in_review')} onAction={vi.fn()} />)
    expect(screen.getByRole('button').className).not.toBe(dangerClass)
  })

  it('el icono de aviso del título es decorativo (triángulo, decisión 6)', () => {
    const { container } = render(<ErrorCard error={apiError('forbidden')} />)
    const icon = container.querySelector('svg[data-icon="warning"]')
    expect(icon).toHaveAttribute('aria-hidden', 'true')
  })

  it('retry_after enorme: la cuenta atrás empieza en 600 s', () => {
    vi.useFakeTimers()
    render(<ErrorCard error={apiError('rate_limited', { retry_after: 86400 })} onAction={vi.fn()} />)
    expect(screen.getByText('Reintento disponible en 600 s')).toBeInTheDocument()
  })

  it('retry_after negativo o 0: se puede reintentar ya, sin cuenta atrás', () => {
    vi.useFakeTimers()
    render(<ErrorCard error={apiError('rate_limited', { retry_after: -10 })} onAction={vi.fn()} />)
    expect(screen.queryByText(/Reintento disponible/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('retry_after con decimales redondea hacia arriba', () => {
    vi.useFakeTimers()
    render(<ErrorCard error={apiError('rate_limited', { retry_after: 1.2 })} onAction={vi.fn()} />)
    expect(screen.getByText('Reintento disponible en 2 s')).toBeInTheDocument()
  })

  it('la cuenta atrás se ve aunque no haya manejador, y el temporizador se para al llegar a 0', () => {
    vi.useFakeTimers()
    render(<ErrorCard error={apiError('rate_limited', { retry_after: 3 })} />)
    expect(screen.getByText('Reintento disponible en 3 s')).toHaveClass('tabular-nums')
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.queryByText(/Reintento disponible/)).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(screen.queryByText(/-\d+ s/)).toBeNull()
  })

  it('solo hay cuenta atrás si la acción es reintentar (not_in_review con retry_after, no)', () => {
    vi.useFakeTimers()
    render(<ErrorCard error={apiError('not_in_review', { retry_after: 30 })} onAction={vi.fn()} />)
    expect(screen.queryByText(/Reintento disponible/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Actualizar' })).toBeEnabled()
  })

  it('un código desconocido con retry_after no muestra cuenta atrás', () => {
    vi.useFakeTimers()
    render(<ErrorCard error={apiError('algo_nuevo', { retry_after: 30 })} />)
    expect(screen.queryByText(/Reintento disponible/)).toBeNull()
  })

  it('el botón desactivado durante la cuenta atrás no responde al pulsarlo', () => {
    vi.useFakeTimers()
    const onAction = vi.fn()
    render(<ErrorCard error={apiError('rate_limited', { retry_after: 5 })} onAction={onAction} />)
    act(() => {
      screen.getByRole('button', { name: 'Reintentar' }).click()
    })
    expect(onAction).not.toHaveBeenCalled()
  })

  it('al desmontarse durante la cuenta atrás no deja temporizadores', () => {
    vi.useFakeTimers()
    const { unmount } = render(<ErrorCard error={apiError('rate_limited', { retry_after: 30 })} />)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('con otra key reinicia la cuenta atrás para el error nuevo', () => {
    vi.useFakeTimers()
    const { rerender } = render(<ErrorCard key="1" error={apiError('rate_limited', { retry_after: 5 })} />)
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    rerender(<ErrorCard key="2" error={apiError('rate_limited', { retry_after: 10 })} />)
    expect(screen.getByText('Reintento disponible en 10 s')).toBeInTheDocument()
  })
})

describe('LoadingState', () => {
  const RUNNING: ProgressEvent[] = [
    { node: 'load_origin', label: 'Cargar el origen', state: 'done' },
    { node: 'retrieve_context', label: 'Recuperar contexto', state: 'running' },
  ]

  it('sin eventos está ocupado y con la Q vacía', () => {
    const { container } = render(<LoadingState title="Generando la suite…" events={[]} />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    expect(container.querySelector<SVGRectElement>('clipPath rect')?.style.getPropertyValue('--q-to')).toBe('326px')
  })

  it('marca el paso en curso con aria-current="step"', () => {
    render(<LoadingState title="Generando la propuesta…" events={RUNNING} />)
    const items = screen.getAllByRole('listitem')
    expect(items[1]).toHaveAttribute('aria-current', 'step')
    expect(items[1]).toHaveTextContent('Recuperar contexto')
  })

  it('la Q de carga es decorativa: la lista de procesos ya informa', () => {
    const { container } = render(<LoadingState title="Generando la propuesta…" events={RUNNING} />)
    expect(screen.queryByRole('img')).toBeNull()
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('con review_ready deja de estar ocupado aunque se perdieran progress', () => {
    const { container } = render(<LoadingState title="Propuesta lista" events={[]} reviewReady />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'false')
    expect(container.querySelector<SVGRectElement>('clipPath rect')?.style.getPropertyValue('--q-to')).toBe('0px')
  })

  it('el título se muestra como texto, nunca como HTML', () => {
    const { container } = render(<LoadingState title="<b>Generando</b>" events={[]} />)
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByRole('heading')).toHaveTextContent('<b>Generando</b>')
  })
})

describe('ProcessSteps y latestSteps', () => {
  it('numera los pasos no hechos y pone la marca de hecho en los terminados', () => {
    const { container } = render(
      <ProcessSteps
        steps={[
          { node: 'load_origin', label: 'Cargar el origen', state: 'done' },
          { node: 'retrieve_context', label: 'Recuperar contexto', state: 'running' },
          { node: 'generate', label: 'Generar la versión 1', state: 'pending' },
        ]}
      />,
    )
    const marks = [...container.querySelectorAll('li > span[aria-hidden="true"]')]
    expect(marks[0]?.querySelector('svg[data-icon="done"]')).not.toBeNull()
    expect(marks[1]).toHaveTextContent('2')
    expect(marks[2]).toHaveTextContent('3')
    expect(screen.getAllByRole('listitem')[2]).toHaveTextContent('(pendiente)')
  })

  it('es una lista ordenada', () => {
    render(<ProcessSteps steps={[{ node: 'generate', label: 'Generar', state: 'pending' }]} />)
    expect(screen.getByRole('list').tagName).toBe('OL')
  })

  it('latestSteps sin eventos no devuelve pasos', () => {
    expect(latestSteps([])).toEqual([])
  })

  it('latestSteps conserva el orden de aparición aunque un nodo anterior se actualice después', () => {
    const steps = latestSteps([
      { node: 'load_origin', label: 'Cargar', state: 'running' },
      { node: 'retrieve_context', label: 'Recuperar', state: 'running' },
      { node: 'load_origin', label: 'Cargar · hecho', state: 'done' },
    ])
    expect(steps.map((step) => step.node)).toEqual(['load_origin', 'retrieve_context'])
    expect(steps[0]?.label).toBe('Cargar · hecho')
  })
})

describe('Notice', () => {
  it('es una nota, no una alerta ni un estado', () => {
    render(<Notice>{SIMULATION_NOTICE}</Notice>)
    expect(screen.getByRole('note')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('el texto del modo de prueba es el de UI.md §2', () => {
    expect(SIMULATION_NOTICE).toBe(
      'Modo de prueba: al aprobar verás lo que se haría en Jira, pero no se escribirá nada.',
    )
  })

  it('lleva el icono de aviso (triángulo) decorativo', () => {
    const { container } = render(<Notice>Aviso ficticio</Notice>)
    expect(container.querySelector('svg[data-icon="warning"]')).toHaveAttribute('aria-hidden', 'true')
  })

  it('muestra el texto como texto, nunca como HTML', () => {
    const { container } = render(<Notice>{'<b>aviso</b>'}</Notice>)
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByRole('note')).toHaveTextContent('<b>aviso</b>')
  })
})

describe('Skeleton', () => {
  it('por defecto pinta 4 líneas', () => {
    const { container } = render(<Skeleton />)
    expect(container.querySelector('[data-skeleton]')?.children).toHaveLength(4)
  })

  it('con 0 líneas no pinta ninguna', () => {
    const { container } = render(<Skeleton lines={0} />)
    expect(container.querySelector('[data-skeleton]')?.children).toHaveLength(0)
  })

  it('más líneas que anchos: repite los anchos en ciclo', () => {
    const { container } = render(<Skeleton lines={8} />)
    const widths = [...(container.querySelector('[data-skeleton]')?.children ?? [])].map(
      (line) => (line as HTMLElement).style.width,
    )
    expect(widths).toHaveLength(8)
    expect(widths[6]).toBe(widths[0])
    expect(widths.every((width) => width !== '')).toBe(true)
  })
})

describe('correcciones tras la revisión', () => {
  it('retry_after infinito se acota a 600 s, no deja reintentar ya', () => {
    expect(retryDelay(apiError('rate_limited', { retry_after: Number.POSITIVE_INFINITY }))).toBe(600)
  })

  it('la cuenta atrás no se vuelve a anunciar cada segundo: es visual y hay una frase fija para lectores', () => {
    vi.useFakeTimers()
    render(<ErrorCard error={apiError('rate_limited', { retry_after: 3 })} onAction={vi.fn()} />)
    const alert = screen.getByRole('alert')
    expect(within(alert).getByText('Podrás reintentar dentro de 3 segundos.')).toHaveClass('visually-hidden')
    expect(within(alert).getByText('Reintento disponible en 3 s')).toHaveAttribute('aria-hidden', 'true')
    vi.useRealTimers()
  })
})
