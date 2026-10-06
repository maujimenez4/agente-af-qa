// Afirmaciones de docs/specs/UI.md v2.0 (T-56) sobre lo ya fusionado que no tenían una prueba que las respaldara:
// el pie de Origen (§4.3), la nota de la memoria del Resultado real (§4.7) y los textos fijos de Administración (§10).
// Solo datos sintéticos (DEMO-3, af-demo, admin-demo) y la API simulada (MSW).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import examples from '../api/examples.json'
import type { ConversationOut, PublishOutcome } from '../api/types.ts'
import { App } from '../App.tsx'
import { mockDb } from '../mocks/node.ts'
import { ResultScreen } from '../screens/Result/ResultScreen.tsx'

type WithResult = ConversationOut & { result: PublishOutcome }

const APPROVED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as WithResult

function storyResult(result: Partial<PublishOutcome>, state: ConversationOut['state']): WithResult {
  return { ...APPROVED, state, result: { ...APPROVED.result, ...result } } as WithResult
}

describe('UI.md §4.3 · Origen fijado, pie del panel', () => {
  it('test_generate_footer_says_one_model_call_when_operation_fixed', async () => {
    /** UI.md §4.3 Panel · Pie: *Generar propuesta* · «Una llamada al modelo. Después itera conversando.» */
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))

    const panel = screen.getByRole('complementary', { name: 'Antes de generar' })
    expect(within(panel).getByRole('button', { name: 'Generar propuesta' })).toBeInTheDocument()
    expect(within(panel).getByText('Una llamada al modelo. Después itera conversando.')).toBeInTheDocument()
  })
})

describe('UI.md §4.7 · Resultado de la HU, nota de la memoria', () => {
  it('test_published_story_says_memory_generated_and_indexed_when_real', () => {
    /** UI.md §4.7 Real: «… se ha generado e indexado; tendrá prioridad en las próximas propuestas.» */
    render(<ResultScreen conversation={storyResult({ simulated: false, published_keys: ['DEMO-3'] }, 'published')} />)
    const region = screen.getByRole('region', { name: 'Publicado en Jira' })
    expect(within(region).getByText(/se ha generado e indexado; tendrá prioridad en las próximas propuestas\.$/)).toBeInTheDocument()
  })

  it.each<[string, Partial<PublishOutcome>, ConversationOut['state'], RegExp]>([
    ['simulated', { simulated: true }, 'simulated', /Publicación simulada/],
    ['partial', { simulated: false, published_keys: ['DEMO-3'], errors: ['Fallo ficticio al vincular.'] }, 'approved', /Publicada en parte/],
  ])('test_memory_indexed_note_absent_when_%s', (_name, result, state, region) => {
    /** UI.md §4.7: la nota «generado e indexado» es solo del modo real con todo publicado. */
    render(<ResultScreen conversation={storyResult(result, state)} />)
    expect(within(screen.getByRole('region', { name: region })).queryByText(/se ha generado e indexado/)).toBeNull()
  })
})

describe('UI.md §10 · Administración, textos fijos', () => {
  async function openAdmin() {
    mockDb.session = { username: 'admin-demo', role: 'admin', csrf: 'csrf-ficticio' }
    render(<App />)
    return screen.findByRole('heading', { level: 1, name: 'Ajustes' })
  }

  it('test_admin_page_subtitle_and_footer_when_admin_enters', async () => {
    /** UI.md §10: subtítulo «Comprueba los servicios…» y pie «Las claves se leen del .env…» (D-01). */
    await openAdmin()
    expect(
      screen.getByText('Comprueba los servicios y consulta la configuración. Desde aquí no se genera ni se publica nada.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Las claves se leen del .env y nunca se muestran. El administrador configura, pero no genera ni publica artefactos (D-01).',
      ),
    ).toBeInTheDocument()
  })

  it('test_models_card_says_read_only_config_file_when_admin_enters', async () => {
    /** UI.md §10 Modelos por tarea: «Solo lectura: los modelos se cambian en config/models.yaml.» */
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modelos por tarea' })
    expect(within(card).getByText('Solo lectura: los modelos se cambian en config/models.yaml.')).toBeInTheDocument()
  })

  it('test_publish_mode_live_text_when_publish_mode_live', async () => {
    /** UI.md §10 Modo de publicación, en real: «Al aprobar, se escribe en Jira lo que la persona confirma.» */
    mockDb.settings = { ...mockDb.settings, publish_mode: 'live' }
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modo de publicación' })
    expect(await within(card).findByText('Al aprobar, se escribe en Jira lo que la persona confirma.')).toBeInTheDocument()
    expect(within(card).queryByText('Simulación: no se escribe nada en Jira')).toBeNull()
  })

  it('test_publish_mode_simulation_text_when_publish_mode_simulation', async () => {
    /** UI.md §10 Modo de publicación, en simulación: «Simulación: no se escribe nada en Jira» (texto literal). */
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modo de publicación' })
    expect(await within(card).findByText('Simulación: no se escribe nada en Jira')).toBeInTheDocument()
    expect(within(card).queryByText('Al aprobar, se escribe en Jira lo que la persona confirma.')).toBeNull()
  })
})
