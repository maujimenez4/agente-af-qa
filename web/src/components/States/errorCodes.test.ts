import { describe, expect, it } from 'vitest'
import contract from '../../../../docs/api/openapi.yaml?raw'
import { KNOWN_ERROR_CODES, presentError } from './errorPresentation.ts'

// Valores de ErrorBody.code en el contrato (docs/api/openapi.yaml), leídos del enum.
function contractErrorCodes(): string[] {
  const body = contract.slice(contract.indexOf('    ErrorBody:'))
  const enumBlock = /code:\s*\n\s*type: string\s*\n\s*enum:\s*\n((?:\s*- [a-z_]+\n)+)/.exec(body)?.[1] ?? ''
  return [...enumBlock.matchAll(/- ([a-z_]+)/g)].map((match) => match[1] ?? '')
}

const FALLBACK_TITLE = 'No se pudo completar la acción'

describe('ErrorCard: los 28 códigos del contrato (DESIGN-DECISIONS.md §6, PA-306)', () => {
  const codes = contractErrorCodes()

  it('lee los 28 valores del enum de ErrorBody.code', () => {
    expect(codes).toHaveLength(28)
  })

  it('tiene título propio para cada código del contrato y para ninguno más', () => {
    expect([...KNOWN_ERROR_CODES].sort()).toEqual([...codes].sort())
  })

  it.each(codes)('«%s» no usa el título genérico', (code) => {
    expect(presentError({ code, message: 'x' }).title).not.toBe(FALLBACK_TITLE)
  })

  it.each([
    ['payload_too_large', 'Contenido demasiado grande', 'error', undefined],
    ['method_not_allowed', 'Acción no permitida', 'error', undefined],
    ['http_error', 'Petición no válida', 'error', undefined],
    ['handoff_unavailable', 'La HU ya no está disponible', 'warning', 'refresh'],
    ['operation_failed', 'No se pudo completar la operación', 'error', 'refresh'],
    ['not_in_error', 'No hay nada que reintentar', 'warning', 'refresh'],
    ['cancelled', 'Generación detenida', 'neutral', 'retry'],
    ['not_cancellable', 'No se puede detener', 'warning', 'refresh'],
    ['restart', 'La conversación no puede continuar', 'error', 'restart'],
    ['too_many_streams', 'Demasiadas pestañas abiertas', 'warning', 'retry'],
    ['provider_timeout', 'El modelo no respondió a tiempo', 'warning', 'regenerate'],
    ['invalid_model_output', 'La respuesta del modelo no es válida', 'error', 'regenerate'],
    ['citation_failed', 'La propuesta no es válida', 'error', 'regenerate'],
    ['coverage_failed', 'La suite no es válida', 'error', 'regenerate'],
    ['quality_failed', 'No se pudo revisar la calidad', 'error', 'retry'],
    ['publish_failed', 'No se puede publicar', 'error', 'backToReceipt'],
    ['unexpected', 'Error inesperado', 'error', 'retry'],
  ])('%s → «%s» (%s, acción %s)', (code, title, tone, action) => {
    expect(presentError({ code, message: 'x' })).toEqual({ title, tone, ...(action ? { action } : {}) })
  })

  it('un código fuera de la lista (versión futura) usa el respaldo', () => {
    expect(presentError({ code: 'nuevo_en_v2', message: 'x' })).toEqual({ title: FALLBACK_TITLE, tone: 'error' })
  })
})
