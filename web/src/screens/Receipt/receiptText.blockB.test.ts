// Bloque B · textos del recibo con datos raros (UI.md §4.6, contrato §5.2; DESIGN-DECISIONS.md §4 bis,
// «Recibo de aprobación»). `plan` es `Record<string, string>[]` en el contrato: puede faltar cualquier campo.
import { describe, expect, it } from 'vitest'
import { aiNotice, receiptOperations, reviewedCounter } from './receiptText.ts'

const TITLE = 'Renovar un préstamo (ficticia)'

describe('receiptOperations con datos raros', () => {
  it('un plan vacío no da ninguna operación', () => {
    expect(receiptOperations([], 1, TITLE, null)).toEqual([])
  })

  it('una operación sin `op` se muestra tal cual, como texto, con sus campos', () => {
    const [operation] = receiptOperations([{ key: 'DEMO-3', project: 'DEMO' }], 1, TITLE, null)
    expect(operation?.label).toBe('Operación «sin nombre»')
    expect(operation?.detail).toBe('key: DEMO-3 · project: DEMO')
  })

  it('una operación desconocida sin más campos no lleva detalle', () => {
    expect(receiptOperations([{ op: 'archivar' }], 1, TITLE, null)[0]).toEqual({ id: '0-archivar', label: 'Operación «archivar»', detail: undefined })
  })

  it('el texto de una operación desconocida no se interpreta (HTML o saltos tal cual)', () => {
    const [operation] = receiptOperations([{ op: '<b>x</b>', nota: 'línea\nsegunda' }], 1, TITLE, null)
    expect(operation?.label).toBe('Operación «<b>x</b>»')
    expect(operation?.detail).toBe('nota: línea\nsegunda')
  })

  it('las claves de las casillas son únicas aunque el plan repita la misma operación', () => {
    const plan = [
      { op: 'link', from: 'DEMO-3', to: 'DEMO-2' },
      { op: 'link', from: 'DEMO-3', to: 'DEMO-2' },
      { op: 'link', from: 'DEMO-3', to: 'DEMO-2' },
    ]
    const ids = receiptOperations(plan, 1, TITLE, null).map((operation) => operation.id)
    expect(new Set(ids).size).toBe(3)
  })

  it('un vínculo sin `type` usa «relates to» (D-09) y sin motivo en `impact`', () => {
    expect(receiptOperations([{ op: 'link', from: 'DEMO-3', to: 'DEMO-7' }], 1, TITLE, null)[0]?.detail).toBe('Vínculo «relates to».')
  })

  it('el motivo del vínculo se recorta y acaba en un solo punto', () => {
    const impact = { diffs: [], affected: [{ jira_key: 'DEMO-2', reason: '  Comparte la regla RN-02.  ', kind: 'rule' as const }], regression_notes: [] }
    expect(receiptOperations([{ op: 'link', from: 'DEMO-3', to: 'DEMO-2' }], 1, TITLE, impact)[0]?.detail).toBe('Comparte la regla RN-02.')
  })

  it('un `impact` con listas vacías usa el título o el tipo de vínculo', () => {
    const impact = { diffs: [], affected: [], regression_notes: [] }
    const ops = receiptOperations(
      [
        { op: 'update_story', project: 'DEMO', key: 'DEMO-3' },
        { op: 'link', from: 'DEMO-3', to: 'DEMO-2', type: 'relates to' },
      ],
      2,
      TITLE,
      impact,
    )
    const detailOf = (label: string) => ops.find((operation) => operation.label === label)?.detail
    expect(detailOf('Actualizar DEMO-3 con la versión 2')).toBe(TITLE)
    expect(detailOf('Vincular DEMO-3 con DEMO-2')).toBe('Vínculo «relates to».')
  })

  // Fija un fallo ya corregido al cerrar el bloque B. Antes: src/screens/Receipt/receiptText.ts:30 — `linkReason` hace `impact?.affected.find(…)` sin
  // proteger `affected` (TypeError), mientras que `changedFields` (línea 18) sí protege `diffs` con `?? []`.
  it('un `impact` sin `diffs` ni `affected` no rompe y usa el título o el tipo de vínculo', () => {
    const impact = {} as never
    const ops = receiptOperations(
      [
        { op: 'update_story', project: 'DEMO', key: 'DEMO-3' },
        { op: 'link', from: 'DEMO-3', to: 'DEMO-2', type: 'relates to' },
      ],
      2,
      TITLE,
      impact,
    )
    const detailOf = (label: string) => ops.find((operation) => operation.label === label)?.detail
    expect(detailOf('Actualizar DEMO-3 con la versión 2')).toBe(TITLE)
    expect(detailOf('Vincular DEMO-3 con DEMO-2')).toBe('Vínculo «relates to».')
  })

  it('publish_suite sin `cases` habla de «las subtareas»', () => {
    expect(receiptOperations([{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3' }], 1, TITLE, null)[0]?.label).toBe('Crear las subtareas en DEMO-3 con la etiqueta «caso-prueba»')
  })

  it('publish_suite con 0 casos usa el plural', () => {
    expect(receiptOperations([{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '0' }], 1, TITLE, null)[0]?.label).toBe('Crear 0 subtareas en DEMO-3 con la etiqueta «caso-prueba»')
  })

  // Fija un fallo ya corregido al cerrar el bloque B. Antes: src/screens/Receipt/receiptText.ts:60 — `Number('')` es 0 y `Number.isFinite(0)` es true,
  // así que `cases: ''` (o solo espacios) se pinta «Publicar 0 casos de prueba» en lugar del texto genérico.
  it('publish_suite con `cases` vacío habla de «las subtareas», no de 0', () => {
    expect(receiptOperations([{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '' }], 1, TITLE, null)[0]?.label).toBe('Crear las subtareas en DEMO-3 con la etiqueta «caso-prueba»')
  })

  // Fija un fallo ya corregido al cerrar el bloque B. Antes: src/screens/Receipt/receiptText.ts:50 y :40 — sin `key`, las plantillas interpolan `undefined`
  // y la casilla dice «Actualizar undefined con la versión 2».
  it('update_story sin `key` no pinta «undefined»', () => {
    expect(receiptOperations([{ op: 'update_story', project: 'DEMO' }], 2, TITLE, null).map((operation) => operation.label).join(' | ')).not.toMatch(/undefined/)
  })

  // Fija un fallo ya corregido al cerrar el bloque B. Antes: src/screens/Receipt/receiptText.ts:54 — sin `epic` ni `project` dice «Crear la HU en el proyecto undefined».
  it('create_story sin `project` ni `epic` no pinta «undefined»', () => {
    expect(receiptOperations([{ op: 'create_story' }], 1, TITLE, null)[0]?.label).not.toMatch(/undefined/)
  })

  // Fija un fallo ya corregido al cerrar el bloque B. Antes: src/screens/Receipt/receiptText.ts:58 — sin `from`/`to` dice «Vincular undefined con undefined».
  it('link sin `from` ni `to` no pinta «undefined»', () => {
    expect(receiptOperations([{ op: 'link', type: 'relates to' }], 1, TITLE, null)[0]?.label).not.toMatch(/undefined/)
  })
})

describe('reviewedCounter y aiNotice en el límite', () => {
  it.each([
    [0, 0, '0 de 0 revisadas'],
    [1, 1, 'Todo revisado'],
    [0, 1, '0 de 1 revisadas'],
    [3, 2, 'Todo revisado'],
  ])('%i de %i → «%s»', (checked, total, text) => {
    expect(reviewedCounter(checked, total)).toBe(text)
  })

  it('sin fuentes dice «0 fuentes»', () => {
    expect(aiNotice(0)).toBe('Generado con IA a partir de 0 fuentes. Revisa cada operación antes de aprobar.')
  })
})
