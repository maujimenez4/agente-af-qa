// Revisión general del pulido (axe): el chat es un `log` que contiene una lista de mensajes, y el cuerpo de un panel
// sin controles se puede enfocar con Tab si se le da nombre (`bodyLabel`). Datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SidePanel } from '../Workspace/index.ts'
import { AssistantMessage, ChatLog, UserMessage } from './Chat.tsx'

describe('ChatLog · lista de mensajes dentro del log', () => {
  it('test_messages_are_list_items_of_a_list_inside_the_log', () => {
    render(
      <ChatLog>
        <UserMessage>Pide un cambio ficticio</UserMessage>
        <AssistantMessage>Versión 2 lista (ficticia).</AssistantMessage>
      </ChatLog>,
    )
    const log = screen.getByRole('log', { name: 'Conversación' })
    const list = within(log).getByRole('list')
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
  })
})

describe('SidePanel · bodyLabel', () => {
  it('test_body_with_label_is_a_named_region_reachable_with_tab', async () => {
    render(
      <SidePanel title="Informe de calidad" bodyLabel="Contenido del informe de calidad">
        <p>Informe ficticio sin controles.</p>
      </SidePanel>,
    )
    const body = screen.getByRole('region', { name: 'Contenido del informe de calidad' })
    await userEvent.tab()
    expect(body).toHaveFocus()
  })

  it('test_body_without_label_is_not_a_tab_stop', () => {
    render(
      <SidePanel title="Propuesta de HU">
        <p>Propuesta ficticia.</p>
      </SidePanel>,
    )
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    expect(screen.getByText('Propuesta ficticia.').parentElement).not.toHaveAttribute('tabindex')
  })
})
