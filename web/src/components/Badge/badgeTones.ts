export type BadgeTone = 'neutral' | 'cite' | 'new' | 'success' | 'warning' | 'error' | 'info' | 'plain'

/** Tipos de caso de prueba (RF-22) y su tono (lienzo QaIterar). */
export type CaseKind = 'Positivo' | 'Negativo' | 'Alterno' | 'Excepción'

export const CASE_KIND_TONE: Record<CaseKind, BadgeTone> = {
  Positivo: 'success',
  Negativo: 'error',
  Alterno: 'info',
  Excepción: 'warning',
}
