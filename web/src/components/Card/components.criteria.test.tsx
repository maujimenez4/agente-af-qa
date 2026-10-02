// Criterio 5: variantes, desactivado, nombre accesible de los botones solo icono y FlowCard
// (aria-pressed / aria-disabled con la ayuda del rol y sin efecto, UI.md §3). Casos que no cubren
// Button.test.tsx, Chip.test.tsx, Badge.test.tsx ni Card.test.tsx.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Badge, CaseKindBadge } from '../Badge/index.ts'
import badgeStyles from '../Badge/Badge.module.css'
import { Button, IconButton } from '../Button/index.ts'
import buttonStyles from '../Button/Button.module.css'
import { Chip } from '../Chip/index.ts'
import chipStyles from '../Chip/Chip.module.css'
import { Card, FlowCard } from './Card.tsx'

describe('Button: variantes y tamaños', () => {
  it('por defecto es secundario y grande', () => {
    render(<Button>Descartar</Button>)
    const button = screen.getByRole('button', { name: 'Descartar' })
    expect(button).toHaveClass(buttonStyles.secondary as string, buttonStyles.lg as string)
  })

  it.each(['primary', 'secondary', 'ghost', 'danger'] as const)('la variante %s lleva su clase', (variant) => {
    render(<Button variant={variant}>Acción ficticia</Button>)
    expect(screen.getByRole('button')).toHaveClass(buttonStyles[variant] as string)
  })

  it.each([
    ['lg', '18'],
    ['md', '18'],
    ['sm', '14'],
  ] as const)('tamaño %s: clase propia e icono de %s px', (size, iconSize) => {
    const { container } = render(
      <Button size={size} icon="new">
        Nueva
      </Button>,
    )
    expect(screen.getByRole('button')).toHaveClass(buttonStyles[size] as string)
    expect(container.querySelector('svg')).toHaveAttribute('width', iconSize)
  })

  it('respeta type="submit" si se pide', () => {
    render(<Button type="submit">Enviar formulario</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'submit')
  })

  it('conserva una clase extra sin perder las suyas', () => {
    render(<Button className="extra-demo">Acción</Button>)
    const button = screen.getByRole('button')
    expect(button).toHaveClass('extra-demo', buttonStyles.button as string)
  })

  it('desactivado no recibe el foco con el teclado ni responde a Enter', async () => {
    const onClick = vi.fn()
    render(
      <>
        <Button disabled onClick={onClick}>
          Aprobar y publicar
        </Button>
        <Button>Otra acción</Button>
      </>,
    )
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Otra acción' })).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(onClick).not.toHaveBeenCalled()
  })

  it('pasa los atributos ARIA nativos (aria-pressed en los conmutadores)', () => {
    render(<Button aria-pressed>Fase 2</Button>)
    expect(screen.getByRole('button', { name: 'Fase 2' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('muestra el texto como texto, nunca como HTML', () => {
    const { container } = render(<Button>{'<img src=x onerror=alert(1)>'}</Button>)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('button')).toHaveTextContent('<img src=x onerror=alert(1)>')
  })
})

describe('IconButton: solo icono', () => {
  it('por defecto es ghost y mediano, con la clase de solo icono', () => {
    render(<IconButton icon="close" label="Cerrar" />)
    expect(screen.getByRole('button', { name: 'Cerrar' })).toHaveClass(
      buttonStyles.ghost as string,
      buttonStyles.md as string,
      buttonStyles.iconOnly as string,
    )
  })

  it('el icono es decorativo: el nombre lo da label', () => {
    const { container } = render(<IconButton icon="send" label="Enviar" variant="primary" />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('button')).toHaveAccessibleName('Enviar')
  })

  it('es type="button" por defecto', () => {
    render(<IconButton icon="stop" label="Detener" />)
    expect(screen.getByRole('button', { name: 'Detener' })).toHaveAttribute('type', 'button')
  })

  it('desactivado conserva su nombre accesible y no responde', async () => {
    const onClick = vi.fn()
    render(<IconButton icon="send" label="Enviar" disabled onClick={onClick} />)
    const button = screen.getByRole('button', { name: 'Enviar' })
    expect(button).toBeDisabled()
    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('el tamaño pequeño usa un icono de 14 px', () => {
    const { container } = render(<IconButton icon="close" label="Cerrar" size="sm" />)
    expect(container.querySelector('svg')).toHaveAttribute('width', '14')
  })
})

describe('Chip', () => {
  it('por defecto es una sugerencia de tipo button', () => {
    render(<Chip>Añade un caso negativo</Chip>)
    const chip = screen.getByRole('button', { name: 'Añade un caso negativo' })
    expect(chip).toHaveAttribute('type', 'button')
    expect(chip).toHaveClass(chipStyles.suggestion as string)
  })

  it('el reciente lleva su variante y la clave en negrita aparte del título', () => {
    const { container } = render(
      <Chip variant="recent" issueKey="DEMO-3">
        Renovar un préstamo
      </Chip>,
    )
    expect(screen.getByRole('button')).toHaveClass(chipStyles.recent as string)
    expect(container.querySelector(`.${chipStyles.key as string}`)).toHaveTextContent('DEMO-3')
  })

  it('sin issueKey no pinta la clave', () => {
    const { container } = render(<Chip variant="recent">Solo título</Chip>)
    expect(container.querySelector(`.${chipStyles.key as string}`)).toBeNull()
  })

  it('desactivado no responde', async () => {
    const onClick = vi.fn()
    render(
      <Chip disabled onClick={onClick}>
        Sugerencia ficticia
      </Chip>,
    )
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('la clave de Jira se muestra como texto, nunca como HTML', () => {
    const { container } = render(
      <Chip variant="recent" issueKey="<b>DEMO-3</b>">
        Título
      </Chip>,
    )
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByRole('button')).toHaveTextContent('<b>DEMO-3</b>')
  })
})

describe('Badge', () => {
  it('por defecto es neutro y pequeño', () => {
    render(<Badge>DOC-01</Badge>)
    const badge = screen.getByText('DOC-01')
    expect(badge).toHaveAttribute('data-tone', 'neutral')
    expect(badge).toHaveClass(badgeStyles.sm as string, badgeStyles.neutral as string)
  })

  it.each([
    ['sm', '14'],
    ['md', '16'],
  ] as const)('tamaño %s: icono de %s px', (size, iconSize) => {
    const { container } = render(
      <Badge size={size} icon="done">
        Hecho
      </Badge>,
    )
    expect(container.querySelector('svg')).toHaveAttribute('width', iconSize)
  })

  it('no es enfocable', async () => {
    render(<Badge tone="success">Pasó</Badge>)
    await userEvent.tab()
    expect(document.body).toHaveFocus()
  })

  it('muestra el texto como texto, nunca como HTML', () => {
    const { container } = render(<Badge>{'<script>x</script>'}</Badge>)
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText('<script>x</script>')).toBeInTheDocument()
  })

  it('CaseKindBadge muestra el tipo de caso tal cual', () => {
    render(<CaseKindBadge kind="Excepción" />)
    expect(screen.getByText('Excepción')).toHaveClass(badgeStyles.warning as string)
  })
})

describe('Card', () => {
  it('sin título no es una región con nombre ni tiene encabezado', () => {
    const { container } = render(
      <Card>
        <p>Contenido ficticio</p>
      </Card>,
    )
    expect(screen.queryByRole('region')).toBeNull()
    expect(screen.queryByRole('heading')).toBeNull()
    expect(container.querySelector('section')).not.toHaveAttribute('aria-labelledby')
  })

  it('pinta la descripción solo si se da', () => {
    const { rerender } = render(<Card title="Fuentes" />)
    expect(screen.queryByRole('paragraph')).toBeNull()
    rerender(<Card title="Fuentes" description="Elige las fuentes ficticias." />)
    expect(screen.getByText('Elige las fuentes ficticias.')).toBeInTheDocument()
  })

  it('dos tarjetas en la página tienen ids de título distintos', () => {
    render(
      <>
        <Card title="Uno" />
        <Card title="Dos" />
      </>,
    )
    const ids = screen.getAllByRole('heading').map((heading) => heading.id)
    expect(new Set(ids).size).toBe(2)
    expect(screen.getByRole('region', { name: 'Uno' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Dos' })).toBeInTheDocument()
  })

  it('el título y la descripción se muestran como texto, nunca como HTML', () => {
    const { container } = render(<Card title="<b>Título</b>" description="<i>Descripción</i>" />)
    expect(container.querySelector('b, i')).toBeNull()
    expect(screen.getByRole('heading', { name: '<b>Título</b>' })).toBeInTheDocument()
  })
})

describe('FlowCard (UI.md §3)', () => {
  const base = {
    label: 'Preparar pruebas',
    hint: 'Casos, cobertura, datos y estrategia de una HU.',
    icon: 'tests' as const,
  }

  it('el icono es decorativo, el nombre accesible es la etiqueta y la ayuda su descripción', () => {
    const { container } = render(<FlowCard {...base} selected={false} onSelect={vi.fn()} />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('button')).toHaveAccessibleName(base.label)
    expect(screen.getByRole('button')).toHaveAccessibleDescription(base.hint)
  })

  it('se elige con el teclado (Enter y Espacio)', async () => {
    const onSelect = vi.fn()
    render(<FlowCard {...base} selected={false} onSelect={onSelect} />)
    screen.getByRole('button').focus()
    await userEvent.keyboard('{Enter}')
    await userEvent.keyboard(' ')
    expect(onSelect).toHaveBeenCalledTimes(2)
  })

  it('activa no lleva aria-disabled', () => {
    render(<FlowCard {...base} selected onSelect={vi.fn()} />)
    expect(screen.getByRole('button')).not.toHaveAttribute('aria-disabled')
  })

  it.each(['Disponible para el rol de analista funcional.', 'Disponible para el rol QA.'])(
    'desactivada con «%s»: la ayuda es la descripción accesible',
    (hint) => {
      render(<FlowCard {...base} selected={false} onSelect={vi.fn()} disabledHint={hint} />)
      const card = screen.getByRole('button')
      expect(card).toHaveAttribute('aria-disabled', 'true')
      expect(card).toHaveAccessibleName(base.label)
      expect(card).toHaveAccessibleDescription(hint)
    },
  )

  it('desactivada no tiene efecto con el teclado', async () => {
    const onSelect = vi.fn()
    render(<FlowCard {...base} selected={false} onSelect={onSelect} disabledHint="Disponible para el rol QA." />)
    const card = screen.getByRole('button')
    await userEvent.tab()
    expect(card).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    await userEvent.keyboard(' ')
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('desactivada nunca se anuncia como seleccionada, aunque selected sea true', () => {
    render(<FlowCard {...base} selected onSelect={vi.fn()} disabledHint="Disponible para el rol QA." />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false')
  })

  it('una ayuda de rol vacía también la desactiva', () => {
    render(<FlowCard {...base} selected onSelect={vi.fn()} disabledHint="" />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-disabled', 'true')
  })

  it('es type="button" para no enviar formularios', () => {
    render(<FlowCard {...base} selected={false} onSelect={vi.fn()} />)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })
})
