// PA-429: al final de Generando e Iterar, el último mensaje (y su botón «Ver la propuesta») quedaba cortado:
// la conversación no bajaba sola. Ahora deja margen al final y, al llegar un mensaje, baja hasta él si la persona
// seguía el final; un mensaje suyo baja siempre. jsdom no calcula el diseño: las medidas del contenedor se fijan
// en la prueba y se comprueba la estructura y la llamada a `scrollTo`. Datos sintéticos.
import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AssistantMessage, ChatLog, UserMessage } from '../Chat/index.ts'
import { NEAR_BOTTOM_PX } from './useStickToBottom.ts'
import { Workspace } from './Workspace.tsx'

type Message = { author: 'user' | 'assistant'; text: string }

function Conversation({ messages }: { messages: Message[] }) {
  return (
    <Workspace title="Evolucionar DEMO-3">
      <ChatLog>
        {messages.map((message, index) =>
          message.author === 'user' ? (
            <UserMessage key={index}>{message.text}</UserMessage>
          ) : (
            <AssistantMessage key={index}>
              <p>{message.text}</p>
            </AssistantMessage>
          ),
        )}
      </ChatLog>
    </Workspace>
  )
}

/** El contenedor que se desplaza, con medidas fijas (jsdom no las calcula) y `scrollTo` espiado. */
function measuredScroller(scrollHeight: number, clientHeight: number) {
  const scroller = document.querySelector<HTMLElement>('[data-chat-scroll]')
  if (!scroller) throw new Error('Sin el contenedor de la conversación')
  Object.defineProperty(scroller, 'scrollHeight', { configurable: true, get: () => scrollHeight })
  Object.defineProperty(scroller, 'clientHeight', { configurable: true, get: () => clientHeight })
  const scrollTo = vi.fn()
  scroller.scrollTo = scrollTo as unknown as typeof scroller.scrollTo
  return { scroller, scrollTo }
}

/** La persona desplaza la conversación hasta `top` (como el evento real). */
function scrollAt(scroller: HTMLElement, top: number) {
  scroller.scrollTop = top
  scroller.dispatchEvent(new Event('scroll'))
}

function stubReducedMotion(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches, media: '(prefers-reduced-motion: reduce)', addEventListener: () => undefined, removeEventListener: () => undefined })))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Conversación · el último mensaje se ve entero (PA-429)', () => {
  it('deja margen al final: el contenedor que se desplaza y la columna de mensajes', () => {
    render(<Conversation messages={[{ author: 'assistant', text: 'Propuesta lista' }]} />)
    const scroller = document.querySelector('[data-chat-scroll]')
    expect(scroller).not.toBeNull()
    expect(scroller?.firstElementChild?.contains(screen.getByRole('log'))).toBe(true)
  })

  it('con la persona al final, un mensaje nuevo baja hasta el final (margen incluido)', async () => {
    stubReducedMotion(false)
    const first: Message[] = [{ author: 'assistant', text: 'Generando…' }]
    const view = render(<Conversation messages={first} />)
    const { scroller, scrollTo } = measuredScroller(1500, 500)
    scrollAt(scroller, 1000) // abajo del todo
    await act(async () => view.rerender(<Conversation messages={[...first, { author: 'assistant', text: 'Propuesta lista · Ver la propuesta' }]} />))
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 1500, behavior: 'smooth' })
  })

  it('si la persona subió a leer, un mensaje del asistente no la mueve', async () => {
    stubReducedMotion(false)
    const first: Message[] = [{ author: 'assistant', text: 'Generando…' }]
    const view = render(<Conversation messages={first} />)
    const { scroller, scrollTo } = measuredScroller(1500, 500)
    scrollAt(scroller, 1000 - NEAR_BOTTOM_PX - 1) // más arriba que el margen de «cerca del final»
    await act(async () => view.rerender(<Conversation messages={[...first, { author: 'assistant', text: 'Propuesta lista' }]} />))
    expect(scrollTo).not.toHaveBeenCalled()
  })

  it('un mensaje de la persona baja siempre, aunque hubiera subido', async () => {
    stubReducedMotion(false)
    const first: Message[] = [{ author: 'assistant', text: 'Propuesta lista' }]
    const view = render(<Conversation messages={first} />)
    const { scroller, scrollTo } = measuredScroller(1500, 500)
    scrollAt(scroller, 0)
    await act(async () => view.rerender(<Conversation messages={[...first, { author: 'user', text: 'Añade un criterio ficticio' }]} />))
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 1500, behavior: 'smooth' })
  })

  it('con «reducir movimiento», baja sin animación', async () => {
    stubReducedMotion(true)
    const first: Message[] = [{ author: 'assistant', text: 'Generando…' }]
    const view = render(<Conversation messages={first} />)
    const { scroller, scrollTo } = measuredScroller(900, 500)
    scrollAt(scroller, 400)
    await act(async () => view.rerender(<Conversation messages={[...first, { author: 'assistant', text: 'Propuesta lista' }]} />))
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 900, behavior: 'auto' })
  })
})
