// Textos de Administración (T-29 mínima; UI.md §10, Ajustes de la «Propuesta v2» del lienzo).
import type { AdminModelOut, SettingsOut } from '../../api/types.ts'

export const ADMIN_TITLE = 'Ajustes'
export const ADMIN_SUBTITLE = 'Comprueba los servicios y consulta la configuración. Desde aquí no se genera ni se publica nada.'

export const CONNECTIONS_TITLE = 'Conexiones'
export const CONNECTIONS_IDLE = 'Aún no has probado las conexiones. La prueba tarda unos segundos y se puede repetir cada 10 s.'
export const CONNECTIONS_TESTING = 'Probando las conexiones…'
export const TEST_CONNECTIONS = 'Probar conexiones'
export const CONNECTION_OK = 'Conectado'
export const CONNECTION_FAILED = 'Con problemas'

export const MODELS_TITLE = 'Modelos por tarea'
export const MODELS_NOTE = 'Solo lectura: los modelos se cambian en config/models.yaml.'
export const EMBEDDINGS_LABEL = 'Embeddings'
export const NO_FALLBACK = 'Sin respaldo'

export const PUBLISH_TITLE = 'Modo de publicación'
export const PUBLISH_SIMULATION_NOTICE = 'Simulación: no se escribe nada en Jira'
export const PUBLISH_MODE_LABELS: Record<SettingsOut['publish_mode'], string> = {
  simulation: 'Simulación',
  live: 'Real',
}
export const PUBLISH_LIVE_TEXT = 'Al aprobar, se escribe en Jira lo que la persona confirma.'

export const DOCUMENTS_TITLE = 'Añadir documentos a la base de conocimiento'
export const DOCUMENTS_TEXT = 'PDF, DOCX, MD o TXT. Se clasifican y se indexan para usarlos como fuentes.'
export const USERS_TITLE = 'Usuarios y roles'
export const USERS_TEXT = 'Las cuentas de la demo se configuran en el servidor.'
export const SOON_ADMIN_TEXT = 'Disponible pronto: usuarios, documentos e historial llegan después del punto de control de la demo.'

export const ADMIN_FOOTER = 'Las claves se leen del .env y nunca se muestran. El administrador configura, pero no genera ni publica artefactos (D-01).'

/** Nombre de cada tarea del LLM (TaskType de adapters/base.py); una desconocida se muestra tal cual. */
const TASK_LABELS: Record<string, string> = {
  generate_story: 'Crear una HU',
  evolve_story: 'Evolucionar una HU',
  review_story: 'Revisar la calidad',
  analyze_impact: 'Analizar el impacto',
  generate_tests: 'Preparar las pruebas',
  synthesize_memory: 'Escribir la memoria',
  classify_source: 'Clasificar documentos',
  nl_to_jql: 'Buscar en Jira',
}

export function taskLabel(task: string): string {
  return Object.hasOwn(TASK_LABELS, task) ? (TASK_LABELS[task] ?? task) : task
}

export function modelName(model: Pick<AdminModelOut, 'provider' | 'model'>): string {
  return `${model.provider} · ${model.model}`
}

export function durationLabel(ms: number): string {
  return `${new Intl.NumberFormat('es-ES').format(Math.max(0, Math.round(ms)))} ms`
}
