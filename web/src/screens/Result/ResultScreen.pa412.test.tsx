// PA-412 · Nota del Resultado simulado: la simulación gasta la aprobación (PA-41), así que la nota ya no dice que
// «sigue vigente». Se fijan los textos nuevos de HU y de QA, que la de QA no nombra la memoria y que los resultados
// publicado y en parte conservan sus notas. Datos sintéticos (DEMO-3, DEMO-21, af-demo, qa-demo, «(ficticio)»).
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { mockSuiteConversation } from '../../mocks/qaSuite.ts'
import { ResultScreen } from './ResultScreen.tsx'
import { OUTCOME_TEXTS, QA_OUTCOME_TEXTS } from './resultText.ts'

type WithResult = ConversationOut & { result: PublishOutcome }

const HU_SIMULATED_NOTE =
  'La aprobación se ha usado en esta simulación. Para publicar de verdad, activa el modo real y empieza de nuevo desde la misma HU para revisarla y aprobarla. La memoria se genera al publicar de verdad.'
const QA_SIMULATED_NOTE =
  'La aprobación se ha usado en esta simulación. Para publicar de verdad, activa el modo real y empieza de nuevo desde la misma HU para revisar la suite y aprobarla.'

// Notas de publicado y en parte anteriores a PA-412 (no deben cambiar).
const HU_PUBLISHED_NOTE = 'La memoria de la HU se ha generado e indexado; tendrá prioridad en las próximas propuestas.'
const HU_PARTIAL_NOTE =
  'Lo publicado se queda en Jira. Reintentar solo lo que falló llegará más adelante (PA-05); mientras, revisa las operaciones en Jira.'
const QA_PUBLISHED_NOTE = 'Cuando ejecutes las pruebas, podrás registrar aquí el resultado (llega más adelante).'
const QA_PARTIAL_NOTE =
  'Lo creado se mantiene. Reintentar solo lo que falló llegará más adelante; mientras, revisa las subtareas en Jira.'

const HU_BASE = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as WithResult

function huConversation(state: ConversationOut['state'], result: Partial<PublishOutcome>): WithResult {
  return { ...HU_BASE, state, result: { ...HU_BASE.result, ...result } }
}

const QA_BASE = mockSuiteConversation('DEMO-3')

function qaConversation(state: ConversationOut['state'], result: Partial<PublishOutcome>): WithResult {
  return {
    ...QA_BASE,
    title: 'Preparar pruebas de DEMO-3',
    state,
    review: null,
    result: {
      simulated: false,
      plan: QA_BASE.review?.plan ?? [],
      approved_by: 'qa-demo',
      approved_at: '2026-10-05T10:30:00Z',
      published_keys: [],
      errors: [],
      failed_ids: [],
      ...result,
    },
  } as WithResult
}

const HU = {
  simulated: huConversation('simulated', { simulated: true }),
  published: huConversation('published', { simulated: false, published_keys: ['DEMO-3'], errors: [], failed_ids: [] }),
  partial: huConversation('approved', { simulated: false, published_keys: ['DEMO-3'], errors: ['Fallo ficticio al vincular'], failed_ids: [] }),
}

const QA = {
  simulated: qaConversation('simulated', { simulated: true }),
  published: qaConversation('published', { published_keys: ['DEMO-21', 'DEMO-22'] }),
  partial: qaConversation('approved', { published_keys: ['DEMO-21'], failed_ids: ['CP-02'] }),
}

