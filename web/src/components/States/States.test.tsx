import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EmptyState } from './EmptyState.tsx'
import { ErrorCard } from './ErrorCard.tsx'
import { presentError, retryDelay } from './errorPresentation.ts'
import { LoadingState } from './LoadingState.tsx'
import { Notice } from './Notice.tsx'
import { ProcessSteps } from './ProcessSteps.tsx'
import { latestSteps, type ProgressEvent } from './progressSteps.ts'
import { Skeleton } from './Skeleton.tsx'
import { SIMULATION_NOTICE } from './texts.ts'

const EVENTS: ProgressEvent[] = [
  { node: 'load_origin', label: 'Cargar el origen', state: 'done' },
  { node: 'retrieve_context', label: 'Recuperar contexto', state: 'running' },
  { node: 'retrieve_context', label: 'Recuperar contexto · 5 fuentes', state: 'done' },
  { node: 'generate', label: 'Generar la versión 1', state: 'running' },
]

describe('EmptyState', () => {
  it('por defecto usa el texto de UI.md §7, no el del lienzo', () => {
    render(<EmptyState />)
    expect(screen.getByRole('heading', { name: 'Aún no hay propuesta' })).toBeInTheDocument()
    expect(screen.getByText('Elige un origen para generar la primera versión de la HU.')).toBeInTheDocument()
    expect(screen.queryByText(/Contexto/)).toBeNull()
  })

  it('solo pinta la acción si hay a dónde ir', async () => {
    const onAction = vi.fn()
    const { rerender } = render(<EmptyState />)
    expect(screen.queryByRole('button')).toBeNull()
    rerender(<EmptyState onAction={onAction} />)
    await userEvent.click(screen.getByRole('button', { name: 'Elegir un origen' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })
})

describe('latestSteps', () => {
  it('deja un paso por nodo, en orden de aparición, con su último estado y texto', () => {
    expect(latestSteps(EVENTS)).toEqual([
      { node: 'load_origin', label: 'Cargar el origen', state: 'done' },
      { node: 'retrieve_context', label: 'Recuperar contexto · 5 fuentes', state: 'done' },
      { node: 'generate', label: 'Generar la versión 1', state: 'running' },
    ])
  })
})

describe('ProcessSteps', () => {
  it('marca el paso en curso con aria-current="step" y anuncia el estado de cada uno', () => {
    render(<ProcessSteps steps={latestSteps(EVENTS)} />)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0]).toHaveTextContent('Cargar el origen(hecho)')
    expect(items[2]).toHaveAttribute('aria-current', 'step')
    expect(items[2]).toHaveTextContent('(en curso)')
    expect(items[0]).not.toHaveAttribute('aria-current')
  })

  it('usa el texto del paso tal cual, como texto', () => {
    const { container } = render(
      <ProcessSteps steps={[{ node: 'generate', label: '<b>Generar</b>', state: 'pending' }]} />,
    )
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByRole('listitem')).toHaveTextContent('<b>Generar</b>')
  })
})

describe('LoadingState', () => {
  it('muestra el título, la Q por procesos y la lista de pasos', () => {
    const { container } = render(<LoadingState title="Generando la propuesta…" events={EVENTS} />)
    const status = screen.getByRole('status')
    expect(within(status).getByRole('heading', { name: 'Generando la propuesta…' })).toBeInTheDocument()
    expect(status).toHaveAttribute('aria-busy', 'true')
    // Dos nodos hechos y generate en curso: la Q se anima dentro del 3.er cuarto.
    const rect = container.querySelector<SVGRectElement>('clipPath rect')
    expect(rect?.dataset.qMotion).toBe('pulse')
    expect(rect?.style.getPropertyValue('--q-to')).toBe('163px')
  })

  it('con review_ready la Q se llena y deja de estar ocupado', () => {
    const { container } = render(<LoadingState title="Propuesta lista" events={EVENTS} reviewReady />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'false')
    expect(container.querySelector<SVGRectElement>('clipPath rect')?.style.getPropertyValue('--q-to')).toBe('0px')
  })
})

