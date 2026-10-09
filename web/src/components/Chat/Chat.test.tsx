import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AssistantMessage, ChatLog, FixedOperation, FoundIssue, UserMessage } from './Chat.tsx'

describe('Chat', () => {
  it('la conversación es un role="log" con un elemento por mensaje', () => {
    render(
      <ChatLog>
        <UserMessage>La persona socia debería poder ampliar el plazo desde la app.</UserMessage>
        <AssistantMessage>He preparado el contexto.</AssistantMessage>
      </ChatLog>,
    )
    const log = screen.getByRole('log', { name: 'Conversación' })
    const items = within(log).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('Tú: La persona socia')
    expect(items[1]).toHaveTextContent('FAQ: He preparado el contexto.')
  })

  it('los mensajes muestran el texto tal cual, nunca como HTML', () => {
    render(
      <ChatLog>
        <UserMessage>{'<img src=x onerror=alert(1)>'}</UserMessage>
      </ChatLog>,
    )
    expect(document.querySelector('[role="log"] img')).toBeNull()
    expect(screen.getByRole('listitem')).toHaveTextContent('<img src=x onerror=alert(1)>')
  })

  it('el avatar del asistente es decorativo', () => {
    const { container } = render(
      <ChatLog>
        <AssistantMessage>Hola</AssistantMessage>
      </ChatLog>,
    )
    expect(container.querySelector('svg')?.closest('[aria-hidden="true"]')).not.toBeNull()
  })

  it('la HU encontrada muestra título, detalle y sus acciones', () => {
    render(<FoundIssue title="DEMO-3, Renovar un préstamo" detail="Épica DEMO-1 · 2 criterios y 2 reglas" actions={<button type="button">Evolucionar DEMO-3</button>} />)
    expect(screen.getByText('DEMO-3, Renovar un préstamo')).toBeInTheDocument()
    expect(screen.getByText('Épica DEMO-1 · 2 criterios y 2 reglas')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeInTheDocument()
  })

  it('la operación fijada lleva el candado y su explicación', () => {
    const { container } = render(
      <FixedOperation title="Operación fijada: evolucionar DEMO-3">
        No cambia durante la conversación; es lo único que se podrá aprobar y publicar.
      </FixedOperation>,
    )
    expect(screen.getByText('Operación fijada: evolucionar DEMO-3')).toBeInTheDocument()
    expect(container.querySelector('svg[data-icon="lock"]')).toHaveAttribute('aria-hidden', 'true')
  })
})