describe('PA-412 · nota del Resultado simulado', () => {
  it('test_simulated_story_note_shows_exact_text_when_simulated', () => {
    /** Criterio 1 (HU): en simulación se ve el texto nuevo exacto de la nota. */
    render(<ResultScreen conversation={HU.simulated} />)
    const region = screen.getByRole('region', { name: 'Publicación simulada' })
    expect(within(region).getByText(HU_SIMULATED_NOTE)).toBeInTheDocument()
    expect(OUTCOME_TEXTS.simulated.note).toBe(HU_SIMULATED_NOTE)
  })

  it('test_simulated_suite_note_shows_exact_text_when_simulated', () => {
    /** Criterio 1 (QA): en simulación de una suite se ve el texto nuevo exacto de la nota. */
    render(<ResultScreen conversation={QA.simulated} />)
    const region = screen.getByRole('region', { name: 'Publicación simulada' })
    expect(within(region).getByText(QA_SIMULATED_NOTE)).toBeInTheDocument()
    expect(QA_OUTCOME_TEXTS.simulated.note).toBe(QA_SIMULATED_NOTE)
  })

  it('test_simulated_notes_differ_between_story_and_suite', () => {
    /** Criterio 1 (límite): la nota de QA no hereda la de HU por el `...OUTCOME_TEXTS.simulated`. */
    expect(QA_OUTCOME_TEXTS.simulated.note).not.toBe(OUTCOME_TEXTS.simulated.note)
  })

  it.each([
    ['HU', HU.simulated],
    ['QA', QA.simulated],
  ])('test_simulated_result_never_says_approval_still_valid_%s', (_kind, conversation) => {
    /** Criterio 2: ningún texto de la pantalla del Resultado simulado dice que la aprobación «sigue vigente». */
    const { container } = render(<ResultScreen conversation={conversation} />)
    expect(container.textContent ?? '').not.toMatch(/sigue vigente/i)
    expect(container.textContent ?? '').not.toMatch(/sin repetir la revisión/i)
  })

  it('test_simulated_texts_never_say_approval_still_valid_in_any_constant', () => {
    /** Criterio 2 (negativo): ningún texto de resultado, de HU ni de QA, conserva «sigue vigente». */
    for (const texts of [...Object.values(OUTCOME_TEXTS), ...Object.values(QA_OUTCOME_TEXTS)]) {
      expect(texts.note).not.toMatch(/sigue vigente/i)
    }
  })

  it('test_simulated_suite_note_omits_memory_when_qa', () => {
    /** Criterio 3: la nota simulada de QA no menciona la memoria (sí lo hace la de HU). */
    expect(QA_OUTCOME_TEXTS.simulated.note).not.toMatch(/memoria/i)
    expect(OUTCOME_TEXTS.simulated.note).toMatch(/memoria/i)
    render(<ResultScreen conversation={QA.simulated} />)
    const region = screen.getByRole('region', { name: 'Publicación simulada' })
    expect(within(region).queryByText(/memoria/i)).toBeNull()
  })

  it.each([
    ['HU publicada', HU.published, 'Publicado en Jira', HU_PUBLISHED_NOTE],
    ['HU en parte', HU.partial, 'Publicada en parte', HU_PARTIAL_NOTE],
    ['QA publicada', QA.published, 'Suite publicada en Jira', QA_PUBLISHED_NOTE],
    ['QA en parte', QA.partial, 'Publicada en parte', QA_PARTIAL_NOTE],
  ])('test_non_simulated_note_unchanged_when_%s', (_kind, conversation, title, note) => {
    /** Criterio 4: los resultados publicado y en parte mantienen su nota y no muestran la de la simulación. */
    render(<ResultScreen conversation={conversation} />)
    const region = screen.getByRole('region', { name: title })
    expect(within(region).getByText(note)).toBeInTheDocument()
    expect(within(region).queryByText(/La aprobación se ha usado en esta simulación/)).toBeNull()
  })

  it('test_non_simulated_constants_unchanged', () => {
    /** Criterio 4 (constantes): las notas de publicado y en parte son las de antes de PA-412. */
    expect(OUTCOME_TEXTS.published.note).toBe(HU_PUBLISHED_NOTE)
    expect(OUTCOME_TEXTS.partial.note).toBe(HU_PARTIAL_NOTE)
    expect(QA_OUTCOME_TEXTS.published.note).toBe(QA_PUBLISHED_NOTE)
    expect(QA_OUTCOME_TEXTS.partial.note).toBe(QA_PARTIAL_NOTE)
  })
})