describe('presentError', () => {
  it.each([
    ['rate_limited', 'Límite de uso alcanzado', 'warning', 'retry'],
    ['service_unavailable', 'Servicio no disponible', 'error', 'retry'],
    ['unauthenticated', 'Sesión caducada', 'neutral', 'login'],
    ['approval_rejected', 'Aprobación rechazada', 'error', 'restart'],
    ['not_in_review', 'La revisión ya no está abierta', 'warning', 'refresh'],
    ['forbidden', 'Sin permiso', 'neutral', undefined],
  ])('%s → «%s»', (code, title, tone, action) => {
    expect(presentError({ code, message: 'x' })).toEqual({ title, tone, ...(action ? { action } : {}) })
  })

  it('un código desconocido usa un título genérico', () => {
    expect(presentError({ code: 'algo_nuevo', message: 'x' }).title).toBe('No se pudo completar la acción')
  })

  it('acota retry_after a 0–600 s', () => {
    expect(retryDelay({ code: 'rate_limited', message: 'x', retry_after: 44.2 })).toBe(45)
    expect(retryDelay({ code: 'rate_limited', message: 'x', retry_after: 99999 })).toBe(600)
    expect(retryDelay({ code: 'rate_limited', message: 'x', retry_after: -3 })).toBe(0)
    expect(retryDelay({ code: 'rate_limited', message: 'x', retry_after: null })).toBe(0)
  })
})

describe('ErrorCard', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('es una alerta con el título por código y el mensaje de la API tal cual', () => {
    const message = 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.'
    render(<ErrorCard error={{ code: 'service_unavailable', message }} />)
    const alert = screen.getByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
    expect(alert).toHaveTextContent(message)
  })

  it('nunca interpreta el mensaje como HTML', () => {
    const message = '<img src=x onerror=alert(1)>Fallo'
    const { container } = render(<ErrorCard error={{ code: 'invalid_request', message }} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('alert')).toHaveTextContent(message)
  })

  it('ofrece la acción del código solo si se le da un manejador', async () => {
    const onAction = vi.fn()
    const { rerender } = render(<ErrorCard error={{ code: 'approval_rejected', message: 'x' }} />)
    expect(screen.queryByRole('button')).toBeNull()
    rerender(<ErrorCard error={{ code: 'approval_rejected', message: 'x' }} onAction={onAction} />)
    await userEvent.click(screen.getByRole('button', { name: 'Empezar de nuevo' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('con retry_after cuenta atrás y solo deja reintentar al terminar', () => {
    vi.useFakeTimers()
    render(
      <ErrorCard
        error={{ code: 'rate_limited', message: 'Todos los proveedores han alcanzado su límite.', retry_after: 2 }}
        onAction={vi.fn()}
      />,
    )
    expect(screen.getByText('Reintento disponible en 2 s')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeDisabled()
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(screen.getByText('Reintento disponible en 1 s')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(screen.queryByText(/Reintento disponible/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled()
  })

  it('el tono sale del código', () => {
    render(<ErrorCard error={{ code: 'rate_limited', message: 'x' }} />)
    expect(screen.getByRole('alert')).toHaveAttribute('data-tone', 'warning')
  })
})

describe('Notice', () => {
  it('es una nota con el texto del modo de prueba', () => {
    render(<Notice>{SIMULATION_NOTICE}</Notice>)
    expect(screen.getByRole('note')).toHaveTextContent(
      'Modo de prueba: al aprobar verás lo que se haría en Jira, pero no se escribirá nada.',
    )
  })
})

describe('Skeleton', () => {
  it('es decorativo y pinta las líneas pedidas', () => {
    const { container } = render(<Skeleton lines={3} />)
    const skeleton = container.querySelector('[data-skeleton]')
    expect(skeleton).toHaveAttribute('aria-hidden', 'true')
    expect(skeleton?.children).toHaveLength(3)
  })
})
