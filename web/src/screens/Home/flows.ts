import type { IconName } from '../../components/Icon/index.ts'
import { NEED_HINT } from '../../text/assistant.ts'

export type FlowId = 'need' | 'evolve' | 'review' | 'tests'

export interface FlowDefinition {
  id: FlowId
  label: string
  hint: string
  placeholder: string
  icon: IconName
  /** Permiso de core/permissions.py que hace falta (UI.md §3). */
  permission: 'generate_story' | 'generate_tests'
}

// Textos del lienzo (MixtoInicio) y UI.md §4.1.
export const FLOWS: readonly FlowDefinition[] = [
  {
    id: 'need',
    label: 'Nueva necesidad',
    hint: NEED_HINT,
    placeholder: 'Describe la necesidad. Si escribes una clave de Jira, por ejemplo DEMO-3, la reconozco.',
    icon: 'new',
    permission: 'generate_story',
  },
  {
    id: 'evolve',
    label: 'Evolucionar una HU',
    hint: 'Parte de una HU de Jira y propón su nueva versión con el diff.',
    placeholder: 'Escribe la clave de la HU, por ejemplo DEMO-3, y qué quieres cambiar.',
    icon: 'work',
    permission: 'generate_story',
  },
  {
    id: 'review',
    label: 'Revisar la calidad de una HU',
    hint: 'Informe con INVEST, ambigüedades y huecos. No cambia nada en Jira.',
    placeholder: 'Escribe la clave de la HU que quieres revisar, por ejemplo DEMO-4.',
    icon: 'searchSource',
    permission: 'generate_story',
  },
  {
    id: 'tests',
    label: 'Preparar pruebas',
    hint: 'Casos, cobertura, datos y estrategia de una HU.',
    placeholder: 'Escribe la clave de la HU para la que quieres pruebas, por ejemplo DEMO-3.',
    icon: 'tests',
    permission: 'generate_tests',
  },
]

// UI.md §3: ayuda de las tarjetas que el rol no puede usar.
export const DISABLED_HINT: Record<FlowDefinition['permission'], string> = {
  generate_story: 'Disponible para el rol de analista funcional.',
  generate_tests: 'Disponible para el rol QA.',
}

/** Flujo elegido por defecto: el primero que el rol puede usar (QA: «Preparar pruebas»). */
export function defaultFlow(permissions: readonly string[]): FlowId {
  return FLOWS.find((flow) => permissions.includes(flow.permission))?.id ?? 'need'
}
