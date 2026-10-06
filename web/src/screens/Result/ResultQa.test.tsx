// QA 4 · Recibo y QA 5 · Resultado (UI.md §6.4 y §6.5) de punta a punta contra la API simulada: escribir la clave de
// la HU, revisar la suite, aprobarla con su huella y ver el resultado simulado, publicado o en parte (PA-324: `approved`).
// Datos sintéticos (DEMO-3, qa-demo).
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ApproveIn } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openSuiteForDemo3 } from '../../test/qaFlow.tsx'
import { approvedLine, QA_OUTCOME_TEXTS } from './resultText.ts'

/** Huella de la suite en revisión del ejemplo del contrato (ConversationQaInReview). */
const QA_FINGERPRINT = '7c'.repeat(32)

async function approveSuite() {
  await openSuiteForDemo3()
  await userEvent.click(await screen.findByRole('button', { name: 'Revisar y aprobar' }))
  const receipt = await screen.findByRole('region', { name: 'Suite, versión 1 lista para revisar' })
  return receipt
}

describe('QA 4 · Recibo', () => {
  it('cabecera de la suite, una casilla con las subtareas y los adjuntos, y el historial de la suite', async () => {
    const receipt = await approveSuite()
    expect(screen.getByRole('heading', { level: 1, name: 'Pruebas de DEMO-3' })).toBeInTheDocument()
    const operations = within(receipt).getByRole('group', { name: /Qué se hará en Jira/ })
    const boxes = within(operations).getAllByRole('checkbox')
    expect(boxes).toHaveLength(1)
    expect(operations).toHaveTextContent('Crear 4 subtareas en DEMO-3 con la etiqueta «caso-prueba»')
    expect(operations).toHaveTextContent('Adjunta estrategia-DEMO-3.md y matriz-DEMO-3.md.')
    // La suite del ejemplo del contrato trae una sola fuente (la HU en Jira): singular.
    expect(within(receipt).getByText(/^Generado con IA a partir de la HU y 1 fuente\./)).toBeInTheDocument()
    expect(within(receipt).getByRole('button', { name: 'Volver a la suite' })).toBeInTheDocument()
    const history = screen.getByRole('complementary', { name: 'Historial de la suite' })
    expect(within(history).getByRole('list', { name: 'Versiones de la suite' })).toHaveTextContent('4 casos · cobertura validada')
  })

  it('*Volver a la suite* vuelve a Iterar la suite', async () => {
    const receipt = await approveSuite()
    await userEvent.click(within(receipt).getByRole('button', { name: 'Volver a la suite' }))
    expect(await screen.findByRole('complementary', { name: 'Suite de pruebas' })).toBeInTheDocument()
  })
})

describe('QA 5 · Resultado', () => {
  it('simulado: aprueba con la huella exacta de la suite y muestra la publicación simulada de la suite', async () => {
    const bodies: ApproveIn[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/approve')) bodies.push((await request.clone().json()) as ApproveIn)
    })
    const receipt = await approveSuite()
    await userEvent.click(within(receipt).getAllByRole('checkbox')[0] as HTMLElement)
    await userEvent.click(within(receipt).getByRole('button', { name: 'Aprobar y publicar' }))
    const region = await screen.findByRole('region', { name: 'Publicación simulada' })
    expect(bodies).toEqual([{ fingerprint: QA_FINGERPRINT }])
    expect(within(region).getByText(QA_OUTCOME_TEXTS.simulated.note)).toBeInTheDocument()
    expect(within(region).queryByText(/memoria/i)).toBeNull()
    expect(within(region).getByText(/^Suite versión 1 aprobada por qa-demo/)).toBeInTheDocument()
    expect(within(region).queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
    // §6.5: en QA, la simulación solo ofrece la auditoría.
    expect(within(region).getByRole('button', { name: 'Ver el registro de auditoría' })).toBeInTheDocument()
    expect(within(region).queryByRole('button', { name: 'Ir al historial' })).toBeNull()
    mockServer.events.removeAllListeners()
  })

  it('publicado: «Suite publicada en Jira», las subtareas creadas y *Registrar la ejecución* disponible pronto', async () => {
    mockDb.forceApprove = 'published'
    const receipt = await approveSuite()
    await userEvent.click(within(receipt).getAllByRole('checkbox')[0] as HTMLElement)
    await userEvent.click(within(receipt).getByRole('button', { name: 'Aprobar y publicar' }))
    const region = await screen.findByRole('region', { name: 'Suite publicada en Jira' })
    expect(screen.getByRole('img', { name: 'Avance: fase 4 de 4, Publicado' })).toBeInTheDocument()
    expect(within(region).getByText('Claves en Jira: DEMO-21, DEMO-22, DEMO-23, DEMO-24')).toBeInTheDocument()
    expect(within(region).getByRole('list', { name: 'Operaciones hechas en Jira' })).toHaveTextContent('Crear 4 subtareas en DEMO-3')
    expect(within(region).getByRole('button', { name: 'Registrar la ejecución' })).toHaveAccessibleDescription('Registrar la ejecución de las pruebas llega más adelante.')
    // Con `jira_browse_url` en /settings pasa a ser un enlace: se espera a que llegue (sin carrera).
    expect(await within(region).findByRole('link', { name: /Abrir DEMO-3 en Jira/ })).toBeInTheDocument()
    expect(within(region).queryByRole('button', { name: 'Ver la memoria' })).toBeNull()
    expect(within(region).queryByText(/memoria/i)).toBeNull()
  })

  it('en parte (PA-324): la suite queda en `approved` con el caso que falló y lo creado se mantiene', async () => {
    mockDb.forceApprove = 'partial'
    const receipt = await approveSuite()
    await userEvent.click(within(receipt).getAllByRole('checkbox')[0] as HTMLElement)
    await userEvent.click(within(receipt).getByRole('button', { name: 'Aprobar y publicar' }))
    const region = await screen.findByRole('region', { name: 'Publicada en parte' })
    // Como la HU (PA-304: el lienzo dice fase 3).
    expect(screen.getByRole('img', { name: 'Avance: fase 4 de 4, Publicada en parte' })).toBeInTheDocument()
    // §6.5: en parte no se ofrece registrar la ejecución (lo que toca es reintentar los fallidos, PA-05).
    expect(within(region).queryByRole('button', { name: 'Registrar la ejecución' })).toBeNull()
    expect(await within(region).findByRole('link', { name: /Abrir DEMO-3 en Jira/ })).toBeInTheDocument()
    const failed = within(region).getByRole('alert')
    expect(failed).toHaveTextContent('No se pudo crear CP-04: Jira no respondió (mensaje ficticio).')
    expect(failed).toHaveTextContent('Fallaron: CP-04')
    expect(within(region).getByText('Claves en Jira: DEMO-21, DEMO-22, DEMO-23')).toBeInTheDocument()
    expect(within(region).getByText(QA_OUTCOME_TEXTS.partial.note)).toBeInTheDocument()
    const run = [...mockDb.runs.values()].find((item) => item.conversation.mode === 'qa')
    expect(run?.conversation.state).toBe('approved')
  })
})

describe('approvedLine', () => {
  it('«Suite versión 2 aprobada por…» en QA y «Versión 2 aprobada por…» en la HU', () => {
    const result = { approved_by: 'qa-demo', approved_at: 'no-es-fecha' } as Parameters<typeof approvedLine>[1]
    expect(approvedLine(2, result, true)).toBe('Suite versión 2 aprobada por qa-demo')
    expect(approvedLine(2, result)).toBe('Versión 2 aprobada por qa-demo')
  })
})
